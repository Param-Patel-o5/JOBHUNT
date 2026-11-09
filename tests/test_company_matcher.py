"""
Unit Test Suite for Company Entity Verifier & LinkedIn Title Structural Parser.

Tests the 3-Stage Deterministic Entity Verification Pipeline against:
  1. Valid Active Employee (Score 1.0)
  2. Ex-Employee Trap (Score 0.0)
  3. Substring Collision Trap (Score 0.0)
  4. Suffix Normalization (Score 1.0)
  5. Truncated Title + Valid Snippet Experience (Score 0.85)
  6. Random Bio Mention / Tool Reference (Score 0.0)
  7. Additional Real-World Edge Cases (Certifications, Multiple Clauses, Ambiguous Brands)
"""

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from src.utils.company_matcher import (
    normalize_company_name,
    verify_contact_company,
    parse_linkedin_title,
    is_brand_ambiguous,
)


# =========================================================================
# Part 1: Suffix Normalization Unit Tests
# =========================================================================

def test_suffix_normalization_netapp():
    cleaned, variations = normalize_company_name("NetApp India Pvt. Ltd.")
    assert cleaned == "netapp"
    assert "netapp" in variations


def test_suffix_normalization_sony():
    cleaned, variations = normalize_company_name("Sony India Software Centre")
    assert cleaned == "sony"


def test_suffix_normalization_walmart():
    cleaned, variations = normalize_company_name("Walmart Global Tech India")
    assert cleaned == "walmart"


def test_suffix_normalization_ntt():
    cleaned, variations = normalize_company_name("NTT DATA North America")
    assert cleaned == "ntt data"


def test_suffix_normalization_scale_ai():
    # 'ai' is not a legal suffix, should be preserved
    cleaned, variations = normalize_company_name("Scale AI")
    assert cleaned == "scale ai"


# =========================================================================
# Part 2: The 6 Required Critical Failure Mode Tests
# =========================================================================

def test_mode_1_valid_active_employee():
    """1. Valid Active Employee: Must pass with score 1.0."""
    is_valid, score, reason = verify_contact_company(
        company_name="Databricks",
        linkedin_title="Rohan Gupta - Senior AI Engineer at Databricks | LinkedIn",
        linkedin_snippet=""
    )
    assert is_valid is True
    assert score == 1.0
    assert "Verified: Primary title active employer" in reason


def test_mode_2_ex_employee_trap():
    """2. Ex-Employee Trap: Must fail (False) and reject past employee."""
    is_valid, score, reason = verify_contact_company(
        company_name="Databricks",
        linkedin_title="Rohan Gupta - SDE II at Stripe | Ex-Databricks | LinkedIn",
        linkedin_snippet=""
    )
    assert is_valid is False
    assert score == 0.0
    assert "Past employee" in reason


def test_mode_3_substring_collision_trap():
    """3. Substring Collision Trap: 'at scale' at Infosys must fail."""
    is_valid, score, reason = verify_contact_company(
        company_name="Scale AI",
        linkedin_title="Amit Verma - Building ML Systems at scale at Infosys | LinkedIn",
        linkedin_snippet=""
    )
    assert is_valid is False
    assert score == 0.0


def test_mode_4_suffix_normalization():
    """4. Suffix Normalization: 'NetApp India Pvt. Ltd.' matching '@ NetApp' must pass."""
    is_valid, score, reason = verify_contact_company(
        company_name="NetApp India Pvt. Ltd.",
        linkedin_title="Sonali Sharma - Software Engineer @ NetApp | LinkedIn",
        linkedin_snippet=""
    )
    assert is_valid is True
    assert score == 1.0
    assert "Verified: Primary title active employer" in reason


def test_mode_5_truncated_title_valid_snippet_experience():
    """5. Truncated Title + Valid Snippet Experience: Must pass with score 0.85."""
    is_valid, score, reason = verify_contact_company(
        company_name="Perplexity",
        linkedin_title="Aarav Mehta - Applied AI Engineer building search... | LinkedIn",
        linkedin_snippet="Location: Bengaluru · Experience: Perplexity · Education: BITS Pilani"
    )
    assert is_valid is True
    assert score == 0.85
    assert "Verified: Snippet experience block" in reason


def test_mode_6_random_bio_mention():
    """6. Random Bio Mention: Tool mention in bio without active employment must fail."""
    is_valid, score, reason = verify_contact_company(
        company_name="Cohere",
        linkedin_title="Vikram Singh - ML Engineer at TCS | LinkedIn",
        linkedin_snippet="Built a RAG chatbot using Cohere and OpenAI APIs."
    )
    assert is_valid is False
    assert score == 0.0
    assert "Weak snippet mention only" in reason


# =========================================================================
# Part 3: Additional Edge Cases & Robustness Tests
# =========================================================================

def test_certification_not_employee():
    """Contact holds a certification (e.g. Databricks Certified) but isn't an employee."""
    is_valid, score, reason = verify_contact_company(
        company_name="Databricks",
        linkedin_title="Piyush Jain - Databricks Certified GenAI & ML Engineer | BITS Pilani | LinkedIn",
        linkedin_snippet=""
    )
    assert is_valid is False
    assert score == 0.0
    assert "Certification" in reason or "Rejected" in reason


def test_ambiguous_brand_front_end():
    """Company named 'Front' vs 'Front End Engineer at Acme Corp'."""
    is_valid, score, reason = verify_contact_company(
        company_name="Front",
        linkedin_title="David Lee - Front End Engineer at Acme Corp | LinkedIn",
        linkedin_snippet=""
    )
    assert is_valid is False
    assert score == 0.0


def test_college_first_active_role_second_clause():
    """Headline starts with college, then states active role at target company."""
    is_valid, score, reason = verify_contact_company(
        company_name="Databricks",
        linkedin_title="Rohan Gupta - BITS Pilani | AI Engineer at Databricks | LinkedIn",
        linkedin_snippet=""
    )
    assert is_valid is True
    assert score == 1.0


def test_postera_dash_format():
    """Headline uses 'Role - Company' format."""
    is_valid, score, reason = verify_contact_company(
        company_name="PostEra",
        linkedin_title="Kriti Goyal - Machine Learning Researcher - PostEra | LinkedIn",
        linkedin_snippet=""
    )
    assert is_valid is True
    assert score == 1.0


def test_past_employee_in_snippet_rejected():
    """Snippet explicitly says 'Past: Company'."""
    is_valid, score, reason = verify_contact_company(
        company_name="Perplexity",
        linkedin_title="Aarav Mehta - Applied AI Engineer | LinkedIn",
        linkedin_snippet="Location: SF · Past: Perplexity · Currently at Google"
    )
    assert is_valid is False
    assert score == 0.0
    assert "Past employee" in reason
