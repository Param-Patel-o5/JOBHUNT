import re
import yaml
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Any, Set
from src.models import JobPosting
from src.db import is_job_seen

logger = logging.getLogger("ingestion.gatekeeper")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Load candidate context configuration
PROFILE_PATH = Path("config/profile_context.yaml")


def load_profile_context(config_path: Path = PROFILE_PATH) -> Dict[str, Any]:
    """Loads configuration and blacklist settings from yaml file."""
    if not config_path.exists():
        logger.warning(f"Profile config not found at {config_path}. Using fallback defaults.")
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# Baseline hardcoded scam/body-shop blacklist
DEFAULT_SCAM_BODY_SHOPS = {
    "turing", "crossover", "revature", "bairesdev",
    "unified mentor", "codsoft", "bharat intern",
    "fiverr", "upwork", "freelancer",
}

# RLHF / Data Annotation / Contract Gig Platforms
RLHF_PLATFORMS = {
    "outlier", "scale data", "mindrift", "alignerr",
    "dataannotation", "askable", "mercor", "soul ai",
    "remotasks", "telus international", "appen"
}

# Contract / RLHF / freelance gig trap patterns
CONTRACT_RLHF_PATTERNS = [
    r"\b(contract|contractor|freelance|part-time|part time|ai trainer|coding tasks|data annotation|prompt rater|rlhf|ai tutor)\b"
]
CONTRACT_RLHF_REGEX = re.compile("|".join(CONTRACT_RLHF_PATTERNS), re.IGNORECASE)

# Seniority & leadership role titles to reject deterministically
SENIOR_LEADERSHIP_PATTERNS = [
    r"\bsenior\b", r"\bsr\.?\b", r"\bstaff\b", r"\bprincipal\b",
    r"\blead\b", r"\bmanager\b", r"\bdirector\b", r"\bvp\b",
    r"\bhead of\b", r"\barchitect\b", r"\biii\b", r"\biv\b"
]
SENIOR_REGEX = re.compile("|".join(SENIOR_LEADERSHIP_PATTERNS), re.IGNORECASE)

# Technical role tokens required to pass
RELEVANT_ROLE_TOKENS = [
    r"\bai\b", r"\bml\b", r"\bmachine learning\b", r"\bdeep learning\b",
    r"\bdata scientist\b", r"\bdata science\b", r"\bapplied scientist\b",
    r"\bllm\b", r"\bgenai\b", r"\bnlp\b", r"\bvision\b", r"\bresearch\b",
    r"\bsoftware engineer\b", r"\bsoftware developer\b", r"\bsde\b",
    r"\bbackend\b", r"\bfull stack\b", r"\bdata engineer\b",
    r"\bpython\b", r"\bfounding engineer\b", r"\bmember of technical staff\b", r"\bmts\b"
]
RELEVANT_ROLE_REGEX = re.compile("|".join(RELEVANT_ROLE_TOKENS), re.IGNORECASE)

# Hard geo-locking patterns on remote boards
GEO_RESTRICTION_PATTERNS = [
    r"must reside in the us",
    r"us citizens only",
    r"authorized to work in the united states",
    r"eu timezones only",
    r"must be located in the us",
    r"us only",
    r"us based only",
    r"canada only",
]
GEO_RESTRICTION_REGEX = re.compile("|".join(GEO_RESTRICTION_PATTERNS), re.IGNORECASE)
REMOTE_SOURCES = {"wwr", "himalayas", "ycombinator", "wellfound", "otta"}


def extract_min_yoe(jd_text: str) -> int:
    """
    Extracts the minimum required years of experience from the JD text.
    Ignores 'preferred', 'nice to have', 'bonus', or company age statements.
    Returns the integer extracted, or 0 if no strict requirement >= 4 is detected.
    """
    if not jd_text:
        return 0

    # Pattern 1: e.g. "3+ years of experience", "5-7 yrs relevant exp", "4 years experience"
    p1 = r"\b([3-9]|[1-9]\d+)\+?\s*(?:-\s*\d+\s*)?(?:years?|yrs?)(?:\s+of)?\s+(?:relevant\s+|industry\s+|professional\s+)?(?:experience|exp)\b"
    # Pattern 2: e.g. "minimum 4 years", "at least 3 yrs", "requires 5 years"
    p2 = r"(?:minimum|at least|requires?|must have)\s+([3-9]|[1-9]\d+)\+?\s*(?:years?|yrs?)"

    matches: List[int] = []

    def is_preferred_or_non_requirement(start_pos: int) -> bool:
        """Checks if match is inside a 'preferred' or company-history context."""
        window_start = max(0, start_pos - 50)
        preceding = jd_text[window_start:start_pos].lower()
        non_req_tokens = ["preferred", "nice to have", "bonus", "plus", "ideal", "company", "business", "our team"]
        return any(tok in preceding for tok in non_req_tokens)

    for m in re.finditer(p1, jd_text, re.IGNORECASE):
        if is_preferred_or_non_requirement(m.start()):
            continue
        try:
            val = int(m.group(1))
            matches.append(val)
        except (ValueError, IndexError):
            pass

    for m in re.finditer(p2, jd_text, re.IGNORECASE):
        if is_preferred_or_non_requirement(m.start()):
            continue
        try:
            val = int(m.group(1))
            matches.append(val)
        except (ValueError, IndexError):
            pass

    return min(matches) if matches else 0


def filter_jobs(
    raw_jobs: List[JobPosting],
    profile_path: Path = PROFILE_PATH
) -> Tuple[List[JobPosting], Dict[str, int]]:
    """
    Production-grade deterministic zero-LLM-cost filtering gate.
    Evaluates:
      1. DB Deduplication (is_job_seen)
      2. Contract / RLHF / Annotation Gig Trap (regex + platform blacklist)
      3. Blacklisted companies (profile config + scam body-shops)
      4. Senior / leadership title rejection
      5. Irrelevant role title rejection
      6. YoE extraction (extracted_max_yoe > 2 rejected)
      7. Hard geo-restrictions on remote job boards

    Returns:
      surviving_jobs: List[JobPosting]
      stats: Dict[str, int] tracking counts for each drop reason
    """
    profile_data = load_profile_context(profile_path)
    cfg_blacklist = profile_data.get("hard_filters", {}).get("blacklisted_companies", [])
    all_blacklisted: Set[str] = {c.strip().lower() for c in cfg_blacklist} | DEFAULT_SCAM_BODY_SHOPS

    stats = {
        "total_incoming": len(raw_jobs),
        "dropped_seen": 0,
        "dropped_contract_or_rlhf": 0,
        "dropped_blacklisted": 0,
        "dropped_senior_title": 0,
        "dropped_irrelevant_role": 0,
        "dropped_high_yoe": 0,
        "dropped_geo_restricted": 0,
        "passed_gatekeeper": 0,
    }

    surviving: List[JobPosting] = []

    for job in raw_jobs:
        company_clean = job.company.strip().lower()
        role_clean = job.role.strip()

        # 1. Database Deduplication
        if is_job_seen(job.job_id, job.company, job.role):
            stats["dropped_seen"] += 1
            continue

        # 2. Contract / RLHF / Annotation Gig Trap
        if (CONTRACT_RLHF_REGEX.search(role_clean) 
            or CONTRACT_RLHF_REGEX.search(company_clean)
            or any(p in company_clean for p in RLHF_PLATFORMS)):
            stats["dropped_contract_or_rlhf"] += 1
            continue

        # 3. Blacklist Filter (Scam body-shops & configured blacklist)
        if any(b in company_clean for b in all_blacklisted):
            stats["dropped_blacklisted"] += 1
            continue

        # 4. Senior/Leadership Title Rejection
        if SENIOR_REGEX.search(role_clean):
            stats["dropped_senior_title"] += 1
            continue

        # 5. Irrelevant Role Title Rejection
        if not RELEVANT_ROLE_REGEX.search(role_clean):
            stats["dropped_irrelevant_role"] += 1
            continue

        # 6. Experience (YoE) Extraction & Gate (Allow up to 3 years for entry/early-career)
        extracted_yoe = extract_min_yoe(job.jd_text)
        job.extracted_max_yoe = extracted_yoe
        if extracted_yoe > 3:
            stats["dropped_high_yoe"] += 1
            continue

        # 7. Geo-Restriction Gate
        source_clean = job.source.strip().lower()
        if source_clean in REMOTE_SOURCES or "remote" in source_clean:
            if GEO_RESTRICTION_REGEX.search(job.jd_text):
                stats["dropped_geo_restricted"] += 1
                continue

        # Passed all deterministic gates
        surviving.append(job)

    stats["passed_gatekeeper"] = len(surviving)

    logger.info(
        f"[Gatekeeper] Processed {stats['total_incoming']} jobs -> {stats['passed_gatekeeper']} passed. "
        f"Drops: Seen={stats['dropped_seen']}, Contract/RLHF={stats['dropped_contract_or_rlhf']}, "
        f"Blacklist={stats['dropped_blacklisted']}, Senior={stats['dropped_senior_title']}, "
        f"Irrelevant={stats['dropped_irrelevant_role']}, HighYoE={stats['dropped_high_yoe']}, "
        f"GeoLock={stats['dropped_geo_restricted']}"
    )

    return surviving, stats
