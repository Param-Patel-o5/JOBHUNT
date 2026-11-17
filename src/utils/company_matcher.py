"""
Company Entity Verifier & LinkedIn Title Structural Parser.

Implements a 3-Stage Deterministic Entity Verification Pipeline:
  1. Canonical Name Normalization (stripping legal/regional suffixes at end, handling short/ambiguous brand tokens).
  2. LinkedIn Title Structural Parsing (Name & Headline separation, active employer extraction, past-tenure rejection).
  3. Structured Snippet Experience Fallback & Weak Mention Hard Rejection.
"""

import re
from typing import Tuple, List, Optional, Set

# Common English words or ambiguous short brand names (<= 5 letters or common dictionary words)
# that require exact full match or strict 'at / @' prefix to prevent substring collisions.
AMBIGUOUS_OR_SHORT_BRANDS: Set[str] = {
    "scale", "front", "deel", "make", "wave", "hive", "box", "seed", "blend",
    "ramp", "slab", "bench", "lattice", "gusto", "door", "nest", "beam", "bolt",
    "linear", "click", "notion", "glean", "post", "link", "loop", "bridge",
    "anchor", "peak", "core", "origin", "drift", "level", "flow", "stripe",
    "ohm", "work", "free", "data", "here", "open", "next", "one", "all",
}

# Legal and regional suffixes to strip ONLY at the end of the company name.
# Multi-word suffixes are ordered first to ensure greedy matching.
LEGAL_REGIONAL_SUFFIXES: List[str] = [
    "private limited",
    "pvt ltd",
    "pvt. ltd.",
    "pvt. ltd",
    "pvt ltd.",
    "pvt.",
    "pvt",
    "north america",
    "global tech",
    "software centre",
    "software center",
    "incorporated",
    "corporation",
    "technologies",
    "technology",
    "solutions",
    "software",
    "systems",
    "limited",
    "holdings",
    "ventures",
    "centre",
    "center",
    "global",
    "india",
    "group",
    "labs",
    "tech",
    "corp.",
    "corp",
    "ltd.",
    "ltd",
    "inc.",
    "inc",
    "llc.",
    "llc",
    "llp.",
    "llp",
    "co.",
    "co",
]

# Regex for past-tenure indicators (scanned within the 25 chars immediately preceding the company mention)
PAST_TENURE_REGEX = re.compile(
    r"(?:\bex[-–—\s]+|\bformer\b|\bformerly\b|\bprev\b|\bpreviously\b|\bprior\b|\bpast\b[:\s]*|\bincoming\b[:\s]*)",
    re.IGNORECASE
)

# Regex for non-employment / credentials (e.g. "Databricks Certified", "AWS Ambassador")
CERT_OR_NON_EMPLOYMENT_REGEX = re.compile(
    r"(?:\bcertified\b|\bcertification\b|\bcertifications\b|\btraining\b|\bambassador\b|\baspirant\b|\balum\b|\balumni\b)",
    re.IGNORECASE
)

# Regex for structured experience block in search snippets (e.g. "Experience: Perplexity", "Current: Cohere")
SNIPPET_EXPERIENCE_REGEX = re.compile(
    r"(?:\bexperience\b|\bcurrent\b|\bworking at\b)\s*[:·-]?\s*",
    re.IGNORECASE
)


def normalize_company_name(name: str) -> Tuple[str, List[str]]:
    """
    Normalizes a raw company name by lowercasing and stripping legal/regional suffixes
    ONLY at the end of the string.

    Returns:
        tuple[str, list[str]]:
          - full_cleaned_name (e.g. 'scale ai', 'netapp', 'databricks')
          - variations (list of normalized search aliases/variations)
    """
    if not name:
        return "", []

    # Clean punctuation and whitespace
    raw_lower = name.strip().lower()
    cleaned = re.sub(r"[\s,.\-_/]+", " ", raw_lower).strip()

    # Iteratively strip trailing legal / regional suffixes
    changed = True
    iterations = 0
    while changed and iterations < 10:
        changed = False
        iterations += 1
        for suffix in LEGAL_REGIONAL_SUFFIXES:
            # Pattern matches suffix at the exact end of string with word boundary
            pat = rf"(?:[\s,.\-_/]+|^)({re.escape(suffix)})$"
            match = re.search(pat, cleaned, re.IGNORECASE)
            if match:
                candidate = cleaned[: match.start()].strip(" ,.-_/")
                # Do not strip if it would leave the string empty
                if candidate:
                    cleaned = candidate
                    changed = True
                    break

    full_cleaned_name = cleaned.strip()

    # Build variations
    variations: List[str] = [full_cleaned_name]

    # If original name had words stripped but was valid, keep the intermediate without legal suffixes
    intermediate = re.sub(r"\b(?:private limited|pvt\.?\s*ltd\.?|inc\.?|llc\.?|corp\.?|ltd\.?)\b", "", raw_lower).strip(" ,.-_/")
    intermediate = re.sub(r"\s+", " ", intermediate).strip()
    if intermediate and intermediate not in variations:
        variations.append(intermediate)

    # Core brand token (first word or full string if single word)
    words = full_cleaned_name.split()
    if len(words) > 1:
        core_token = words[0]
        # Only add core token as standalone variation if it is NOT a common English word
        if core_token not in AMBIGUOUS_OR_SHORT_BRANDS and len(core_token) > 4:
            if core_token not in variations:
                variations.append(core_token)

    return full_cleaned_name, variations


def is_brand_ambiguous(name: str) -> bool:
    """
    Checks if a company name or its core token is ambiguous or very short (<= 4 chars),
    requiring an exact full match or strict 'at / @' prefix.
    """
    cleaned, _ = normalize_company_name(name)
    words = cleaned.split()
    core = words[0] if words else cleaned
    return core.lower() in AMBIGUOUS_OR_SHORT_BRANDS or len(core) <= 4 or len(cleaned) <= 4


def parse_linkedin_title(raw_title: str) -> Tuple[str, str]:
    """
    Parses a LinkedIn SERP title following the pattern:
      '[Name] - [Headline / Role at Company] | LinkedIn'

    Returns:
        tuple[str, str]: (name, headline_segment)
    """
    if not raw_title:
        return "", ""

    # 1. Strip trailing "| LinkedIn", "- LinkedIn", "— LinkedIn"
    cleaned = re.sub(r"\s*[-–—|]\s*LinkedIn.*$", "", raw_title, flags=re.IGNORECASE).strip()

    # 2. Split on the first dash separator: " - ", " – ", " — "
    parts = re.split(r"\s+[-–—]\s+", cleaned, maxsplit=1)
    if len(parts) >= 2:
        name = parts[0].strip()
        headline_segment = parts[1].strip()
    else:
        # Fallback if title format is "Name | Role..." or has no dash
        pipe_parts = re.split(r"\s+[|•]\s+", cleaned, maxsplit=1)
        if len(pipe_parts) >= 2:
            name = pipe_parts[0].strip()
            headline_segment = pipe_parts[1].strip()
        else:
            name = cleaned
            headline_segment = cleaned

    return name, headline_segment


def extract_cleaned_headline(linkedin_title: str, company_name: str = "", snippet: str = "") -> str:
    """Extracts the cleanest human-readable headline from a raw LinkedIn title and snippet."""
    _, headline = parse_linkedin_title(linkedin_title)
    norm_comp, _ = normalize_company_name(company_name) if company_name else ("", [])
    
    # If headline is missing or is literally just the company name itself
    if not headline or (company_name and headline.strip().lower() in (company_name.strip().lower(), norm_comp)):
        if snippet:
            role_match = re.search(
                r"\b((?:AI|ML|Machine Learning|Deep Learning|Software|Data|Platform|Research|Cloud|Full Stack|Backend|Systems)"
                r"\s+(?:Engineer|Scientist|Developer|Architect|Lead|Manager|Specialist|Associate))\b",
                snippet,
                re.IGNORECASE
            )
            if role_match:
                return f"{role_match.group(1)} at {company_name}" if company_name else role_match.group(1)
        return f"Engineering Team at {company_name}" if company_name else "Professional"

    return headline


def verify_contact_company(
    company_name: str,
    linkedin_title: str,
    linkedin_snippet: str = ""
) -> Tuple[bool, float, str]:
    """
    Strict 3-Stage Deterministic Entity Verification Pipeline:
      - Rule A (Past-Tenure Rejection): Scans preceding 25 chars for ex/former indicators -> Score 0.0.
      - Rule B (Primary Title Active Employer): Explicit active employer pattern in headline -> Score 1.0.
      - Rule C (Snippet Experience Header Fallback): Truncated title with 'Experience: Company' -> Score 0.85.
      - Rule D (Hard Reject): Random snippet prose mention only or non-employment -> Score 0.0.

    Returns:
        tuple[bool, float, str]: (is_valid, confidence_score, decision_reason)
    """
    if not company_name or not linkedin_title:
        return False, 0.0, "Rejected: Missing company name or title"

    full_cleaned_name, variations = normalize_company_name(company_name)
    if not full_cleaned_name:
        return False, 0.0, "Rejected: Could not normalize company name"

    name, headline_segment = parse_linkedin_title(linkedin_title)
    headline_lower = headline_segment.lower()
    snippet_lower = (linkedin_snippet or "").lower()

    requires_exact_full = is_brand_ambiguous(company_name)

    # Tokens to test for company presence
    # If ambiguous, ONLY test full_cleaned_name (e.g. 'scale ai'), unless company name is literally 1 word
    if requires_exact_full and len(full_cleaned_name.split()) > 1:
        target_tokens = [full_cleaned_name]
    else:
        target_tokens = [full_cleaned_name] + [v for v in variations if v != full_cleaned_name]

    # -------------------------------------------------------------------------
    # RULE A: Past-Tenure Rejection
    # Scan the 25 characters immediately preceding ANY match of company in title or snippet.
    # -------------------------------------------------------------------------
    def has_past_indicator_preceding(text: str, token: str) -> bool:
        """Checks if any occurrence of token in text is preceded by past indicators within the same clause or window."""
        pattern = rf"\b{re.escape(token)}\b"
        for m in re.finditer(pattern, text, re.IGNORECASE):
            start_idx = m.start()
            preceding_text = text[:start_idx]
            # Clause break boundaries so past indicator belonging to a prior clause doesn't contaminate
            clause_break = max(
                preceding_text.rfind("|"),
                preceding_text.rfind("•"),
                preceding_text.rfind("·"),
                preceding_text.rfind(";"),
                max(0, start_idx - 80)
            )
            preceding_window = text[clause_break:start_idx]
            if PAST_TENURE_REGEX.search(preceding_window):
                return True
        return False

    def is_solely_past_employee(text: str, token: str) -> bool:
        """Returns True if token exists in text AND all its occurrences are preceded by past indicators."""
        pattern = rf"\b{re.escape(token)}\b"
        occurrences = list(re.finditer(pattern, text, re.IGNORECASE))
        if not occurrences:
            return False
        for m in occurrences:
            start_idx = m.start()
            preceding_text = text[:start_idx]
            clause_break = max(
                preceding_text.rfind("|"),
                preceding_text.rfind("•"),
                preceding_text.rfind("·"),
                preceding_text.rfind(";"),
                max(0, start_idx - 80)
            )
            preceding_window = text[clause_break:start_idx]
            if not PAST_TENURE_REGEX.search(preceding_window):
                # Found at least one occurrence that is NOT preceded by past indicators
                return False
        return True

    # If the headline or snippet explicitly marks the company as a past employer
    for token in target_tokens:
        if has_past_indicator_preceding(headline_lower, token) or is_solely_past_employee(snippet_lower, token):
            # Check if there is an active employer clause that supersedes it in title
            # If headline has "Ex-<Company>", it's directly rejected
            if has_past_indicator_preceding(headline_lower, token):
                return False, 0.0, "Rejected: Past employee"

    # Also check snippet-level pure past employee
    for token in target_tokens:
        if is_solely_past_employee(snippet_lower, token) and not any(re.search(rf"\b{re.escape(t)}\b", headline_lower) for t in target_tokens):
            return False, 0.0, "Rejected: Past employee"

    # -------------------------------------------------------------------------
    # RULE B: Primary Title Active Employer Check (Score 1.0)
    # -------------------------------------------------------------------------
    # Analyze headline clauses: LinkedIn headlines often structure:
    # "Current Role at CurrentCompany | Ex-PastCompany | College"
    clauses = [c.strip() for c in re.split(r"\s*[|•·;]\s*", headline_segment) if c.strip()]
    if not clauses:
        clauses = [headline_segment.strip()]

    # First active clause evaluation:
    # Determine which clause represents the primary active role
    first_active_clause = clauses[0]
    first_clause_lower = first_active_clause.lower()

    for token in target_tokens:
        # Check for certification or non-employment (e.g. "Databricks Certified")
        cert_match = re.search(rf"\b{re.escape(token)}\s+(?:certified|certification|training|ambassador)\b", headline_lower)
        if cert_match:
            # Not an employee, just certified or trained
            return False, 0.0, "Rejected: Certification / non-employment reference"

        # Explicit active employment patterns:
        # "(at|@|-|•|–|—)\s*<token>"
        active_pattern = rf"(?:\b(?:at|working at|currently at)\b|@|[-–—•])\s*{re.escape(token)}\b"
        
        # 1. Match in first active clause
        if re.search(active_pattern, first_clause_lower):
            # Verify it's not immediately preceded by past indicator
            if not has_past_indicator_preceding(first_clause_lower, token):
                return True, 1.0, "Verified: Primary title active employer"

        # Check if the first clause explicitly names another employer (e.g. "at Acme", "@ Google", "at Infosys")
        other_at_matches = list(re.finditer(r"(?:\b(?:at|working at|currently at)\b|@)\s*([a-zA-Z0-9&]+)", first_clause_lower))
        clause_has_conflicting_employer = False
        for om in other_at_matches:
            matched_other = om.group(1).lower()
            if matched_other != token and matched_other not in target_tokens:
                clause_has_conflicting_employer = True
                break

        if clause_has_conflicting_employer:
            # Active employer in this clause is another company (e.g. "Front End Engineer at Acme Corp")
            continue

        # 2. If headline has format "Role, Company" or "Company - Role" or word-bounded token
        # If the token is ambiguous or short:
        #   - If multi-word (e.g. "scale ai"): match the full cleaned name
        #   - If single-word (e.g. "front", "scale", "deel"): MUST appear immediately after 'at' or '@' (already tested above)
        if not requires_exact_full:
            # Word-bounded match in the first active clause for non-ambiguous companies (e.g. "Databricks", "NetApp")
            if re.search(rf"\b{re.escape(token)}\b", first_clause_lower):
                if not has_past_indicator_preceding(first_clause_lower, token):
                    return True, 1.0, "Verified: Primary title active employer"
        else:
            # Ambiguous/short brand:
            # If multi-word (e.g. "Scale AI"), match the full cleaned name word-bounded
            if len(full_cleaned_name.split()) > 1:
                exact_full_pat = rf"\b{re.escape(full_cleaned_name)}\b"
                if re.search(exact_full_pat, first_clause_lower):
                    if not has_past_indicator_preceding(first_clause_lower, full_cleaned_name):
                        if not re.search(rf"\b{re.escape(full_cleaned_name)}\s+at\s+[a-zA-Z0-9]+", first_clause_lower):
                            return True, 1.0, "Verified: Primary title active employer"

    # Also check if another clause later in headline is active (e.g. "BITS Pilani | AI Engineer at Databricks")
    # Only if clause 0 was NOT an active employment clause at another company
    clause_0_has_other_employer = bool(re.search(r"(?:\bat\b|@)\s*[a-zA-Z0-9]+", first_clause_lower))
    if not clause_0_has_other_employer and len(clauses) > 1:
        for clause in clauses[1:]:
            clause_lower = clause.lower()
            # If this clause has past indicator (e.g. "Ex-Company"), skip it
            if PAST_TENURE_REGEX.search(clause_lower):
                continue
            for token in target_tokens:
                active_pattern = rf"(?:\b(?:at|working at|currently at)\b|@|[-–—•])\s*{re.escape(token)}\b"
                if re.search(active_pattern, clause_lower):
                    if not has_past_indicator_preceding(clause_lower, token):
                        return True, 1.0, "Verified: Primary title active employer"

    # -------------------------------------------------------------------------
    # RULE C: Snippet "Experience:" Header Fallback (Score 0.85)
    # LinkedIn snippets often format: "Experience: Company Name · Education: ..."
    # -------------------------------------------------------------------------
    if snippet_lower:
        for token in target_tokens:
            # Pattern: (experience|current|working at)[:·-]?\s*<token>\b
            snip_exp_pat = rf"(?:\bexperience\b|\bcurrent\b|\bworking at\b)\s*[:·-]?\s*(?:ex[-–—\s]+)?{re.escape(token)}\b"
            snip_match = re.search(snip_exp_pat, snippet_lower)
            if snip_match:
                matched_snippet_str = snip_match.group(0)
                # Check for past indicator in the matched experience segment or immediately preceding 25 chars
                start_pos = snip_match.start()
                preceding_25 = snippet_lower[max(0, start_pos - 25): start_pos]
                if PAST_TENURE_REGEX.search(preceding_25) or PAST_TENURE_REGEX.search(matched_snippet_str):
                    return False, 0.0, "Rejected: Past employee"

                return True, 0.85, "Verified: Snippet experience block"

    # -------------------------------------------------------------------------
    # RULE D: Hard Reject (Score 0.0)
    # If the company only appears randomly in prose without an active title match
    # or structured Experience: header match.
    # -------------------------------------------------------------------------
    # Check if company was mentioned in snippet or title at all
    found_anywhere = any(re.search(rf"\b{re.escape(t)}\b", f"{headline_lower} {snippet_lower}") for t in target_tokens)
    if found_anywhere:
        return False, 0.0, "Rejected: Weak snippet mention only"

    return False, 0.0, "Rejected: No active employer match"


# =========================================================================
# Structured Contact Signals Extractor
# =========================================================================

INTERN_ROLE_REGEX = re.compile(
    r"\b(?:intern|internship|summer\s+analyst|trainee|apprentice|co-?op)\b",
    re.IGNORECASE
)

BITS_CAMPUS_REGEX = re.compile(
    r"\b(?:bits\s+pilani|birla\s+institute\s+of\s+technology\s+(?:and|&)\s*science|bits\s+hyderabad|bits\s+goa|bphc|bits\s+wilp)\b",
    re.IGNORECASE
)

BITS_WILP_REGEX = re.compile(
    r"\b(?:wilp|work\s+integrated)\b",
    re.IGNORECASE
)

AI_ML_INTEREST_REGEX = re.compile(
    r"\b(?:ai|ml|machine\s+learning|llm|llms|agent|agents|agentic|rag|nlp|deep\s+learning|genai|gen\s*ai|generative\s+ai|data\s+science|data\s+scientist)\b",
    re.IGNORECASE
)

SENIOR_TITLE_REGEX = re.compile(
    r"\b(?:senior|sr\.?|staff|principal|lead|manager|director|head|vp|cto|founder|architect)\b",
    re.IGNORECASE
)

MID_TITLE_REGEX = re.compile(
    r"\b(?:sde\s*(?:ii|2|two)|engineer\s*(?:ii|2|3|iii)|ml\s+engineer|machine\s+learning\s+engineer|mts|member\s+of\s+technical\s+staff)\b",
    re.IGNORECASE
)

MUTUAL_CONNECTIONS_REGEX = re.compile(
    r"\bmutual\s+connections?\b",
    re.IGNORECASE
)


def verify_and_extract_contact_signals(
    target_company: str,
    linkedin_title: str,
    linkedin_snippet: str = ""
) -> dict:
    """
    Strict Active-Company & Non-Intern Verifier and Profile Signal Extractor.
    - Rule A: Target company MUST appear in active current role clause or snippet Experience block.
      Preceding 'Ex-', 'Former', 'Previously', or 'Incoming' results in hard reject.
    - Rule B: Hard reject interns and short-tenure trainees unless snippet explicitly shows >1 year tenure.
    - Rule C: Extracts structured signals for personalized outreach:
        * current_company
        * current_title
        * is_bits_alum (bool)
        * bits_type ("FULL_TIME" | "WILP" | "NONE")
        * stated_ai_ml_interest (bool - only if person's own words state it)
        * years_experience_level ("senior" | "mid" | "junior")
        * mutual_connections (bool)
    """
    default_signals = {
        "is_valid": False,
        "rejection_reason": None,
        "current_company": "",
        "current_title": "",
        "is_bits_alum": False,
        "bits_type": "NONE",
        "stated_ai_ml_interest": False,
        "years_experience_level": "junior",
        "mutual_connections": False,
    }

    if not target_company or not linkedin_title:
        default_signals["rejection_reason"] = "Rejected: Missing company name or title"
        return default_signals

    # 1. Rule A: Active Company Verification
    is_valid_comp, conf, reason = verify_contact_company(target_company, linkedin_title, linkedin_snippet)
    if not is_valid_comp:
        default_signals["rejection_reason"] = reason
        return default_signals

    # Extract current_title and current_company
    norm_target, _ = normalize_company_name(target_company)
    name, headline_segment = parse_linkedin_title(linkedin_title)
    cleaned_hl = extract_cleaned_headline(linkedin_title, target_company, linkedin_snippet)

    # Isolate role title from active clause
    current_title = cleaned_hl
    # Strip trailing company mentions like "at TargetCompany" or "@ TargetCompany"
    clean_title = re.sub(rf"\s*(?:at|@|[-–—])\s*.*$", "", current_title, flags=re.IGNORECASE).strip()
    if not clean_title or clean_title.lower() == target_company.lower() or clean_title.lower() == norm_target.lower():
        # Fallback to role from headline or snippet
        m_role = re.search(r"(?:^|[\-–—|•·])\s*([a-zA-Z0-9\s/]+?)\s+(?:at|@)\s+", linkedin_title, re.IGNORECASE)
        clean_title = m_role.group(1).strip() if m_role else f"Engineer at {target_company}"

    current_title = clean_title

    # 2. Rule B: Hard Reject Interns & Short-Tenure Trainees
    if INTERN_ROLE_REGEX.search(current_title):
        has_long_tenure = bool(re.search(r"\b(?:[2-9]|\d{2,})\s*(?:years?|yrs?)\b|\b1\s*(?:year|yr)\s+[1-9]\d*\s*mos?\b", linkedin_snippet, re.IGNORECASE))
        if not has_long_tenure:
            default_signals["is_valid"] = False
            default_signals["rejection_reason"] = "Rejected: Intern / Short-tenure trainee role"
            default_signals["current_company"] = target_company
            default_signals["current_title"] = current_title
            return default_signals

    # 3. Rule C: Extract Structured Profile Signals
    combined_text = f"{linkedin_title} {linkedin_snippet}"

    # BITS Alumni Signal
    is_bits = bool(BITS_CAMPUS_REGEX.search(combined_text))
    bits_type = "NONE"
    if is_bits:
        bits_type = "WILP" if BITS_WILP_REGEX.search(combined_text) else "FULL_TIME"

    # Stated AI/ML Interest (person's own words, excluding company name)
    text_without_company = re.sub(rf"\b{re.escape(norm_target)}\b", "", combined_text, flags=re.IGNORECASE)
    text_without_company = re.sub(rf"\b{re.escape(target_company)}\b", "", text_without_company, flags=re.IGNORECASE)
    stated_ai = bool(AI_ML_INTEREST_REGEX.search(text_without_company))

    # Seniority Level
    if SENIOR_TITLE_REGEX.search(current_title):
        exp_level = "senior"
    elif MID_TITLE_REGEX.search(current_title):
        exp_level = "mid"
    else:
        exp_level = "junior"

    # Mutual Connections
    has_mutual = bool(MUTUAL_CONNECTIONS_REGEX.search(linkedin_snippet))

    return {
        "is_valid": True,
        "rejection_reason": None,
        "current_company": target_company,
        "current_title": current_title,
        "is_bits_alum": is_bits,
        "bits_type": bits_type,
        "stated_ai_ml_interest": stated_ai,
        "years_experience_level": exp_level,
        "mutual_connections": has_mutual,
    }
