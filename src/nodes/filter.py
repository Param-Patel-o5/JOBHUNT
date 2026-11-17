"""
Node 2: Deterministic Filtering Gate (filter.py).

Enforces strict zero-LLM-cost deterministic gates:
  1. DB Deduplication (is_job_seen)
  2. Contract / RLHF / Scam Body-Shop Blacklist
  3. Role Type & Title Segregation (Hard reject internships, senior roles, non-AI tracks; strict AI whitelist)
  4. Geographic & Remote Filter (Hard reject Remote US / Global; strictly allow India / Indian cities / Remote - India)
  5. Experience Cap & Required YoE Extraction (Extract required_yoe; hard reject 5+ YoE, allow 0 to 4 years)
"""

import re
import yaml
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Any, Set, Optional

from src.models import JobPosting
from src.db import is_job_seen

logger = logging.getLogger("ingestion.filter")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

PROFILE_PATH = Path("config/profile_context.yaml")


def load_profile_context(config_path: Path = PROFILE_PATH) -> Dict[str, Any]:
    """Loads configuration and blacklist settings from YAML file."""
    if not config_path.exists():
        logger.warning(f"Profile config not found at {config_path}. Using fallback defaults.")
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# Baseline hardcoded scam / body-shop blacklist
DEFAULT_SCAM_BODY_SHOPS: Set[str] = {
    "turing", "crossover", "revature", "bairesdev",
    "unified mentor", "codsoft", "bharat intern",
    "fiverr", "upwork", "freelancer",
}

# RLHF / Data Annotation / Contract Gig Platforms
RLHF_PLATFORMS: Set[str] = {
    "outlier", "scale data", "mindrift", "alignerr",
    "dataannotation", "askable", "mercor", "soul ai",
    "remotasks", "telus international", "appen"
}

# Contract / RLHF / freelance gig trap patterns
CONTRACT_RLHF_PATTERNS = [
    r"\b(contract|contractor|freelance|part-time|part time|ai trainer|coding tasks|data annotation|prompt rater|rlhf|ai tutor)\b"
]
CONTRACT_RLHF_REGEX = re.compile("|".join(CONTRACT_RLHF_PATTERNS), re.IGNORECASE)


# =========================================================================
# 1. Geographic & Remote Filter Regexes
# =========================================================================

FOREIGN_LOCATIONS = [
    r"\bunited\s+states\b", r"\busa\b", r"\bu\.s\.a?\b", r"\bus\b",
    r"\bsan\s+francisco\b", r"\bnew\s+york\b", r"\bseattle\b", r"\baustin\b",
    r"\beurope\b", r"\buk\b", r"\bunited\s+kingdom\b", r"\blondon\b",
    r"\bcanada\b", r"\btoronto\b", r"\bvancouver\b",
    r"\bgermany\b", r"\bberlin\b", r"\bfrance\b", r"\bparis\b",
    r"\baustralia\b", r"\bsydney\b", r"\bsingapore\b"
]
FOREIGN_LOCATIONS_REGEX = re.compile(r"\b(?:" + "|".join(FOREIGN_LOCATIONS) + r")\b", re.IGNORECASE)

# Permitted Indian cities and India tokens
INDIAN_CITIES = [
    r"india", r"bengaluru", r"bangalore", r"hyderabad",
    r"pune", r"mumbai", r"gurugram", r"gurgaon",
    r"noida", r"chennai", r"delhi", r"new\s+delhi",
    r"kolkata", r"ahmedabad", r"kochi", r"chandigarh",
    r"indore", r"jaipur"
]
INDIAN_CITIES_REGEX = re.compile(r"\b(?:" + "|".join(INDIAN_CITIES) + r")\b", re.IGNORECASE)

# Explicit Remote India patterns
REMOTE_INDIA_PATTERNS = [
    r"remote\s*[-–—:]\s*india",
    r"india\s*[-–—:]\s*remote",
    r"remote\s*,?\s*india",
    r"india\s*,?\s*remote",
    r"remote\s*\(\s*india\s*\)",
    r"anywhere\s+in\s+india",
    r"remote\s+(?:in|within|across)\s+india",
    r"india[,\s]+remote",
]
REMOTE_INDIA_REGEX = re.compile("|".join(REMOTE_INDIA_PATTERNS), re.IGNORECASE)

REMOTE_KEYWORD_REGEX = re.compile(r"\b(remote|anywhere|worldwide|work\s+from\s+home|wfh)\b", re.IGNORECASE)

GEO_RESTRICTION_PATTERNS = [
    r"must reside in the us",
    r"us citizens only",
    r"authorized to work in the united states",
    r"eu timezones only",
    r"must be located in the us",
    r"us only",
    r"us based only",
    r"canada only",
    r"must be authorized to work in the u\.s\.",
    r"eligible to work in the us",
    r"sponsorship is not available for this role in the us",
    r"must be in north america",
]
GEO_RESTRICTION_REGEX = re.compile("|".join(GEO_RESTRICTION_PATTERNS), re.IGNORECASE)


def is_valid_location(location: str, description: str) -> Tuple[bool, str]:
    """
    Geographic & Remote Filter:
    - Hard Reject Remote US / Global: Immediately reject any listing where location contains
      "United States", "US", "USA", "San Francisco", "New York", "Seattle", "Austin",
      "Europe", "UK", "London", "Canada", or "Remote" (unless the location or text
      explicitly states "Remote - India", "India Remote", or an Indian city).
    - Permitted Locations: Must explicitly match India or Indian cities ("India", "Bengaluru",
      "Bangalore", "Hyderabad", "Pune", "Mumbai", "Gurugram", "Gurgaon", "Noida", "Chennai", "Delhi").

    Returns:
        (is_valid, reason)
    """
    loc_clean = (location or "").strip()
    desc_clean = (description or "").strip()

    # 1. Hard check description for foreign residency / US citizen restrictions
    if GEO_RESTRICTION_REGEX.search(desc_clean):
        return False, "[FILTER REJECT] Description specifies US/EU work authorization or residence restriction"

    has_remote_india = bool(
        REMOTE_INDIA_REGEX.search(loc_clean) or REMOTE_INDIA_REGEX.search(desc_clean)
    )
    has_indian_city_in_loc = bool(INDIAN_CITIES_REGEX.search(loc_clean))
    has_indian_city_in_desc = bool(INDIAN_CITIES_REGEX.search(desc_clean))

    has_foreign_in_loc = bool(FOREIGN_LOCATIONS_REGEX.search(loc_clean))
    has_remote_in_loc = bool(REMOTE_KEYWORD_REGEX.search(loc_clean))

    # 2. Check foreign location presence
    if has_foreign_in_loc:
        # If foreign keyword is in location string, only allow if location explicitly has India / Indian city or Remote - India
        if not (has_remote_india or has_indian_city_in_loc):
            return False, f"[FILTER REJECT] Foreign location: '{loc_clean}'"

    # 3. Check generic Remote presence
    if has_remote_in_loc:
        if not (has_remote_india or has_indian_city_in_loc or has_indian_city_in_desc):
            return False, f"[FILTER REJECT] Remote role without explicit India presence: '{loc_clean}'"

    # 4. Permitted Locations check: Must explicitly match India or an Indian city
    if not (has_indian_city_in_loc or (has_remote_in_loc and (has_remote_india or has_indian_city_in_desc))):
        return False, f"[FILTER REJECT] Location '{loc_clean}' is not in permitted India locations"

    return True, "Location verified (India / Permitted City)"


# =========================================================================
# 2. Experience Cap & Required Years Extraction
# =========================================================================

YOE_REQUIREMENT_PATTERNS = [
    # "3+ years of experience", "2-4 years of experience", "5+ yrs relevant exp"
    r"(?i)\b([0-9]|1[0-9])\+?\s*(?:-\s*(?:[0-9]|1[0-9])\s*)?(?:years?|yrs?)\s+(?:of\s+)?(?:relevant\s+|industry\s+|professional\s+|hands-on\s+)?experience\b",
    # "minimum 3 years", "at least 4 years", "requires 5 years"
    r"(?i)(?:minimum|at\s+least|requires?|must\s+have)\s+([0-9]|1[0-9])\+?\s*(?:-\s*(?:[0-9]|1[0-9])\s*)?(?:years?|yrs?)\b",
    # "3+ years in machine learning / Python / AI"
    r"(?i)\b([0-9]|1[0-9])\+?\s*(?:-\s*(?:[0-9]|1[0-9])\s*)?(?:years?|yrs?)\s+(?:of\s+)?(?:experience\s+)?(?:in|with|building|developing|working\s+with)\b",
]


def extract_required_yoe(description: str) -> int:
    """
    Extracts the minimum required years of experience (required_yoe) from the JD text.
    Ignores non-requirement contexts ('preferred', 'nice to have', 'bonus', company history).
    Returns an integer representing the required YoE, or 0 if unstated / fresh grad.
    """
    if not description:
        return 0

    desc = description

    def is_non_requirement_context(start_pos: int, end_pos: int) -> bool:
        # Preceding window: check up to the current sentence start (e.g. "Preferred: 5+ years")
        window_start = max(0, start_pos - 60)
        preceding = desc[window_start:start_pos]
        last_period = max(preceding.rfind("."), preceding.rfind("\n"), preceding.rfind(";"))
        if last_period != -1:
            preceding = preceding[last_period + 1:]
        preceding = preceding.lower()

        # Succeeding window: check within the same sentence (e.g. "5+ years preferred", "5+ years is a plus")
        window_end = min(len(desc), end_pos + 45)
        succeeding = desc[end_pos:window_end]
        next_period = min(
            [pos for pos in (succeeding.find("."), succeeding.find("\n"), succeeding.find(";")) if pos != -1] or [len(succeeding)]
        )
        succeeding = succeeding[:next_period].lower()

        non_req_tokens = [
            "preferred", "nice to have", "bonus", "plus", "ideal", "good to have",
            "advantageous", "desired", "company", "business", "our team", "firm has",
            "over the last", "past", "history of"
        ]
        return any(tok in preceding for tok in non_req_tokens) or any(tok in succeeding for tok in non_req_tokens)

    mandatory_years: List[int] = []

    for pattern in YOE_REQUIREMENT_PATTERNS:
        for m in re.finditer(pattern, desc):
            if is_non_requirement_context(m.start(), m.end()):
                continue
            try:
                yoe_val = int(m.group(1))
                if yoe_val <= 15:
                    mandatory_years.append(yoe_val)
            except (ValueError, IndexError):
                pass

    if not mandatory_years:
        return 0

    max_demanded = max(mandatory_years)
    min_demanded = min(mandatory_years)

    # If any mandatory requirement demands 5+ years, return that number so it triggers hard rejection
    if max_demanded >= 5:
        return max_demanded

    return min_demanded


# Backward compatibility alias
extract_min_yoe = extract_required_yoe


# =========================================================================
# 3. Role Type & Title Segregation Regexes
# =========================================================================

# Hard Reject Internships & Trainee positions (candidate graduating June 2027 wants full-time)
INTERNSHIP_TOKENS = [
    r"\bintern\b",
    r"\binternship\b",
    r"\btrainee\b",
    r"\bapprentice\b",
    r"\bapprenticeship\b",
    r"\bco-?op\b",
    r"\bstudent\b",
]
INTERNSHIP_REGEX = re.compile("|".join(INTERNSHIP_TOKENS), re.IGNORECASE)

# Seniority & Leadership roles (hard rejected)
SENIOR_LEADERSHIP_TOKENS = [
    r"\bsenior\b", r"\bsr\.?\b", r"\bstaff\b", r"\bprincipal\b",
    r"\blead\b", r"\bmanager\b", r"\bdirector\b", r"\bvp\b",
    r"\bhead\s+of\b", r"\barchitect\b", r"\biii\b", r"\biv\b"
]
SENIOR_LEADERSHIP_REGEX = re.compile("|".join(SENIOR_LEADERSHIP_TOKENS), re.IGNORECASE)

# Hard Reject Non-AI Tracks
NON_AI_TRACK_TOKENS = [
    r"\bdevops\b",
    r"\bsre\b",
    r"\bsite\s+reliability\b",
    r"\bdata\s+engineer(?:ing)?\b",
    r"\bdata\s+analyst\b",
    r"\bbusiness\s+analyst\b",
    r"\bfrontend\b",
    r"\bfront-end\b",
    r"\bui[/-]?ux\b",
    r"\bios\b",
    r"\bandroid\b",
    r"\bqa\b",
    r"\bsdet\b",
    r"\btest\s+engineer(?:ing)?\b",
    r"\bquality\s+assurance\b",
    r"\bsecurity\s+engineer(?:ing)?\b",
    r"\bnetwork\s+engineer(?:ing)?\b",
    r"\bsales\s+engineer\b",
    r"\bproduct\s+manager\b",
    r"\btechnical\s+writer\b",
]
NON_AI_TRACK_REGEX = re.compile("|".join(NON_AI_TRACK_TOKENS), re.IGNORECASE)

# Strict Whitelist: Title MUST contain at least one of these core tokens
AI_CORE_TOKENS = [
    r"\bai\b",
    r"\bml\b",
    r"\bmachine\s+learning\b",
    r"\bartificial\s+intelligence\b",
    r"\bllm\b",
    r"\bllms\b",
    r"\bgenai\b",
    r"\bgen\s*ai\b",
    r"\bgenerative\s+ai\b",
    r"\bdata\s+scientist\b",
    r"\bdata\s+science\b",
    r"\bdeep\s+learning\b",
    r"\bnlp\b",
    r"\bcomputer\s+vision\b",
    r"\bvision\b",
    r"\bagent\b",
    r"\bagents\b",
    r"\bagentic\b",
    r"\brag\b",
]
AI_CORE_REGEX = re.compile("|".join(AI_CORE_TOKENS), re.IGNORECASE)


def is_valid_role_title(title: str) -> Tuple[bool, str]:
    """
    Role Type & Title Segregation:
    - Hard Reject Internships: Reject any title containing "Intern", "Internship", "Trainee", "Apprentice", "Co-op".
    - Hard Reject Senior / Leadership: Reject Senior, Staff, Principal, Lead, Manager, Director, VP.
    - Hard Reject Non-AI Tracks: Reject DevOps, SRE, Site Reliability, Data Engineer, Data Analyst,
      Business Analyst, Frontend, UI/UX, iOS, Android, QA, SDET, Test Engineer, Security Engineer, Network.
    - Strict Whitelist: Title MUST contain at least one of:
      "AI", "ML", "Machine Learning", "Artificial Intelligence", "LLM", "GenAI", "Generative AI",
      "Data Scientist", "Data Science", "Deep Learning", "NLP", "Computer Vision", "Agent", "Agentic", "RAG".
    """
    if not title or not title.strip():
        return False, "[FILTER REJECT] Empty title"

    t = title.strip()

    # 1. Hard Reject Internships
    if INTERNSHIP_REGEX.search(t):
        return False, f"[FILTER REJECT] Internship / Trainee role: '{t}'"

    # 2. Hard Reject Senior / Leadership
    if SENIOR_LEADERSHIP_REGEX.search(t):
        return False, f"[FILTER REJECT] Senior / Leadership role: '{t}'"

    # 3. Hard Reject Non-AI Tracks
    if NON_AI_TRACK_REGEX.search(t):
        return False, f"[FILTER REJECT] Non-AI track role: '{t}'"

    # 4. Strict Whitelist: Must contain at least one core AI/ML/Data token
    # (This also automatically rejects pure "Backend Engineer" or "Software Engineer" without an AI term)
    if not AI_CORE_REGEX.search(t):
        return False, f"[FILTER REJECT] Title lacks required AI/ML core token: '{t}'"

    return True, "Role title verified"


# =========================================================================
# 4. Master Deterministic Filtering Gate
# =========================================================================

def filter_jobs(
    raw_jobs: List[JobPosting],
    profile_path: Path = PROFILE_PATH
) -> Tuple[List[JobPosting], Dict[str, int]]:
    """
    Deterministic zero-LLM-cost filtering pipeline.
    Applies:
      1. DB Deduplication (is_job_seen)
      2. Contract / RLHF / Scam Body-Shop Blacklist
      3. Role Type & Title Segregation (Internship, Senior, Non-AI tracks, Strict AI whitelist)
      4. Geographic & Remote Filter (Remote US / Global rejected; India / Indian cities / Remote - India permitted)
      5. Experience Cap & Required YoE Extraction (Hard reject 5+ YoE, allow 0 to 4 years)

    Returns:
      surviving_jobs: List[JobPosting]
      stats: Dict[str, int]
    """
    profile_data = load_profile_context(profile_path)
    cfg_blacklist = profile_data.get("hard_filters", {}).get("blacklisted_companies", [])
    all_blacklisted: Set[str] = {c.strip().lower() for c in cfg_blacklist} | DEFAULT_SCAM_BODY_SHOPS

    stats = {
        "total_incoming": len(raw_jobs),
        "dropped_seen": 0,
        "dropped_contract_or_rlhf": 0,
        "dropped_blacklisted": 0,
        "dropped_invalid_title": 0,
        "dropped_invalid_location": 0,
        "dropped_high_yoe": 0,
        "passed_filter": 0,
    }

    surviving: List[JobPosting] = []

    for job in raw_jobs:
        company_clean = job.company.strip().lower()
        role_clean = job.role.strip()

        # 1. Database Deduplication
        if is_job_seen(job.job_id, job.company, job.role):
            stats["dropped_seen"] += 1
            logger.debug(f"[Filter Drop] Already seen: {job.company} - {job.role}")
            continue

        # 2. Contract / RLHF / Gig Trap & Platform Blacklist
        if (CONTRACT_RLHF_REGEX.search(role_clean)
            or CONTRACT_RLHF_REGEX.search(company_clean)
            or any(p in company_clean for p in RLHF_PLATFORMS)):
            stats["dropped_contract_or_rlhf"] += 1
            logger.debug(f"[Filter Drop] Contract/RLHF trap: {job.company} - {job.role}")
            continue

        # 3. Company Blacklist (Scam body-shops & configured blacklist)
        if any(b in company_clean for b in all_blacklisted):
            stats["dropped_blacklisted"] += 1
            logger.debug(f"[Filter Drop] Blacklisted company: {job.company}")
            continue

        # 4. Role Type & Title Segregation
        title_ok, title_reason = is_valid_role_title(role_clean)
        if not title_ok:
            stats["dropped_invalid_title"] += 1
            logger.info(f"[Filter Drop] {title_reason} ({job.company})")
            continue

        # 5. Geographic & Remote Filter
        loc_ok, loc_reason = is_valid_location(job.location, job.jd_text)
        if not loc_ok:
            stats["dropped_invalid_location"] += 1
            logger.info(f"[Filter Drop] {loc_reason} ({job.company} - {job.role})")
            continue

        # 6. Experience Cap & Required Years Extraction
        required_yoe = extract_required_yoe(job.jd_text)
        job.required_yoe = required_yoe
        job.extracted_max_yoe = required_yoe  # maintain compatibility

        # Hard reject 5+ YoE. Allow 0 to 4 years of experience.
        if required_yoe >= 5:
            stats["dropped_high_yoe"] += 1
            logger.info(f"[Filter Drop] [FILTER REJECT] Requires 5+ years experience ({required_yoe} yrs): {job.company} - {job.role}")
            continue

        # All deterministic gates passed
        surviving.append(job)

    stats["passed_filter"] = len(surviving)

    logger.info(
        f"[Filter Node] Processed {stats['total_incoming']} jobs -> {stats['passed_filter']} passed. "
        f"Drops: Seen={stats['dropped_seen']}, RLHF/Contract={stats['dropped_contract_or_rlhf']}, "
        f"Blacklist={stats['dropped_blacklisted']}, TitleSegregation={stats['dropped_invalid_title']}, "
        f"GeoLock={stats['dropped_invalid_location']}, HighYoE={stats['dropped_high_yoe']}"
    )

    return surviving, stats
