"""
Node 3 & 4: Contact Discovery, Entity Verification & Human Email Discovery (enrich.py).

Architecture:
  - Discovers 3 to 5 verified LinkedIn contacts per target company (max 4 per job).
  - Uses verify_and_extract_contact_signals (Rule A active company check, Rule B non-intern check,
    Rule C profile signals extraction).
  - Ranks contacts: Full-time BITS Pilani alumni first -> BITS WILP -> AI/ML Engineers/Leads -> Recruiters.
  - Integrates Hunter.io API & deterministic permutations for direct employee email discovery.
  - Prioritizes direct human email over generic careers@/info@ black holes.
"""

import os
import re
import logging
import threading
from typing import List, Dict, Any, Optional

from src.models import ContactPerson
from src.nodes.scrape import search_dork_engine
from src.utils.company_matcher import (
    normalize_company_name,
    verify_and_extract_contact_signals,
    parse_linkedin_title,
    extract_cleaned_headline,
)
from src.utils.email_hunter import find_direct_email, clean_domain_from_company

logger = logging.getLogger("referral.enrich")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

_CACHE_LOCK = threading.Lock()
_CONTACTS_CACHE: Dict[str, List[ContactPerson]] = {}

LINKEDIN_PROFILE_REGEX = re.compile(r"linkedin\.com/in/([a-zA-Z0-9_\-]+)", re.IGNORECASE)
DISALLOWED_URL_SEGMENTS = [
    "/company/", "/jobs/", "/school/", "/pulse/", "/posts/",
    "/learning/", "/feed/", "/dir/", "/groups/"
]


def parse_linkedin_search_result(item: Dict[str, str], tier: str, company: str = "") -> Optional[ContactPerson]:
    """
    Parses and verifies a LinkedIn search result:
    - Filters directory, company, or search aggregator pages.
    - Runs verify_and_extract_contact_signals to enforce:
        * Rule A: Active employment at target company (no Ex-, Former, Previously, Incoming).
        * Rule B: Hard reject interns and short-tenure trainees.
        * Rule C: Extraction of BITS status, AI/ML interest, seniority, and mutual connections.
    - Discovers direct human email address via Hunter.io / deterministic permutations.
    """
    raw_url = (item.get("url") or "").strip()
    raw_title = (item.get("title") or "").strip()
    raw_content = (item.get("content") or "").strip()

    if not raw_url or not raw_title:
        return None

    url_lower = raw_url.lower()
    if any(segment in url_lower for segment in DISALLOWED_URL_SEGMENTS):
        return None

    match = LINKEDIN_PROFILE_REGEX.search(raw_url)
    if not match:
        return None

    slug = match.group(1).strip()
    if not slug or slug.lower() in ("search", "feed", "jobs", "in"):
        return None

    clean_url = f"https://www.linkedin.com/in/{slug}"
    cleaned_title = re.sub(r"\s*[-–—|]\s*LinkedIn.*$", "", raw_title, flags=re.IGNORECASE).strip()

    title_lower = cleaned_title.lower()
    if any(kw in title_lower for kw in ["profiles", "top 10", "top 20", "search results", "directory"]):
        return None

    name, headline = parse_linkedin_title(cleaned_title)
    if not name:
        name = cleaned_title

    # Sanity checks on name
    name_lower = name.lower().strip()
    if len(name.split()) > 6 or len(name) < 2 or "linkedin" in name_lower:
        return None

    corporate_tokens = (
        "bank", "ltd", "pvt", "inc", "llc", "corp", "technologies",
        "solutions", "careers", "jobs", "hiring", "official", "wilp", "pilani"
    )
    if any(re.search(rf"\b{tok}\b", name_lower) for tok in corporate_tokens):
        logger.debug(f"[Enrich] Rejected corporate name '{name}'")
        return None

    if company:
        canonical_comp, _ = normalize_company_name(company)
        if canonical_comp and (canonical_comp in name_lower or name_lower in company.lower()):
            logger.debug(f"[Enrich] Rejected company-named profile '{name}' for '{company}'")
            return None

    # Verify Active Company & Extract Structured Signals
    signals = verify_and_extract_contact_signals(
        target_company=company,
        linkedin_title=raw_title,
        linkedin_snippet=raw_content
    )

    if not signals.get("is_valid"):
        logger.info(f"[Enrich Rejected] {name} ({headline}): {signals.get('rejection_reason')} for '{company}'")
        return None

    # Derive clean title and headline
    current_title = signals.get("current_title") or headline
    is_bits = signals.get("is_bits_alum", False)
    bits_type = signals.get("bits_type", "NONE")
    stated_ai = signals.get("stated_ai_ml_interest", False)
    exp_level = signals.get("years_experience_level", "junior")
    has_mutual = signals.get("mutual_connections", False)

    # Classify tier
    if is_bits:
        assigned_tier = "1_ALUMNI"
    elif tier == "3_RECRUITER" or "recruiter" in current_title.lower() or "talent" in current_title.lower():
        assigned_tier = "3_RECRUITER"
    else:
        assigned_tier = "2_TEAM_ENGINEER_OR_HM"

    # Contextual relevance note
    if is_bits:
        campus_label = "Full-time BITS Pilani alum" if bits_type == "FULL_TIME" else "BITS WILP alum"
        relevance_note = f"{campus_label} at {company} ({current_title})"
    elif stated_ai:
        relevance_note = f"AI/ML Engineer / Lead at {company} ({current_title})"
    elif assigned_tier == "2_TEAM_ENGINEER_OR_HM":
        relevance_note = f"Team engineer at {company} ({current_title})"
    else:
        relevance_note = f"Technical recruiter at {company} ({current_title})"

    # Direct Human Email Discovery (Hunter.io + Deterministic Permutations)
    first_name = name.split()[0] if name else ""
    last_name = name.split()[-1] if len(name.split()) > 1 else ""
    domain = clean_domain_from_company(company)
    email_data = find_direct_email(first_name, last_name, domain)

    contact = ContactPerson(
        name=name,
        headline=headline,
        linkedin_url=clean_url,
        tier=assigned_tier,
        relevance_note=relevance_note,
        email=email_data.get("email", ""),
        email_status=email_data.get("status", ""),
        current_company=company,
        current_title=current_title,
        is_bits_alum=is_bits,
        bits_type=bits_type,
        stated_ai_ml_interest=stated_ai,
        years_experience_level=exp_level,
        mutual_connections=has_mutual,
    )

    logger.info(
        f"[Enrich Accepted] {name} ({assigned_tier} | {exp_level}) at {company} | "
        f"Email: {contact.email} ({contact.email_status}) | BITS={bits_type}"
    )
    return contact


def find_hr_email_for_company(
    company: str,
    job_url: str = "",
    jd_text: str = "",
    contacts: Optional[List[ContactPerson]] = None
) -> str:
    """
    Finds direct recruiter/referral email for the company.
    Priority order:
      1. Direct human email of top discovered contact (never generic if a contact exists).
      2. Explicit recruiting/talent email from JD text.
      3. Inferred domain pattern (recruiting@{domain}).
    """
    if contacts and len(contacts) > 0 and contacts[0].email:
        return contacts[0].email

    if jd_text:
        email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", jd_text)
        if email_match:
            candidate_email = email_match.group(0).lower()
            if not any(bad in candidate_email for bad in ["example.com", "sentry.io", "w3.org"]):
                return candidate_email

    domain = clean_domain_from_company(company, job_url)
    return f"recruiting@{domain}"


def clear_contacts_cache() -> None:
    """Clears the in-memory contact cache (useful for testing)."""
    with _CACHE_LOCK:
        _CONTACTS_CACHE.clear()


def find_contacts_for_company(company: str, role: str = "", max_contacts: int = 4) -> List[ContactPerson]:
    """
    Discovers up to `max_contacts` (default 4, up to 5) verified contacts per target company.
    Queries in strict ranked priority order:
      1. Tier 1 (BITS Pilani Alumni at company)
      2. Tier 2 (AI/ML Engineers, Tech Leads, Engineering Managers)
      3. Tier 3 (Technical Recruiters & Talent Acquisition)

    Sorts contacts with prioritized ranking:
      - Full-time BITS Pilani alumni first
      - BITS WILP alumni next
      - AI/ML engineers with stated interest
      - Team engineers / managers
      - Recruiters
    """
    company_clean = company.strip()
    company_key = company_clean.lower()
    canonical_name, _ = normalize_company_name(company_clean)
    search_company = canonical_name.title() if canonical_name.islower() else (canonical_name or company_clean)
    company_phrases = f'("at {search_company}" OR "@ {search_company}" OR "@{search_company}" OR "{search_company}")'

    with _CACHE_LOCK:
        if company_key in _CONTACTS_CACHE and len(_CONTACTS_CACHE[company_key]) >= 2:
            logger.info(f"[Enrich] Cache hit for '{company_clean}': {len(_CONTACTS_CACHE[company_key])} contacts")
            return _CONTACTS_CACHE[company_key][:max_contacts]

    discovered: List[ContactPerson] = []
    seen_urls = set()

    def add_contacts(results: List[Dict[str, str]], tier: str):
        for item in results:
            contact = parse_linkedin_search_result(item, tier, company=company_clean)
            if contact and contact.linkedin_url not in seen_urls:
                seen_urls.add(contact.linkedin_url)
                discovered.append(contact)

    # Query 1: Tier 1 - BITS Alumni at Company
    q1 = (
        f'site:linkedin.com/in/ {company_phrases} '
        f'("BITS Pilani" OR "BITS, Pilani" OR "Birla Institute of Technology and Science" OR "BPHC" OR "BITS Hyderabad" OR "BITS Goa") '
        f'-"certificate program" -"executive certificate" '
        f'("B.E" OR "M.Tech" OR "M.E" OR "M.Sc" OR "Engineer" OR "AI" OR "Machine Learning")'
    )
    logger.info(f"[Enrich] Querying Tier 1 (BITS Alumni) for '{search_company}'...")
    try:
        r1 = search_dork_engine(q1, max_results=6)
        add_contacts(r1, "1_ALUMNI")
    except Exception as e:
        logger.warning(f"[Enrich] Tier 1 query failed for '{company_clean}': {e}")

    # Query 2: Tier 2 - AI/ML Engineers & Tech Leads (run if needed to reach max_contacts)
    if len(discovered) < max_contacts:
        q2 = (
            f'site:linkedin.com/in/ {company_phrases} '
            f'("AI Engineer" OR "Machine Learning" OR "LLM" OR "Tech Lead" OR "Engineering Manager" OR "Software Engineer") '
            f'("India" OR "Bengaluru" OR "Hyderabad" OR "Pune") -Intern -Internship'
        )
        logger.info(f"[Enrich] Querying Tier 2 (Team Peers/HM) for '{search_company}'...")
        try:
            r2 = search_dork_engine(q2, max_results=6)
            add_contacts(r2, "2_TEAM_ENGINEER_OR_HM")
        except Exception as e:
            logger.warning(f"[Enrich] Tier 2 query failed for '{company_clean}': {e}")

    # Query 3: Tier 3 - Technical Recruiters (run if still below max_contacts)
    if len(discovered) < max_contacts:
        q3 = (
            f'site:linkedin.com/in/ {company_phrases} '
            f'("Technical Recruiter" OR "Talent Acquisition" OR "Lead Recruiter") ("India")'
        )
        logger.info(f"[Enrich] Querying Tier 3 (Recruiters) for '{search_company}'...")
        try:
            r3 = search_dork_engine(q3, max_results=4)
            add_contacts(r3, "3_RECRUITER")
        except Exception as e:
            logger.warning(f"[Enrich] Tier 3 query failed for '{company_clean}': {e}")

    # Priority sorting:
    # 1. Full-time BITS alumni
    # 2. BITS WILP alumni
    # 3. AI/ML Engineers with stated interest
    # 4. Other Team Engineers
    # 5. Recruiters
    def rank_key(c: ContactPerson) -> int:
        if c.is_bits_alum and c.bits_type == "FULL_TIME":
            return 1
        if c.is_bits_alum and c.bits_type == "WILP":
            return 2
        if c.tier == "2_TEAM_ENGINEER_OR_HM" and c.stated_ai_ml_interest:
            return 3
        if c.tier == "2_TEAM_ENGINEER_OR_HM":
            return 4
        if c.tier == "3_RECRUITER":
            return 5
        return 99

    discovered.sort(key=rank_key)
    top_contacts = discovered[:max_contacts]

    with _CACHE_LOCK:
        _CONTACTS_CACHE[company_key] = top_contacts

    logger.info(
        f"[Enrich] Completed discovery for '{company_clean}': "
        f"selected {len(top_contacts)} verified contacts: "
        f"{[f'{c.name} ({c.tier}|BITS={c.bits_type}|{c.years_experience_level})' for c in top_contacts]}"
    )
    return top_contacts
