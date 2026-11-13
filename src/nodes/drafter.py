"""
Milestone 4: Outreach Package Generation Layer.

Drafts hyper-tailored outreach packages for discovered contacts:
  - Strict <= 190 character LinkedIn connection note ("Add a note" free-tier limit buffer).
  - Seniority-aware tone adjustment (Leadership/Director vs. Peer/Junior).
  - Hyper-personalized references to contact headline and company domain.
  - Strict <= 85 word full direct message / InMail / email.
  - Fallback direct ATS apply note if no contacts are discovered.
"""

import re
import logging
from typing import List, Tuple, Optional

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

PORTFOLIO_URL = "https://parampatel-ai.vercel.app"


def detect_seniority(headline: str) -> str:
    """
    Detects seniority tier from contact headline.
    Returns 'Senior/Leadership' if management or leadership keywords are present, else 'Peer/Junior'.
    """
    if not headline:
        return "Peer/Junior"

    pattern = r"\b(?:manager|director|head|lead|leads|leading|principal|staff|vp|vice president|founder|co-founder|chief|cto|partner|architect)\b"
    if re.search(pattern, headline, re.IGNORECASE):
        return "Senior/Leadership"
    return "Peer/Junior"


def _build_fallback_note(
    job: JobPosting,
    company_intel: CompanyIntel,
    match_result: MatchAndTailorResult,
) -> str:
    """
    Generates a crisp direct-application cover note (~60 words) to paste
    into the ATS 'Additional Information' or 'Cover Letter' field.
    """
    return (
        f"Hi {company_intel.company_name} hiring team,\n\n"
        f"I am Param Patel, a 2027 graduate from BITS Pilani applying for the {job.role} position. "
        f"{match_result.winning_hook_sentence} "
        f"My technical projects, benchmarks, and research publications are available at {PORTFOLIO_URL}. "
        f"I would welcome the opportunity to discuss how my background directly aligns with your team's engineering goals."
    )


def _build_outreach_prompt(
    contact: ContactPerson,
    job: JobPosting,
    intel: CompanyIntel,
    match_result: MatchAndTailorResult,
    seniority: str,
) -> str:
    """Builds the structured LLM prompt tailored to contact seniority and domain context."""
    first_name = contact.name.split()[0] if contact.name else "there"
    is_bits = (contact.tier == "1_ALUMNI")

    alumni_guidance = (
        "- ALUMNI STATUS: Verified BITS Pilani alumnus. Mention the shared BITS Pilani connection naturally "
        "('fellow BITSian here (2027 batch)' or 'fellow BITSian building in AI')."
        if is_bits else
        "- ALUMNI STATUS: NOT from BITS Pilani (Tier: " + contact.tier + "). CRITICAL: DO NOT mention BITS, BITSian, "
        "or college connection under any circumstance! Mentioning BITS to a non-alumni is completely false. "
        "Frame connection strictly around their engineering work, team, or domain at " + intel.company_name + "."
    )

    example_senior = (
        f'"Hi {first_name}, fellow BITSian here. Following your leadership in {intel.company_name}\'s engineering—would value your perspective as an aspiring AI engineer!"'
        if is_bits else
        f'"Hi {first_name}, following your leadership in {intel.company_name}\'s engineering—would value your guidance as an aspiring AI engineer!"'
    )
    example_peer = (
        f'"Hi {first_name}, fellow BITSian here (2027 batch). Came across your work at {intel.company_name}—would love to connect and follow your team\'s updates!"'
        if is_bits else
        f'"Hi {first_name}, came across your work in tech at {intel.company_name}—would love to connect and follow what your team is building!"'
    )

    return f"""You are drafting a 2-stage human networking package for Param Patel, a 2027 graduate from BITS Pilani applying for {job.role} at {intel.company_name}.

CONTACT CONTEXT:
- Name: {contact.name} (First Name: {first_name})
- Headline: {contact.headline}
- Seniority Tier: {seniority}
- Contact Tier: {contact.tier}
- Relevance / Journey Note: {contact.relevance_note}
{alumni_guidance}

COMPANY & ROLE CONTEXT:
- Company: {intel.company_name}
- Company Summary: {intel.summary_2_lines}
- Role: {job.role}
- Job URL: {job.job_url}
- Winning Hook / Alignment Proof: {match_result.winning_hook_sentence}
- Candidate Portfolio: {PORTFOLIO_URL}

TONE GUIDELINES BY SENIORITY:
- If Senior/Leadership (Managers, Directors, Heads, Staff, Leads, VPs):
  Keep it highly respectful and concise. Acknowledge their leadership or tenure, and frame the connection around seeking brief industry perspective or advice from a veteran. (Do NOT treat them like a college peer).
- If Peer/Junior (Engineers, SDE-1/2, Analysts):
  Keep it collaborative, warm, and humble, highlighting shared engineering domains. Only mention BITS if Contact Tier is 1_ALUMNI.

HYPER-PERSONALIZATION RULE:
You MUST explicitly reference at least one specific technical team, domain, or detail mentioned in their headline or company context (e.g., if their headline mentions "Agentic AI", "Data Infrastructure", or "Computer Vision", you must mention that exact topic).

STRICT LENGTH ENFORCEMENT:

STAGE 1: connection_note_300_chars (LinkedIn free-tier "Add a note" modal):
- HARD LIMIT: MUST be STRICTLY UNDER 190 characters (including spaces and punctuation). LinkedIn has a strict 200-char limit for free accounts.
- ZERO REFERRAL ASK: Do NOT ask for a referral or interview here.
- FRAME: Advice, following their work, or connecting as an aspiring engineer.
- Example for Senior/Leadership: {example_senior} (<185 chars)
- Example for Peer/Junior: {example_peer} (<175 chars)

STAGE 2: full_dm_under_95_words (Sent AFTER they accept the connection):
- HARD LIMIT: MUST be STRICTLY UNDER 85 words.
- TONE: Warm, humble, polite, plain English (NO robotic jargon like "3-tier post-hoc forensic").
- STRUCTURE:
  1. Thank them for connecting, and state you are applying for {job.role} ({job.job_url}).
  2. Plain-English Proof: 1 natural sentence connecting your project ({match_result.winning_hook_sentence}) to what their team builds.
  3. Low-Friction Referral + Advice Close: "If you feel my profile is a fit, I'd be really grateful for a referral—happy to send my resume PDF and Job ID so it takes you zero hassle. Either way, I'd love any advice you have for a junior entering this space! My work: {PORTFOLIO_URL}"

Return a structured OutreachPackage object."""


def _sanitize_outreach_package(
    pkg: OutreachPackage,
    contact: ContactPerson,
    job: JobPosting,
    match_result: MatchAndTailorResult,
) -> OutreachPackage:
    """
    Enforces hard character (<= 190 chars) and word count (<= 85 words) limits.
    Implements smart truncation at the last complete sentence or word boundary.
    """
    pkg.contact_name = contact.name
    pkg.contact_tier = contact.tier
    pkg.linkedin_url = contact.linkedin_url

    # 1. Sanitize connection note (MUST be strictly <= 190 chars)
    note = pkg.connection_note_300_chars.strip()

    # Guard against hallucinated BITSian mentions for non-alumni contacts
    if contact.tier != "1_ALUMNI":
        note = re.sub(r"(?i)\bfellow\s+bitsian\s+here\s*(\([^\)]*\))?[,\.\-—\s]*", "", note)
        note = re.sub(r"(?i)\bbitsian\b", "engineer", note)
        note = re.sub(r"(?i)\bbits\s+pilani\b", "", note)
        if not note.startswith("Hi") and not note.startswith("Hello"):
            first_name = contact.name.split()[0] if contact.name else "there"
            note = f"Hi {first_name}, " + note.lstrip(",.- ")

    if len(note) > 190:
        sub = note[:190]
        # Look for last sentence boundary before 190
        last_punct = max(sub.rfind("."), sub.rfind("!"), sub.rfind("?"))
        if last_punct > 120:
            note = sub[:last_punct + 1].strip()
        else:
            # Cut at last word boundary before 187 chars + "..."
            sub_words = note[:187]
            last_space = sub_words.rfind(" ")
            if last_space > 100:
                note = sub_words[:last_space].rstrip(" ,.-") + "..."
            else:
                note = sub_words.rstrip(" ,.-") + "..."
    pkg.connection_note_300_chars = note

    # 2. Sanitize full DM (MUST be strictly <= 85 words)
    dm = pkg.full_dm_under_95_words.strip()
    words = dm.split()

    if PORTFOLIO_URL not in dm:
        dm += f" My work: {PORTFOLIO_URL}"
        words = dm.split()

    if len(words) > 85:
        dm = " ".join(words[:84]) + "."
        if PORTFOLIO_URL not in dm:
            words_adj = dm.split()[:83]
            dm = " ".join(words_adj) + f" {PORTFOLIO_URL}"

    pkg.full_dm_under_95_words = dm
    return pkg


def generate_outreach_for_job(
    job: JobPosting,
    company_intel: CompanyIntel,
    match_result: MatchAndTailorResult,
    contacts: List[ContactPerson],
) -> Tuple[List[OutreachPackage], Optional[str]]:
    """
    Generates tailored outreach packages for each contact, or a fallback direct-apply
    note if no contacts were discovered. Adjusts tone based on detected seniority.

    Args:
        job: The target JobPosting.
        company_intel: Viability and intel for the company.
        match_result: Match score, tailored project, and winning hook.
        contacts: List of discovered ContactPerson instances (up to 2).

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
        prompt = _build_outreach_prompt(contact, job, company_intel, match_result, seniority)
        first_name = contact.name.split()[0] if contact.name else "there"

        try:
            logger.info(f"[Drafter] Generating outreach for {contact.name} ({seniority} | {contact.tier}) at {job.company}")
            raw_pkg = invoke_structured_llm(OutreachPackage, prompt, tier="smart")
            sanitized_pkg = _sanitize_outreach_package(raw_pkg, contact, job, match_result)
            outreach_packages.append(sanitized_pkg)
        except Exception as e:
            logger.error(f"[Drafter] Failed to draft outreach for {contact.name}: {e}")
            # Robust seniority-aware fallback draft under 190 characters
            is_bits = (contact.tier == "1_ALUMNI")
            if is_bits:
                if seniority == "Senior/Leadership":
                    fallback_note = (
                        f"Hi {first_name}, fellow BITSian here. Following your leadership in engineering at "
                        f"{job.company}—would value your guidance as an aspiring AI engineer!"
                    )[:189]
                else:
                    fallback_note = (
                        f"Hi {first_name}, fellow BITSian here (2027 batch). Came across your work at "
                        f"{job.company}—would love to connect and follow your team's engineering updates!"
                    )[:189]
            else:
                if seniority == "Senior/Leadership":
                    fallback_note = (
                        f"Hi {first_name}, following your engineering leadership at "
                        f"{job.company}—would value your guidance as an aspiring AI engineer!"
                    )[:189]
                else:
                    fallback_note = (
                        f"Hi {first_name}, came across your work in tech at "
                        f"{job.company}—would love to connect and follow your team's engineering updates!"
                    )[:189]

            fallback_dm = (
                f"Hi {first_name}, thank you for connecting! I am applying for the {job.role} position at {job.company} ({job.job_url}). "
                f"{match_result.winning_hook_sentence} "
                f"If you feel my profile is a fit, I'd be really grateful for a referral—happy to send my resume PDF and Job ID so it takes zero hassle. "
                f"Either way, I'd love any advice for a junior entering this space! My work: {PORTFOLIO_URL}"
            )
            # Ensure DM is under 85 words
            dm_words = fallback_dm.split()
            if len(dm_words) > 85:
                fallback_dm = " ".join(dm_words[:84]) + f" {PORTFOLIO_URL}"

            outreach_packages.append(
                OutreachPackage(
                    contact_name=contact.name,
                    contact_tier=contact.tier,
                    linkedin_url=contact.linkedin_url,
                    connection_note_300_chars=fallback_note,
                    full_dm_under_95_words=fallback_dm,
                )
            )

    return outreach_packages, None
