"""
Milestone 4: Referral Discovery Layer.

Discovers relevant contacts at target companies using OSINT search dorking.
Ranks contacts by tier:
  1_ALUMNI: BITS Pilani alumni at the target company
  2_TEAM_ENGINEER_OR_HM: Team peers, tech leads, or engineering managers
  3_RECRUITER: Technical recruiters or talent acquisition specialists
"""

import re
import logging
import threading
from typing import List, Dict, Any, Optional

from src.models import ContactPerson
from src.nodes.scrapers import search_dork_engine

logger = logging.getLogger("referral.people_finder")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# In-memory thread-safe contact cache
_CACHE_LOCK = threading.Lock()
_CONTACTS_CACHE: Dict[str, List[ContactPerson]] = {}

LINKEDIN_PROFILE_REGEX = re.compile(r"linkedin\.com/in/([a-zA-Z0-9_\-]+)", re.IGNORECASE)
DISALLOWED_URL_SEGMENTS = [
    "/company/", "/jobs/", "/school/", "/pulse/", "/posts/",
    "/learning/", "/feed/", "/dir/", "/groups/"
]


def parse_linkedin_search_result(item: Dict[str, str], tier: str, company: str = "") -> Optional[ContactPerson]:
    """
    Parses a single search result into a clean ContactPerson if it's a valid LinkedIn personal profile.
    Filters out ex-employees and extracts name, headline, normalized profile URL, tier, and personal journey note.
    """
    raw_url = (item.get("url") or "").strip()
    raw_title = (item.get("title") or "").strip()
    raw_content = (item.get("content") or "").strip()

    if not raw_url or not raw_title:
        return None

    # Filter out company pages, directory searches, job listings
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

    # Clean title by removing trailing " | LinkedIn" or " - LinkedIn"
    cleaned_title = re.sub(r"\s*[-–—|]\s*LinkedIn.*$", "", raw_title, flags=re.IGNORECASE).strip()

    # Reject aggregator title artifacts (e.g. "100+ 'Razorpay' profiles", "Top 20...")
    title_lower = cleaned_title.lower()
    if any(kw in title_lower for kw in ["profiles", "top 10", "top 20", "search results", "directory"]):
        return None

    # Split name and headline (delimiters: " - ", " – ", " — ", " | ")
    parts = re.split(r"\s+[-–—|]\s+", cleaned_title, maxsplit=1)
    if len(parts) >= 2:
        name = parts[0].strip()
        headline = parts[1].strip()
    else:
        name = cleaned_title
        headline = raw_content[:120].strip() if raw_content else f"Professional at {company}"

    # Name sanity check: name should not be too long or contain generic phrases
    if len(name.split()) > 6 or len(name) < 2 or "linkedin" in name.lower():
        return None

    # -------------------------------------------------------------
    # Ex-Employee / Former Staff Filter
    # -------------------------------------------------------------
    c_lower = company.lower().strip()
    c_slug = re.sub(r"[^a-zA-Z0-9]", "", c_lower)
    combined_check = f"{headline} {raw_content}".lower()

    ex_indicators = [
        f"ex-{c_lower}", f"ex - {c_lower}", f"ex {c_lower}",
        f"former {c_lower}", f"previously at {c_lower}", f"past: {c_lower}",
        f"ex-{c_slug}", f"former {c_slug}", f"previously {c_slug}"
    ]
    if any(ind in combined_check for ind in ex_indicators):
        # Profile mentions ex/former for this target company
        return None

    # If headline explicitly states they currently work at another company (e.g. "... at Microsoft | Ex-NetApp")
    if " at " in headline.lower() and c_lower not in headline.lower().split(" at ")[-1]:
        if "ex-" in headline.lower() or "former" in headline.lower():
            return None

    # -------------------------------------------------------------
    # Personal Journey & Context Extraction
    # -------------------------------------------------------------
    journey_details = []
    content_lower = raw_content.lower()
    headline_lower = headline.lower()

    if "pilani" in content_lower or "pilani" in headline_lower:
        journey_details.append("Pilani campus")
    elif "goa" in content_lower or "goa" in headline_lower:
        journey_details.append("Goa campus")
    elif "hyderabad" in content_lower or "hyderabad" in headline_lower:
        journey_details.append("Hyderabad campus")

    year_match = re.search(r"\b(201\d|202[0-6])\b", raw_content)
    if year_match:
        journey_details.append(f"batch of {year_match.group(1)}")

    for domain in ["agentic ai", "llm", "genai", "nlp", "computer vision", "distributed systems", "ml infrastructure", "platform", "search", "data science"]:
        if domain in content_lower or domain in headline_lower:
            journey_details.append(f"working in {domain}")
            break

    journey_context = ", ".join(journey_details) if journey_details else (headline[:80] if headline else f"Engineer at {company}")

    if tier == "1_ALUMNI":
        relevance_note = f"BITS Pilani alum at {company} ({journey_context})"
    elif tier == "2_TEAM_ENGINEER_OR_HM":
        relevance_note = f"Team engineer / hiring manager at {company} ({journey_context})"
    else:
        relevance_note = f"Technical recruiter / talent acquisition at {company} ({journey_context})"

    return ContactPerson(
        name=name,
        headline=headline,
        linkedin_url=clean_url,
        tier=tier,
        relevance_note=relevance_note,
    )


def find_hr_email_for_company(company: str, job_url: str = "", jd_text: str = "") -> str:
    """
    Finds or infers a verified or pattern-based HR/recruiter email for a company.
    1. Checks JD text for explicit career/recruiting email addresses.
    2. Runs an OSINT search query for company careers/talent emails.
    3. Infers company domain and returns careers@{domain} (pattern).
    """
    company_clean = company.strip()
    email_pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

    # 1. Check JD text
    if jd_text:
        matches = email_pattern.findall(jd_text)
        for email in matches:
            email_lower = email.lower()
            if any(kw in email_lower for kw in ["career", "job", "talent", "recruiting", "hiring", "hr", "people"]):
                return email
            c_slug = re.sub(r"[^a-zA-Z0-9]", "", company_clean.lower())
            if c_slug and c_slug in email_lower:
                return email

    # 2. OSINT Search Query
    try:
        q = f'"{company_clean}" ("careers@" OR "jobs@" OR "talent@" OR "hr@" OR "recruiting@") email'
        results = search_dork_engine(q, max_results=3)
        for item in results:
            content = f"{item.get('title', '')} {item.get('content', '')}"
            matches = email_pattern.findall(content)
            for email in matches:
                full_lower = email.lower()
                c_slug = re.sub(r"[^a-zA-Z0-9]", "", company_clean.lower())
                if any(kw in full_lower for kw in ["careers@", "jobs@", "talent@", "hr@", "recruiting@", "hiring@"]):
                    if c_slug in full_lower or not any(x in full_lower for x in ["gmail.com", "yahoo.com", "outlook.com", "duck.com"]):
                        return email
    except Exception as e:
        logger.warning(f"[People Finder] HR email search failed for {company_clean}: {e}")

    # 3. Infer clean company domain
    domain = None
    if job_url:
        from urllib.parse import urlparse
        parsed = urlparse(job_url)
        host = parsed.netloc.lower()
        if not any(b in host for b in ["greenhouse.io", "lever.co", "ashbyhq.com", "linkedin.com", "himalayas.app", "weworkremotely.com", "instahyre.com", "workatastartup.com"]):
            domain = host.replace("www.", "")

    if not domain:
        c_slug = re.sub(r"[^a-zA-Z0-9]", "", company_clean.lower())
        domain = f"{c_slug}.com"

    return f"careers@{domain} (pattern)"


def clear_contacts_cache() -> None:
    """Clears the in-memory contact cache (useful for testing)."""
    with _CACHE_LOCK:
        _CONTACTS_CACHE.clear()


def find_contacts_for_company(company: str, role: str) -> List[ContactPerson]:
    """
    Discovers up to 2 high-priority contacts for a company using OSINT search dorking.
    Queries in strict ranked order:
      1. Tier 1 (BITS Alumni)
      2. Tier 2 (Peer / Tech Lead / EM) - only if < 2 alumni found
      3. Tier 3 (Recruiter) - only if total found < 2

    Returns up to 2 unique ContactPerson objects ranked by tier priority.
    """
    company_clean = company.strip()
    company_key = company_clean.lower()

    # Check cache first
    with _CACHE_LOCK:
        if company_key in _CONTACTS_CACHE:
            logger.info(f"[People Finder] Cache hit for '{company_clean}': {len(_CONTACTS_CACHE[company_key])} contacts")
            return _CONTACTS_CACHE[company_key]

    discovered: List[ContactPerson] = []
    seen_urls = set()

    def add_contacts(results: List[Dict[str, str]], tier: str):
        for item in results:
            contact = parse_linkedin_search_result(item, tier, company=company_clean)
            if contact and contact.linkedin_url not in seen_urls:
                seen_urls.add(contact.linkedin_url)
                discovered.append(contact)

    # -------------------------------------------------------------
    # Query 1: Tier 1 - BITS Alumni at Company
    # -------------------------------------------------------------
    q1 = f'site:linkedin.com/in/ "{company_clean}" "BITS Pilani" ("AI" OR "Machine Learning" OR "Software" OR "Engineer")'
    logger.info(f"[People Finder] Running Tier 1 (BITS Alumni) dork for '{company_clean}'")
    try:
        r1 = search_dork_engine(q1, max_results=4)
        add_contacts(r1, "1_ALUMNI")
    except Exception as e:
        logger.warning(f"[People Finder] Tier 1 dork failed for '{company_clean}': {e}")

    # -------------------------------------------------------------
    # Query 2: Tier 2 - Team Peer / Tech Lead (run only if < 2 found)
    # -------------------------------------------------------------
    if len(discovered) < 2:
        q2 = f'site:linkedin.com/in/ "{company_clean}" ("AI Engineer" OR "Machine Learning" OR "Engineering Manager") ("India" OR "Bengaluru" OR "Hyderabad")'
        logger.info(f"[People Finder] Running Tier 2 (Team Peer/HM) dork for '{company_clean}'")
        try:
            r2 = search_dork_engine(q2, max_results=4)
            add_contacts(r2, "2_TEAM_ENGINEER_OR_HM")
        except Exception as e:
            logger.warning(f"[People Finder] Tier 2 dork failed for '{company_clean}': {e}")

    # -------------------------------------------------------------
    # Query 3: Tier 3 - Recruiter Fallback (run only if total < 2)
    # -------------------------------------------------------------
    if len(discovered) < 2:
        q3 = f'site:linkedin.com/in/ "{company_clean}" ("Technical Recruiter" OR "Talent Acquisition") ("India")'
        logger.info(f"[People Finder] Running Tier 3 (Recruiter) dork for '{company_clean}'")
        try:
            r3 = search_dork_engine(q3, max_results=4)
            add_contacts(r3, "3_RECRUITER")
        except Exception as e:
            logger.warning(f"[People Finder] Tier 3 dork failed for '{company_clean}': {e}")

    # Tier ranking priority mapping
    tier_priority = {
        "1_ALUMNI": 1,
        "2_TEAM_ENGINEER_OR_HM": 2,
        "3_RECRUITER": 3,
    }
    discovered.sort(key=lambda c: tier_priority.get(c.tier, 99))
    top_contacts = discovered[:2]

    # Save to cache
    with _CACHE_LOCK:
        _CONTACTS_CACHE[company_key] = top_contacts

    logger.info(
        f"[People Finder] Completed search for '{company_clean}': "
        f"found {len(top_contacts)} contacts: {[c.name + ' (' + c.tier + ')' for c in top_contacts]}"
    )
    return top_contacts

