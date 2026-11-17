"""
Node 4: Outreach Package Generation Layer (drafter.py).

Implements the strict 6-step Referral DM Specification:
  - Step 1: Deterministic Signal Check (BITS_FULL_TIME, BITS_WILP, AI_ML_OVERLAP, MUTUAL, PLAIN_DIRECT).
  - Step 2: Honest State of Role, Job ID/Link & Experience Stretch Check (if required_yoe >= 2).
  - Step 3: Plain description of Param Patel's real projects (1-2 sentences, zero puffery/adjectives).
  - Step 4: Standalone portfolio link sentence: "You can see my work here: https://param-dev.vercel.app."
  - Step 5: Direct low-pressure referral ask + advice close.
  - Step 6: Deterministic post-processor (sanitize_referral_dm):
      * Replaces em dashes (-- / —) with commas or periods.
      * Replaces exclamation marks (!) with periods (.).
      * Strips "Thanks for connecting" openers.
      * Strips banned AI-tell phrases ("aligns perfectly", "directly addresses", "cutting-edge",
        "groundbreaking", "passionate about", "synergy", "thrilled", "excited to").
      * Enforces a single plain paragraph of 3 to 5 sentences.
  - Connection notes are set to "Send Blank Connection Request (Free-tier strategy)" (saving tokens & UI).
  - Direct Email Draft: Clean, honest email for Hunter.io outreach.
"""

import re
import logging
from typing import List, Tuple, Optional, Dict, Any

from src.models import (
    JobPosting,
    CompanyIntel,
    MatchAndTailorResult,
    ContactPerson,
    OutreachPackage,
)
from src.llm_router import invoke_structured_llm

logger = logging.getLogger("referral.drafter")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

PORTFOLIO_URL = "https://param-dev.vercel.app"
BLANK_CONNECTION_STRATEGY = "Send Blank Connection Request (Free-tier strategy)"

# Param Patel's Real Projects (profile_context.yaml)
PARAM_PROJECT_MAP: Dict[str, Dict[str, Any]] = {
    "agent_diagnostician": {
        "title": "Agent Failure Diagnostician",
        "description": "an open-source PyPI library for diagnosing multi-agent LLM trace failures",
        "keywords": ["multi-agent", "agent", "agents", "langchain", "langgraph", "llm", "eval", "observability", "debugging", "traces", "guardrails"]
    },
    "tempus_rag": {
        "title": "TempusRAG",
        "description": "a hybrid BM25 and vector RAG system for auditing multi-year SEC 10-K filings",
        "keywords": ["rag", "retrieval", "vector", "search", "embeddings", "reranking", "nlp", "sec", "finance", "hybrid"]
    },
    "lidar_parser": {
        "title": "LiDAR PCAP Converter",
        "description": "a C++ and Python library on PyPI that parses offline 3D LiDAR packets at 2.08M points per second",
        "keywords": ["c++", "lidar", "computer vision", "low latency", "3d", "sensor", "point cloud", "systems", "performance", "optimization"]
    },
    "fairtrace": {
        "title": "FairTrace",
        "description": "a LightGBM credit-risk pipeline with deterministic adverse action reporting",
        "keywords": ["fintech", "credit", "risk", "tabular", "lightgbm", "fairness", "compliance", "banking", "governance", "adverse action"]
    }
}

BANNED_AI_REPLACEMENTS = [
    (re.compile(r"\baligns\s+perfectly(?:\s+with)?\b", re.IGNORECASE), "relates to"),
    (re.compile(r"\bdirectly\s+addresses\b", re.IGNORECASE), "addresses"),
    (re.compile(r"\bcutting-?edge\b", re.IGNORECASE), "modern"),
    (re.compile(r"\bgroundbreaking\b", re.IGNORECASE), "practical"),
    (re.compile(r"\bpassionate\s+about\b", re.IGNORECASE), "interested in"),
    (re.compile(r"\bsynergy\b", re.IGNORECASE), "collaboration"),
    (re.compile(r"\bthrilled(?:\s+to)?\b", re.IGNORECASE), "glad to"),
    (re.compile(r"\bexcited\s+to\b", re.IGNORECASE), "looking to"),
]

BANNED_WORDS = [
    "aligns perfectly",
    "directly addresses",
    "cutting-edge",
    "cutting edge",
    "groundbreaking",
    "passionate about",
    "synergy",
    "thrilled",
    "excited to",
]


def determine_opener_type(contact: ContactPerson) -> str:
    """
    Step 1: Deterministic Signal Check.
    1. If is_bits_alum == True and bits_type == "FULL_TIME" -> "BITS_FULL_TIME"
    2. If is_bits_alum == True and bits_type == "WILP" -> "BITS_WILP"
    3. Else if stated_ai_ml_interest == True -> "AI_ML_OVERLAP"
    4. Else if mutual_connections == True -> "MUTUAL"
    5. Else -> "PLAIN_DIRECT"
    """
    if contact.is_bits_alum and contact.bits_type == "FULL_TIME":
        return "BITS_FULL_TIME"
    elif contact.is_bits_alum and contact.bits_type == "WILP":
        return "BITS_WILP"
    elif contact.stated_ai_ml_interest:
        return "AI_ML_OVERLAP"
    elif contact.mutual_connections:
        return "MUTUAL"
    return "PLAIN_DIRECT"


def extract_ai_topic(text: str) -> str:
    """Extracts a clean, specific AI topic from the contact's headline if available."""
    if not text:
        return "AI/ML"
    text_lower = text.lower()
    if "agent" in text_lower or "langgraph" in text_lower:
        return "AI agents"
    if "rag" in text_lower or "retrieval" in text_lower:
        return "RAG and search systems"
    if "llm" in text_lower or "genai" in text_lower or "generative ai" in text_lower:
        return "LLM applications"
    if "computer vision" in text_lower or "vision" in text_lower:
        return "computer vision"
    if "nlp" in text_lower:
        return "NLP systems"
    if "machine learning" in text_lower or "ml" in text_lower:
        return "machine learning"
    if "data science" in text_lower:
        return "data science"
    return "AI/ML"


def detect_seniority(headline: str) -> str:
    """Detects seniority tier from contact headline."""
    if not headline:
        return "Peer/Junior"
    pattern = r"\b(?:manager|director|head|lead|leads|leading|principal|staff|vp|vice president|founder|co-founder|chief|cto|partner|architect)\b"
    if re.search(pattern, headline, re.IGNORECASE):
        return "Senior/Leadership"
    return "Peer/Junior"


def select_projects_for_contact(
    contact: ContactPerson,
    match_result: Optional[MatchAndTailorResult] = None,
    jd_text: str = "",
) -> List[str]:
    """
    Selects 1 or 2 plain project descriptions from Param's real project arsenal.
    - If contact.stated_ai_ml_interest or senior/mid technical -> 2 projects allowed.
    - If non-AI or pure infra/ops -> 1 project only.
    """
    primary_id = match_result.selected_project_id if match_result else "agent_diagnostician"
    if primary_id not in PARAM_PROJECT_MAP:
        primary_id = "agent_diagnostician"

    descs = [PARAM_PROJECT_MAP[primary_id]["description"]]

    can_mention_two = (
        contact.stated_ai_ml_interest
        or contact.years_experience_level in ("senior", "mid")
    )

    if can_mention_two:
        second_id = "tempus_rag" if primary_id != "tempus_rag" else "agent_diagnostician"
        descs.append(PARAM_PROJECT_MAP[second_id]["description"])

    return descs


def generate_deterministic_referral_dm(
    contact: ContactPerson,
    job: JobPosting,
    project_descs: List[str],
    opener_type: str,
) -> str:
    """
    Constructs a deterministic 4-to-5 sentence post-connection referral DM
    following the exact 6-step specification. Zero fluff, zero AI-tell words.
    """
    first_name = contact.name.split()[0] if contact.name else "there"
    job_id_str = f" (Job ID: {job.job_id})" if job.job_id else ""
    yoe = job.required_yoe or 0

    # Step 1: Opener Sentence
    if opener_type == "BITS_FULL_TIME":
        s1 = f"Hi {first_name}, fellow BITSian here, applying for the {job.role} role at {job.company}{job_id_str}."
    elif opener_type == "BITS_WILP":
        s1 = f"Hi {first_name}, saw the shared BITS Pilani connection and wanted to reach out as I'm applying for the {job.role} role at {job.company}{job_id_str}."
    elif opener_type == "AI_ML_OVERLAP":
        topic = extract_ai_topic(contact.headline)
        s1 = f"Hi {first_name}, saw you're working on {topic} at {job.company} and wanted to reach out as I'm applying for the {job.role} role{job_id_str}."
    elif opener_type == "MUTUAL":
        s1 = f"Hi {first_name}, noticed we share mutual connections and wanted to reach out as I'm applying for the {job.role} role at {job.company}{job_id_str}."
    else:  # PLAIN_DIRECT
        s1 = f"Hi {first_name}, I'm applying for the {job.role} role at {job.company}{job_id_str}."

    # Step 2 & 3: Experience Stretch Check & Plain Project Description
    proj_text = " and ".join(project_descs)
    if yoe >= 2:
        s2 = f"I know the experience bar is a stretch for where I'm at right now, but I recently built {proj_text}."
    else:
        s2 = f"I recently built {proj_text}."

    # Step 4: Standalone Portfolio Link Sentence
    s3 = f"You can see my work here: {PORTFOLIO_URL}."

    # Step 5: Low-Pressure Ask + Advice Close
    s4 = "Would really appreciate a referral if you think I'm a fit, and happy to share my resume and Job ID if helpful."
    s5 = "Either way, would love any advice you have for someone entering this space."

    return f"{s1} {s2} {s3} {s4} {s5}"


def sanitize_referral_dm(
    text: str,
    first_name: str = "",
    role_title: str = "",
    company: str = "",
    job_id: str = "",
    opener_type: str = "PLAIN_DIRECT",
    required_yoe: int = 0,
    project_descs: Optional[List[str]] = None,
) -> str:
    """
    Step 6: Deterministic Post-Processor.
    - Replaces any em dashes (-- or — or –) with commas or periods.
    - Replaces any exclamation marks (!) with periods (.).
    - Strips any "Thanks for connecting" or "Thank you for connecting" opener.
    - Strips banned AI-tell phrases.
    - Guarantees standalone portfolio link sentence.
    - Enforces a single plain paragraph of 3 to 5 sentences.
    """
    if not text or len(text.strip()) < 20:
        contact_stub = ContactPerson(
            name=first_name,
            headline="",
            linkedin_url="",
            tier="1_ALUMNI" if opener_type == "BITS_FULL_TIME" else "2_TEAM_ENGINEER_OR_HM",
            relevance_note="",
            is_bits_alum=(opener_type == "BITS_FULL_TIME"),
            bits_type="FULL_TIME" if opener_type == "BITS_FULL_TIME" else "NONE",
            stated_ai_ml_interest=(opener_type == "AI_ML_OVERLAP"),
        )
        job_stub = JobPosting(
            job_id=job_id,
            company=company,
            role=role_title,
            location="",
            jd_text="",
            job_url="",
            source="",
            required_yoe=required_yoe,
        )
        return generate_deterministic_referral_dm(
            contact_stub,
            job_stub,
            project_descs or [PARAM_PROJECT_MAP["agent_diagnostician"]["description"]],
            opener_type
        )

    cleaned = text.strip()

    # 1. Clean markdown headers, bullets, and bolding
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"^\s*[-*•#]+\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*\n+\s*", " ", cleaned).strip()

    # 2. Replace em dashes and en dashes with commas or periods
    cleaned = re.sub(r"\s*[—–]\s*|\s*--\s*", ", ", cleaned)

    # 3. Replace exclamation marks with periods
    cleaned = cleaned.replace("!", ".")

    # 4. Strip "Thanks for connecting" or "Thank you for connecting"
    cleaned = re.sub(
        r"(?i)\b(?:thanks|thank you)(?:\s+so much)?\s+for connecting[., ]*",
        "",
        cleaned
    ).strip()

    # 5. Clean banned AI-tell phrases
    for pat, repl in BANNED_AI_REPLACEMENTS:
        cleaned = pat.sub(repl, cleaned)

    for bw in BANNED_WORDS:
        cleaned = re.sub(rf"\b{re.escape(bw)}\b", "", cleaned, flags=re.IGNORECASE)

    # Clean double punctuation and spaces
    cleaned = re.sub(r",\s*,+", ",", cleaned)
    cleaned = re.sub(r"\.\s*\.+", ".", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # 6. Ensure proper opener greeting if missing
    if first_name and not re.match(rf"^(?:hi|hello|dear)\s+{re.escape(first_name)}\b", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"^(?:hi|hello|dear)\s+[^,]+,\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = f"Hi {first_name}, " + cleaned.lstrip(",.- ")

    # Guard against non-alumni mentioning BITSian
    if opener_type not in ("BITS_FULL_TIME", "BITS_WILP"):
        cleaned = re.sub(r"(?i)\bfellow\s+bitsian\s+here\s*(\([^\)]*\))?[,\.\-—\s]*", "", cleaned)
        cleaned = re.sub(r"(?i)\bbitsian\b", "engineer", cleaned)
        cleaned = re.sub(r"(?i)\bbits\s+pilani\b", "", cleaned)

    # 7. Ensure standalone portfolio sentence
    standalone_portfolio = f"You can see my work here: {PORTFOLIO_URL}."
    cleaned = re.sub(r"\bhttps?://[^\s)\]]+", "", cleaned)
    cleaned = re.sub(r"\b(?:here|at|work)\s*:\s*\.", ".", cleaned)
    cleaned = re.sub(r"\s+\.", ".", cleaned)

    # Split into sentences to check count and assemble
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]
    sentences = [s if s[-1] in ".!?" else f"{s}." for s in sentences]

    # Ensure stretch acknowledgment if required_yoe >= 2
    if required_yoe >= 2:
        has_stretch = any("stretch" in s.lower() for s in sentences)
        if not has_stretch:
            stretch_phrase = "I know the experience bar is a stretch for where I'm at right now, but I recently built an open-source PyPI library for diagnosing multi-agent LLM trace failures."
            if len(sentences) >= 2:
                sentences.insert(1, stretch_phrase)
            else:
                sentences.append(stretch_phrase)

    # Remove any duplicate mentions of portfolio
    sentences = [s for s in sentences if PORTFOLIO_URL not in s and "you can see my work here" not in s.lower()]

    if len(sentences) == 0:
        return generate_deterministic_referral_dm(
            ContactPerson(name=first_name, headline="", linkedin_url="", tier="2_TEAM_ENGINEER_OR_HM", relevance_note=""),
            JobPosting(job_id=job_id, company=company, role=role_title, location="", jd_text="", job_url="", source="", required_yoe=required_yoe),
            project_descs or [PARAM_PROJECT_MAP["agent_diagnostician"]["description"]],
            opener_type
        )

    # Assemble: head (1-2) + portfolio (1) + tail (1-2) -> 3-5 sentences total
    head_sentences = sentences[:2] if len(sentences) >= 2 else sentences[:1]
    tail_sentences = sentences[2:] if len(sentences) > 2 else []

    ask_advice_sentence = " ".join(tail_sentences).strip()
    if not ask_advice_sentence or "referral" not in ask_advice_sentence.lower():
        ask_advice_sentence = "Would really appreciate a referral if you think I'm a fit, and happy to share my resume and Job ID if helpful. Either way, would love any advice you have for someone entering this space."

    tail_split = [s.strip() for s in re.split(r"(?<=[.!?])\s+", ask_advice_sentence) if s.strip()]

    combined = head_sentences + [standalone_portfolio] + tail_split[:2]

    if len(combined) > 5:
        combined = combined[:5]

    result_paragraph = " ".join(combined).strip()
    result_paragraph = result_paragraph.replace("!", ".")
    result_paragraph = re.sub(r"\s*[—–]\s*|\s*--\s*", ", ", result_paragraph)
    result_paragraph = re.sub(r"\s+", " ", result_paragraph).strip()

    return result_paragraph


def build_direct_email_draft(
    contact: ContactPerson,
    job: JobPosting,
    referral_dm: str,
) -> str:
    """
    Generates a clean, professional Direct Email Draft for when the user
    contacts the person via their Hunter.io email address.
    """
    first_name = contact.name.split()[0] if contact.name else "there"
    job_id_str = f" (Job ID: {job.job_id})" if job.job_id else ""
    subject = f"Referral inquiry: {job.role}{job_id_str} - Param Patel (BITS Pilani)"

    body_core = re.sub(r"^(?:hi|hello|dear)\s+[^,]+,\s*", "", referral_dm, flags=re.IGNORECASE).strip()

    email_body = (
        f"Subject: {subject}\n\n"
        f"Hi {first_name},\n\n"
        f"{body_core}\n\n"
        f"I have attached my resume for reference. Thank you for your time and perspective.\n\n"
        f"Best regards,\n"
        f"Param Patel\n"
        f"BITS Pilani (2027) | {PORTFOLIO_URL}"
    )
    return email_body


def _build_fallback_note(
    job: JobPosting,
    company_intel: CompanyIntel,
    match_result: MatchAndTailorResult,
) -> str:
    """
    Generates a crisp direct-application cover note (~60 words) to paste
    into the ATS 'Additional Information' or 'Cover Letter' field when no contacts are found.
    """
    job_id_str = f" (Job ID: {job.job_id})" if job.job_id else ""
    yoe = job.required_yoe or 0
    stretch_str = " While I know the experience bar is a stretch for where I'm at as a 2027 graduate, I have focused heavily on practical systems." if yoe >= 2 else ""

    return (
        f"Hi {company_intel.company_name} hiring team,\n\n"
        f"I am Param Patel, a 2027 graduate from BITS Pilani applying for the {job.role} position{job_id_str}.{stretch_str} "
        f"I recently built an open-source PyPI library for diagnosing multi-agent LLM trace failures and a hybrid RAG system for multi-year SEC filings. "
        f"You can see my work here: {PORTFOLIO_URL}. "
        f"I would welcome the opportunity to discuss how my practical engineering projects contribute to your team."
    )


def _build_outreach_prompt(
    contact: ContactPerson,
    job: JobPosting,
    intel: CompanyIntel,
    match_result: MatchAndTailorResult,
    seniority: str,
    opener_type: str,
    project_descs: List[str],
) -> str:
    """Builds the structured LLM prompt enforcing the exact 6-step referral DM specification."""
    first_name = contact.name.split()[0] if contact.name else "there"
    job_id_str = f" (Job ID: {job.job_id})" if job.job_id else ""
    yoe = job.required_yoe or 0
    is_stretch = yoe >= 2

    opener_guidance = {
        "BITS_FULL_TIME": "Lead with shared BITSian campus connection: 'fellow BITSian here, applying for...'",
        "BITS_WILP": "Acknowledge shared BITS Pilani connection respectfully: 'saw the shared BITS Pilani connection and wanted to reach out as I'm applying for...'",
        "AI_ML_OVERLAP": f"Lead with genuine overlap with what THEIR profile says they build: 'saw you're working on {extract_ai_topic(contact.headline)} at {job.company} and wanted to reach out as I'm applying for...'",
        "MUTUAL": "Soft mention of mutual connections: 'noticed we share mutual connections and wanted to reach out as I'm applying for...'",
        "PLAIN_DIRECT": f"Open plainly without a fake hook: 'Hi {first_name}, I'm applying for the {job.role} role at {job.company}{job_id_str}.'",
    }.get(opener_type, f"Hi {first_name}, I'm applying for the {job.role} role at {job.company}.")

    stretch_instruction = (
        "- EXPERIENCE STRETCH MANDATE: The JD requires " + str(yoe) + "+ years of experience. Candidate is Param Patel, a 2027 graduate from BITS Pilani. YOU MUST EXPLICITLY ACKNOWLEDGE THIS ('I know the experience bar is a stretch for where I'm at right now') rather than ignoring it."
        if is_stretch else
        "- EXPERIENCE FIT: Candidate aligns with entry-level / fresher requirements."
    )

    proj_instructions = " and ".join(project_descs)

    return f"""You are drafting a post-connection LinkedIn referral DM for Param Patel, a 2027 graduate from BITS Pilani applying for {job.role} at {intel.company_name}.

CONTACT CONTEXT:
- Name: {contact.name} (First Name: {first_name})
- Headline: {contact.headline}
- Seniority Tier: {seniority}
- Contact Tier: {contact.tier}
- Discovered Signals: BITS={contact.bits_type}, Stated_AI={contact.stated_ai_ml_interest}, Exp_Level={contact.years_experience_level}, Mutual={contact.mutual_connections}
- Pre-computed Opener Type: {opener_type} ({opener_guidance})

JOB CONTEXT:
- Role: {job.role}
- Company: {intel.company_name}
- Job ID: {job.job_id}
- Job URL: {job.job_url}
- Required YoE: {yoe} years
{stretch_instruction}

PROJECT DESCRIPTIONS TO USE (NO PUFFERY OR ADJECTIVES):
{proj_instructions}

PORTFOLIO LINK (MUST BE STANDALONE SENTENCE):
You can see my work here: {PORTFOLIO_URL}.

STRICT 6-STEP DECISION SPECIFICATION:
1. STEP 1 (Opener): Open using the pre-computed opener type ({opener_type}). NEVER claim the company does something relevant unless the contact's own profile text says they personally work on it.
2. STEP 2 (Role & Stretch): State the exact role ({job.role}) at {intel.company_name}{job_id_str}. If required YoE >= 2, you MUST explicitly state 'I know the experience bar is a stretch for where I'm at right now'. Never manufacture fake alignment claims.
3. STEP 3 (Plain Work Description): State the project plainly in 1 sentence ({proj_instructions}).
4. STEP 4 (Portfolio Link): MUST be on its own standalone sentence: 'You can see my work here: {PORTFOLIO_URL}.'
5. STEP 5 (Low-Pressure Ask + Advice Close): Ask: 'Would really appreciate a referral if you think I'm a fit, and happy to share my resume and Job ID if helpful. Either way, would love any advice you have for someone entering this space.'
6. STEP 6 (Deterministic Rules):
   - Output MUST be a SINGLE PLAIN PARAGRAPH of 3 to 5 sentences.
   - NO em dashes (-- or —). Use commas or periods instead.
   - NO exclamation marks (!). Use periods (.) only.
   - NO 'Thanks for connecting' or 'Thank you for connecting' opener.
   - ZERO BANNED WORDS: Do NOT use 'aligns perfectly', 'directly addresses', 'cutting-edge', 'groundbreaking', 'passionate about', 'synergy', 'thrilled', 'excited to'.
   - Set connection_note_300_chars to: '{BLANK_CONNECTION_STRATEGY}'.

Return a structured OutreachPackage object."""


def generate_outreach_for_job(
    job: JobPosting,
    company_intel: CompanyIntel,
    match_result: MatchAndTailorResult,
    contacts: List[ContactPerson],
    use_llm: bool = True,
) -> Tuple[List[OutreachPackage], Optional[str]]:
    """
    Generates tailored outreach packages for each contact following the 6-step referral DM spec,
    or a fallback direct-apply note if no contacts were discovered.

    Returns:
        Tuple of (list_of_outreach_packages, fallback_direct_apply_note)
    """
    if not contacts:
        logger.info(f"[Drafter] No contacts found for '{job.company}'. Generating fallback direct-apply note.")
        fallback_note = _build_fallback_note(job, company_intel, match_result)
        return [], fallback_note

    outreach_packages: List[OutreachPackage] = []

    for contact in contacts:
        seniority = detect_seniority(contact.headline)
        opener_type = determine_opener_type(contact)
        project_descs = select_projects_for_contact(contact, match_result, job.jd_text)
        first_name = contact.name.split()[0] if contact.name else "there"

        # Pre-computed deterministic DM as baseline & fallback
        det_dm = generate_deterministic_referral_dm(contact, job, project_descs, opener_type)

        prompt = _build_outreach_prompt(
            contact=contact,
            job=job,
            intel=company_intel,
            match_result=match_result,
            seniority=seniority,
            opener_type=opener_type,
            project_descs=project_descs,
        )

        try:
            if not use_llm:
                raise RuntimeError("Deterministic mode requested")
            logger.info(
                f"[Drafter] Drafting referral DM for {contact.name} ({seniority} | {opener_type}) at {job.company}"
            )
            raw_pkg = invoke_structured_llm(OutreachPackage, prompt, tier="smart")

            clean_dm = sanitize_referral_dm(
                text=raw_pkg.full_dm_under_95_words,
                first_name=first_name,
                role_title=job.role,
                company=job.company,
                job_id=job.job_id,
                opener_type=opener_type,
                required_yoe=job.required_yoe or 0,
                project_descs=project_descs,
            )

            email_draft = raw_pkg.direct_email_draft or build_direct_email_draft(contact, job, clean_dm)

            pkg = OutreachPackage(
                contact_name=contact.name,
                contact_tier=contact.tier,
                linkedin_url=contact.linkedin_url,
                connection_note_300_chars=BLANK_CONNECTION_STRATEGY,
                full_dm_under_95_words=clean_dm,
                direct_email_draft=email_draft,
            )
            outreach_packages.append(pkg)
            logger.info(f"[Drafter Accepted] Verified 6-step referral DM drafted for {contact.name}")

        except Exception as e:
            logger.warning(f"[Drafter] LLM call failed for {contact.name}: {e}. Using deterministic 6-step DM.")
            clean_dm = det_dm
            email_draft = build_direct_email_draft(contact, job, clean_dm)

            pkg = OutreachPackage(
                contact_name=contact.name,
                contact_tier=contact.tier,
                linkedin_url=contact.linkedin_url,
                connection_note_300_chars=BLANK_CONNECTION_STRATEGY,
                full_dm_under_95_words=clean_dm,
                direct_email_draft=email_draft,
            )
            outreach_packages.append(pkg)

    return outreach_packages, None
