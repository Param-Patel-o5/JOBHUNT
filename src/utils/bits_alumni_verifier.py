"""
BITS Pilani Alumni Verification Utility.

Distinguishes genuine BITS Pilani campus degree holders from people who:
  - Did a BITS Pilani online/WILP certification (Executive Ed, CSIS, WILP)
  - Mention BITS Pilani only as a certification body in their headline
  - Are just BITS Pilani certified (e.g., "Databricks Certified... | BITS Pilani")

BITS Pilani has 3 real campuses. Genuine alumni will have one of these in their
Education section, which typically surfaces in the LinkedIn SERP snippet or headline:
  - Pilani (the main campus), Goa, Hyderabad (BPHC)

The continuing-education / certification arms that do NOT confer campus degrees:
  - BITS Pilani WILP (Work Integrated Learning Programme)
  - BITS Pilani CSIS (Centre for Software & IT)
  - Executive Certificate / Certificate Programme
  - Any mention of "online" / "distance" alongside BITS Pilani
"""

import re
from typing import Tuple

# ---------------------------------------------------------------------------
# Campus degree signals — these appear in the Education section snippet
# for genuine B.E. / M.E. / M.Tech / M.Sc / MBA / Ph.D. campus graduates.
# ---------------------------------------------------------------------------

# Real BITS degree abbreviations
BITS_DEGREE_PATTERNS = re.compile(
    r"""
    (?:
        # Degree mentioned with BITS or Pilani (education block)
        \b(?:b\.?e\.?|b\.?tech\.?|m\.?e\.?|m\.?tech\.?|m\.?sc\.?|mba|ph\.?d\.?|integrated)\b
        .{0,60}?
        \b(?:bits|pilani|b-p-h-c|bphc)\b
    |
        # BITS Pilani with campus-specific city suffix (strong signal)
        \b(?:bits\s+pilani|bitspilani)\b
        .{0,30}?
        \b(?:pilani\s+campus|goa\s+campus|hyderabad\s+campus|k\s*k\s*birla|dubai\b)\b
    |
        # "Education: BITS Pilani" or "BITS Pilani · 20XX" (snippet Education block)
        \beducation\s*[:·\-]?\s*(?:bits\s+pilani|birla\s+institute)
    |
        # "BITS Pilani, Class of XXXX" or "Batch of XXXX at BITS"
        \b(?:bits\s+pilani|bitspilani)\b.{0,25}\b(?:class\s+of|batch\s+of|19\d\d|20[01]\d|202[0-9])\b
    |
        # Headline format: "M.Tech (AI/ML) @ BITS Pilani" — still a campus student
        \bm\.?\s*tech\b.{0,30}\b(?:bits|pilani)\b
    |
        # BITS Pilani campus city alone can confirm (cities unique enough)
        \bbits\s+pilani\b.{0,10}(?:,\s*)?(?:pilani|goa|hyderabad|rajasthan)\b
    |
        \bbirla\s+institute\s+of\s+technology\b
    )
    """,
    re.IGNORECASE | re.VERBOSE
)

# ---------------------------------------------------------------------------
# Certification / non-degree NEGATIVE signals — if present, it is NOT a campus alum.
# Order matters: check these FIRST to short-circuit.
# ---------------------------------------------------------------------------

# BITS Pilani's continuing education / certification programmes
BITS_CERT_PATTERNS = re.compile(
    r"""
    (?:
        # Explicit non-degree programme names
        \bbits?\s+pilani\s+wilp\b                               # WILP programme
    |   \bwork\s+integrated\s+learning\b                        # WILP description
    |   \bbits?\s+pilani\s+(?:executive|certificate|certified|certification|csis)\b
    |   \bexecutive\s+(?:certificate|education|program|programme)\b.{0,40}\bbits\b
    |   \bcertificate\s+(?:program|programme|course)\b.{0,40}\bbits\b
    |   \bbits\b.{0,40}\bcertificate\s+(?:program|programme|course)\b
    |   # Vendor CERTIFIED + BITS Pilani — must have the word "certified" or "certification" close to vendor
        # e.g. "AWS Certified", "Databricks Certified GenAI", "Google Cloud Certified"
        \b(?:aws|azure|gcp|databricks|microsoft|coursera|udemy|nptel|nvidia|
             google\s+cloud|google\s+certified|google\s+professional)\b
        .{0,80}
        \bbits\s+pilani\b
    |   # "certified" or "certification" keyword → within 120 chars → BITS Pilani
        \bcertif(?:ied|ication|ications)\b.{0,120}\bbits\s+pilani\b
    )
    """,
    re.IGNORECASE | re.VERBOSE
)

# Strong exclusion: "distance" or "online" adjacent to BITS
BITS_DISTANCE_PATTERN = re.compile(
    r"\b(?:distance|online|correspondence|remote)\b.{0,40}\bbits\b"
    r"|\bbits\b.{0,40}\b(?:distance|online|correspondence|remote)\b",
    re.IGNORECASE
)

# "BITS Pilani" mentioned ONLY in context of a certification, not a degree
# e.g. "PMP | BITS Pilani Certified" or "NPTEL | BITS Pilani"
BITS_ONLY_CERT_CONTEXT = re.compile(
    r"\b(?:pmp|cfa|cpa|csm|scrum|nptel|coursera|edx|udacity)\b"
    r".{0,100}\bbits\s*pilani\b"
    r"|\bbits\s*pilani\b.{0,100}\b(?:pmp|cfa|cpa|csm|scrum|nptel|coursera|edx|udacity)\b",
    re.IGNORECASE
)


def verify_bits_alumni(
    linkedin_title: str,
    linkedin_snippet: str = ""
) -> Tuple[bool, str]:
    """
    Verifies whether a LinkedIn profile belongs to a genuine BITS Pilani campus
    degree holder (B.E. / M.Tech / Ph.D. from one of the 3 campuses), as opposed
    to someone who did a BITS WILP / certificate programme / just mentioned BITS
    Pilani as a certification body.

    Args:
        linkedin_title: The raw LinkedIn SERP title string.
        linkedin_snippet: The raw LinkedIn SERP snippet/content string.

    Returns:
        (is_genuine_alum: bool, reason: str)
    """
    combined = f"{linkedin_title} {linkedin_snippet}".lower()
    combined_raw = f"{linkedin_title} {linkedin_snippet}"  # for case-sensitive patterns

    # Normalize all BITS campus aliases so downstream patterns unify around "BITS Pilani".
    # "BITS Goa", "BITS Hyderabad", "BPHC", "Birla Institute of Technology and Science"
    # are all genuine campus references. We handle them via an early-exit positive check.
    _campus_alias_re = re.compile(
        r"\b(?:bits\s+goa|bits\s+hyderabad|bphc|bits\s+dubai|"
        r"birla\s+institute\s+of\s+technology(?:\s+and\s+science|\s*&\s*science)?)\b",
        re.IGNORECASE
    )
    has_campus_alias = bool(_campus_alias_re.search(combined_raw))

    # ------------------------------------------------------------------
    # FAST PATH for other BITS campuses (Goa, Hyderabad/BPHC):
    # If a campus alias is present AND no cert keywords appear near it, accept immediately.
    # We do NOT inject into combined_raw (which would cause cert false positives).
    # ------------------------------------------------------------------
    if has_campus_alias:
        # Check no cert disqualifier around the campus alias itself
        for alias_match in _campus_alias_re.finditer(combined_raw):
            start = alias_match.start()
            window = combined_raw[max(0, start - 60): start + len(alias_match.group(0)) + 60]
            if not re.search(r"\b(?:certif|wilp|certificate|executive|online|distance)\b", window, re.IGNORECASE):
                return True, f"Verified: Genuine BITS campus alias '{alias_match.group(0)}' found (no cert context)"

    # ------------------------------------------------------------------
    # STEP 1: Hard reject on certification / non-degree programme signals
    # (Run on the original combined_raw — NOT alias-expanded to avoid false positives)
    # ------------------------------------------------------------------
    if BITS_CERT_PATTERNS.search(combined_raw):
        return False, "Rejected: BITS Pilani certification/WILP reference (not a campus degree)"

    if BITS_DISTANCE_PATTERN.search(combined):
        return False, "Rejected: BITS Pilani distance/online reference"

    if BITS_ONLY_CERT_CONTEXT.search(combined):
        return False, "Rejected: BITS Pilani mentioned only in certification context"

    # ------------------------------------------------------------------
    # STEP 2: Positive match on campus degree signals
    # ------------------------------------------------------------------
    if BITS_DEGREE_PATTERNS.search(combined_raw):
        return True, "Verified: BITS Pilani campus degree signal found"

    # ------------------------------------------------------------------
    # STEP 3: Fallback heuristic — BITS Pilani in Education snippet block
    # LinkedIn SERP snippets often contain structured blocks:
    # "Experience: Company · Education: BITS Pilani · ..."
    # This is the Education section — a strong campus degree signal.
    # ------------------------------------------------------------------
    edu_block_pat = re.compile(
        r"education\s*[:·\-]?\s*(?:bits\s+pilani|birla\s+institute|b\.?i\.?t\.?s\.?)",
        re.IGNORECASE
    )
    if edu_block_pat.search(combined_raw):
        return True, "Verified: BITS Pilani in Education section of snippet"

    # ------------------------------------------------------------------
    # STEP 4: Headline contains "[Campus] | BITS Pilani" or "BITS Pilani | [Degree]"
    # Headline alumni pattern: people often write "M.Tech AI/ML @ BITS Pilani"
    # or "BITS Pilani | CERN | IMSc" (research track people)
    # ------------------------------------------------------------------
    headline_degree_pat = re.compile(
        r"(?:b\.?e|m\.?tech|m\.?sc|ph\.?d|dual\s+degree|integrated)"
        r".{0,60}bits\s*pilani"
        r"|bits\s*pilani.{0,60}(?:b\.?e|m\.?tech|m\.?sc|ph\.?d|dual\s+degree|integrated)",
        re.IGNORECASE
    )
    if headline_degree_pat.search(combined_raw):
        return True, "Verified: Degree + BITS Pilani co-occurrence in headline"

    # ------------------------------------------------------------------
    # STEP 5: If BITS Pilani appears in snippet with graduation year — good signal
    # e.g. "BITS Pilani 2023" or "2024 BITS Pilani"
    # ------------------------------------------------------------------
    year_bits_pat = re.compile(
        r"bits\s*pilani.{0,20}(?:20[12]\d|19\d\d)"
        r"|(?:20[12]\d|19\d\d).{0,20}bits\s*pilani",
        re.IGNORECASE
    )
    if year_bits_pat.search(combined_raw):
        return True, "Verified: BITS Pilani + graduation year co-occurrence"

    # ------------------------------------------------------------------
    # STEP 6: "BITS Pilani" in headline with no other context — ambiguous.
    # e.g. "AI Engineer | BITS Pilani" in headline alone (no snippet degree context)
    # This is risky: could be a certification. Apply a soft accept ONLY if the
    # snippet explicitly contains "BITS Pilani" without cert keywords nearby.
    # ------------------------------------------------------------------
    bits_in_headline = bool(re.search(r"bits\s*pilani", linkedin_title, re.IGNORECASE))
    bits_in_snippet = bool(re.search(r"bits\s*pilani", linkedin_snippet, re.IGNORECASE))

    if bits_in_headline and bits_in_snippet:
        # Both title and snippet mention BITS — higher confidence campus grad
        return True, "Verified: BITS Pilani present in both headline and Education snippet"

    if bits_in_headline and not bits_in_snippet:
        # Only in headline — could be cert, could be alum listing it. Soft accept.
        # e.g. "M.Tech AI/ML – BITS Pilani" in headline → almost always a student/alum
        # But "BITS Pilani Certified" would have been caught in Step 1 already.
        return True, "Verified: BITS Pilani in headline (non-cert context)"

    if bits_in_snippet and not bits_in_headline:
        # Only in snippet but not headline — could be a past mention. Cautious reject.
        return False, "Rejected: BITS Pilani only in snippet prose, not headline (ambiguous)"

    # No BITS signal at all — this profile shouldn't have been in Tier 1 results
    return False, "Rejected: No BITS Pilani signal found"
