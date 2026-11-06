"""
Milestone 4: Outreach Package Generation Layer.

Drafts hyper-tailored outreach packages for discovered contacts:
  - Strict <= 280 character LinkedIn connection note ("Add a note").
  - Strict <= 95 word full direct message / InMail / email.
  - Fallback direct ATS apply note if no contacts are discovered.
"""

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
) -> str:
    """Builds the structured LLM prompt for the two-stage human networking workflow."""
    return f"""You are drafting a 2-stage human networking package for Param Patel, a 2027 graduate from BITS Pilani applying for {job.role} at {intel.company_name}.

CONTACT CONTEXT:
- Name: {contact.name}
- Headline: {contact.headline}
- Tier: {contact.tier}
- Relevance / Journey Note: {contact.relevance_note}
- LinkedIn: {contact.linkedin_url}

JOB & COMPANY CONTEXT:
- Company: {intel.company_name}
- Role: {job.role}
- Job URL: {job.job_url}
- Winning Hook / Alignment Proof: {match_result.winning_hook_sentence}
- Candidate Portfolio: {PORTFOLIO_URL}

TWO-STAGE HUMAN NETWORKING RULES:

STAGE 1: connection_note_300_chars (LinkedIn "Add a note" modal):
- HARD LIMIT: STRICTLY <= 260 characters (including spaces and punctuation).
- GOAL: Mentor & Advice connection frame.
- ZERO REFERRAL ASK: Do NOT ask for a referral, do NOT ask for a job, and do NOT cite heavy resume metrics here.
- PERSONALIZATION: Mention being a fellow BITSian (2027 batch) if tier is 1_ALUMNI (or general junior engineer if recruiter/peer). Reference their specific journey, domain, or team from their headline/relevance_note ({contact.relevance_note}).
- TONE: Warm, respectful, eager to learn.
- Example vibe: "Hi {contact.name.split()[0]}, fellow BITSian here (2027 batch). Came across your work while looking into {intel.company_name}'s AI initiatives. Would love to connect and learn a bit about your engineering journey to {intel.company_name}!"

STAGE 2: full_dm_under_95_words (Sent AFTER they accept your connection request):
- HARD LIMIT: STRICTLY <= 95 words.
- TONE: Warm, humble, polite, plain English (NO robotic jargon like "3-tier post-hoc forensic evaluation").
- STRUCTURE:
  1. Thank them for connecting, and state you are applying for the {job.role} role ({job.job_url}).
  2. Plain-English Proof: In 1 clear sentence, explain how your relevant project ({match_result.winning_hook_sentence}) aligns with what their team builds.
  3. Zero-Friction Referral + Advice Close: "If you feel my profile is a fit, I'd be really grateful for a referral—happy to send my resume PDF and Job ID so it takes you zero hassle. Either way, I'd love any advice you have for a junior entering this space! My work: {PORTFOLIO_URL}"

Return a structured OutreachPackage object."""


def _sanitize_outreach_package(
    pkg: OutreachPackage,
    contact: ContactPerson,
    job: JobPosting,
    match_result: MatchAndTailorResult,
) -> OutreachPackage:
    """Enforces hard character (<= 260 chars) and word count (<= 95 words) limits."""
    pkg.contact_name = contact.name
    pkg.contact_tier = contact.tier
    pkg.linkedin_url = contact.linkedin_url

    # 1. Sanitize connection note (<= 260 chars)
    note = pkg.connection_note_300_chars.strip()
    if len(note) > 260:
        truncated = note[:257]
        last_space = truncated.rfind(" ")
        if last_space > 180:
            note = truncated[:last_space] + "..."
        else:
            note = truncated + "..."
    pkg.connection_note_300_chars = note

    # 2. Sanitize full DM (<= 95 words)
    dm = pkg.full_dm_under_95_words.strip()
    words = dm.split()

    if PORTFOLIO_URL not in dm:
        dm += f" My work: {PORTFOLIO_URL}"
        words = dm.split()

    if len(words) > 95:
        dm = " ".join(words[:94]) + "."
        if PORTFOLIO_URL not in dm:
            words_adj = dm.split()[:93]
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
    note if no contacts were discovered.

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
        prompt = _build_outreach_prompt(contact, job, company_intel, match_result)
        try:
            logger.info(f"[Drafter] Generating outreach for {contact.name} ({contact.tier}) at {job.company}")
            raw_pkg = invoke_structured_llm(OutreachPackage, prompt, tier="smart")
            sanitized_pkg = _sanitize_outreach_package(raw_pkg, contact, job, match_result)
            outreach_packages.append(sanitized_pkg)
        except Exception as e:
            logger.error(f"[Drafter] Failed to draft outreach for {contact.name}: {e}")
            # Robust fallback draft if LLM call fails
            fallback_note = (
                f"Hi {contact.name}, I'm Param from BITS Pilani. {match_result.winning_hook_sentence}"
            )[:270]
            fallback_dm = (
                f"Hi {contact.name},\n\n"
                f"I am Param Patel, a 2027 graduate from BITS Pilani applying for the {job.role} role at {job.company} ({job.job_url}).\n\n"
                f"{match_result.winning_hook_sentence}\n\n"
                f"You can review my projects and benchmarks at {PORTFOLIO_URL}. "
                f"If you're open to referring, I'd be grateful—happy to share my resume directly."
            )
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

