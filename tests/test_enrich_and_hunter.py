"""
Unit Test Suite for LinkedIn Contact Discovery, Strict Verification, Profile Signal Extraction,
and Hunter.io Direct Human Email Discovery.
"""

import os
from unittest.mock import patch, MagicMock
import pytest

from src.models import ContactPerson
from src.utils.company_matcher import (
    verify_contact_company,
    verify_and_extract_contact_signals,
    normalize_company_name,
)
from src.utils.email_hunter import (
    clean_domain_from_company,
    find_direct_email,
)
from src.nodes.enrich import (
    parse_linkedin_search_result,
    find_hr_email_for_company,
    find_contacts_for_company,
    clear_contacts_cache,
)


# ============================================================================
# PART 1: Company Normalization & Domain Extraction Tests
# ============================================================================

def test_clean_domain_from_company():
    # Known overrides
    assert clean_domain_from_company("Cred") == "cred.club"
    assert clean_domain_from_company("Swiggy") == "swiggy.in"
    assert clean_domain_from_company("Zomato") == "zomato.com"
    assert clean_domain_from_company("Groww") == "groww.in"

    # Standard clean name
    assert clean_domain_from_company("NetApp") == "netapp.com"
    assert clean_domain_from_company("Acme AI Labs Pvt Ltd") == "acmeailabspvtltd.com"

    # From job_url (non-job board)
    assert clean_domain_from_company("Uber", "https://careers.uber.com/jobs/123") == "careers.uber.com"

    # From job board url (should ignore job boards like greenhouse, lever, linkedin)
    assert clean_domain_from_company("Databricks", "https://boards.greenhouse.io/databricks/jobs/456") == "databricks.com"
    assert clean_domain_from_company("Scale AI", "https://www.linkedin.com/jobs/view/789") == "scaleai.com"


# ============================================================================
# PART 2: Hunter.io Direct Email Discovery Tests
# ============================================================================

def test_find_direct_email_pattern_fallback():
    # No hunter key or fallback
    with patch.dict(os.environ, {"HUNTER_API_KEY": ""}, clear=False):
        res = find_direct_email("Aditya", "Sharma", "cred.club")
        assert res["email"] == "aditya.sharma@cred.club"
        assert res["alt_email"] == "aditya@cred.club"
        assert res["status"] == "PATTERN_GUESS"
        assert res["score"] == 50

        # Single name
        res_single = find_direct_email("Rahul", "", "swiggy.in")
        assert res_single["email"] == "rahul@swiggy.in"
        assert res_single["status"] == "PATTERN_GUESS"


@patch("src.utils.email_hunter.httpx.Client")
def test_find_direct_email_hunter_verified(mock_client_cls):
    # Mock Hunter.io returning high confidence email
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "email": "asharma@cred.club",
            "score": 92,
        }
    }
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    with patch.dict(os.environ, {"HUNTER_API_KEY": "test_hunter_key_123"}, clear=False):
        res = find_direct_email("Aditya", "Sharma", "cred.club")
        assert res["status"] == "VERIFIED"
        assert res["email"] == "asharma@cred.club"
        assert res["score"] == 92


@patch("src.utils.email_hunter.httpx.Client")
def test_find_direct_email_hunter_low_score_fallback(mock_client_cls):
    # Mock Hunter.io returning low score (< 70)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "email": "aditya@cred.club",
            "score": 45,  # < 70 threshold
        }
    }
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    with patch.dict(os.environ, {"HUNTER_API_KEY": "test_hunter_key_123"}, clear=False):
        res = find_direct_email("Aditya", "Sharma", "cred.club")
        assert res["status"] == "PATTERN_GUESS"
        assert res["email"] == "aditya.sharma@cred.club"


# ============================================================================
# PART 3: Strict Active-Company & Non-Intern Verifier (Rules A, B, C)
# ============================================================================

def test_verify_contact_signals_rule_a_active_company():
    # Valid active employee
    title = "Rohan Gupta - Senior AI Engineer at NetApp | LinkedIn"
    snippet = "Bengaluru, Karnataka, India · Senior AI Engineer at NetApp"
    signals = verify_and_extract_contact_signals("NetApp", title, snippet)
    assert signals["is_valid"] is True
    assert signals["current_company"] == "NetApp"
    assert signals["years_experience_level"] == "senior"

    # Past employee (Ex-)
    title_ex = "Pooja Verma - Ex-NetApp | AI Researcher at Acme | LinkedIn"
    signals_ex = verify_and_extract_contact_signals("NetApp", title_ex, "")
    assert signals_ex["is_valid"] is False
    assert "Past employee" in (signals_ex["rejection_reason"] or "")

    # Past employee (Former)
    title_former = "Vikram Rao - Former Staff ML Engineer at NetApp | LinkedIn"
    signals_former = verify_and_extract_contact_signals("NetApp", title_former, "")
    assert signals_former["is_valid"] is False

    # Incoming employee (not yet employed)
    title_incoming = "Arjun Patel - Incoming Software Engineer at NetApp | LinkedIn"
    signals_incoming = verify_and_extract_contact_signals("NetApp", title_incoming, "")
    assert signals_incoming["is_valid"] is False

    # Conflicting / Wrong Company
    title_wrong = "Siddharth Jain - Lead ML Engineer at Microsoft | LinkedIn"
    signals_wrong = verify_and_extract_contact_signals("NetApp", title_wrong, "Experience: Microsoft")
    assert signals_wrong["is_valid"] is False


def test_verify_contact_signals_rule_b_intern_gating():
    # Intern without >1 year tenure -> Hard reject
    title_intern = "Kavya Nair - AI Intern at NetApp | LinkedIn"
    snippet_intern = "Bengaluru, India · AI Intern at NetApp for 3 mos"
    signals_intern = verify_and_extract_contact_signals("NetApp", title_intern, snippet_intern)
    assert signals_intern["is_valid"] is False
    assert "Intern" in (signals_intern["rejection_reason"] or "")

    # Summer Analyst -> Hard reject
    title_trainee = "Deepak S - Summer Analyst at NetApp | LinkedIn"
    signals_trainee = verify_and_extract_contact_signals("NetApp", title_trainee, "")
    assert signals_trainee["is_valid"] is False

    # Intern with >1 year tenure -> Accepted
    snippet_long = "Bengaluru, India · Experience: NetApp · 2 years · Full-time apprentice"
    signals_long = verify_and_extract_contact_signals("NetApp", title_intern, snippet_long)
    assert signals_long["is_valid"] is True


def test_verify_contact_signals_rule_c_bits_extraction():
    # Full-time BITS Pilani
    title_bits = "Anand Kumar - ML Engineer at NetApp | BITS Pilani | LinkedIn"
    snippet_bits = "Bengaluru · Education: Birla Institute of Technology and Science, Pilani"
    sig_bits = verify_and_extract_contact_signals("NetApp", title_bits, snippet_bits)
    assert sig_bits["is_valid"] is True
    assert sig_bits["is_bits_alum"] is True
    assert sig_bits["bits_type"] == "FULL_TIME"

    # BITS Goa campus
    title_goa = "Neha Singh - AI Engineer at NetApp | BITS Goa | LinkedIn"
    sig_goa = verify_and_extract_contact_signals("NetApp", title_goa, "")
    assert sig_goa["is_valid"] is True
    assert sig_goa["is_bits_alum"] is True
    assert sig_goa["bits_type"] == "FULL_TIME"

    # BITS WILP
    title_wilp = "Sanjay M - Staff Engineer at NetApp | BPHC | LinkedIn"
    snippet_wilp = "Education: BITS Pilani WILP (Work Integrated Learning Programmes)"
    sig_wilp = verify_and_extract_contact_signals("NetApp", title_wilp, snippet_wilp)
    assert sig_wilp["is_valid"] is True
    assert sig_wilp["is_bits_alum"] is True
    assert sig_wilp["bits_type"] == "WILP"

    # Non-BITS
    title_iit = "Rajesh K - SDE 2 at NetApp | IIT Bombay | LinkedIn"
    sig_iit = verify_and_extract_contact_signals("NetApp", title_iit, "")
    assert sig_iit["is_valid"] is True
    assert sig_iit["is_bits_alum"] is False
    assert sig_iit["bits_type"] == "NONE"


def test_verify_contact_signals_rule_c_ai_interest_and_seniority():
    # Test that "AI" in company name (e.g. Scale AI) does NOT trigger false positive for a recruiter
    title_recruiter = "Priya Roy - Technical Recruiter at Scale AI | LinkedIn"
    snippet_recruiter = "Hiring top talent across engineering and operations"
    sig_rec = verify_and_extract_contact_signals("Scale AI", title_recruiter, snippet_recruiter)
    assert sig_rec["is_valid"] is True
    assert sig_rec["stated_ai_ml_interest"] is False  # Scale AI name stripped out!

    # Test true AI interest in candidate's headline
    title_ai = "Meera Joshi - Staff ML Engineer at NetApp | LLM & Agentic Systems | LinkedIn"
    sig_ai = verify_and_extract_contact_signals("NetApp", title_ai, "Building generative AI pipelines")
    assert sig_ai["is_valid"] is True
    assert sig_ai["stated_ai_ml_interest"] is True
    assert sig_ai["years_experience_level"] == "senior"

    # Seniority levels:
    # Senior
    sig_dir = verify_and_extract_contact_signals("NetApp", "Amit K - Director of Engineering at NetApp | LinkedIn", "")
    assert sig_dir["years_experience_level"] == "senior"

    # Mid
    sig_mid = verify_and_extract_contact_signals("NetApp", "Sunil G - SDE II at NetApp | LinkedIn", "")
    assert sig_mid["years_experience_level"] == "mid"

    # Junior
    sig_jr = verify_and_extract_contact_signals("NetApp", "Aarti T - Software Engineer at NetApp | LinkedIn", "")
    assert sig_jr["years_experience_level"] == "junior"

    # Mutual connections
    sig_mutual = verify_and_extract_contact_signals(
        "NetApp",
        "Sunil G - SDE II at NetApp | LinkedIn",
        "Bengaluru · 15 mutual connections"
    )
    assert sig_mutual["mutual_connections"] is True


# ============================================================================
# PART 4: parse_linkedin_search_result & Direct Human Email
# ============================================================================

def test_parse_linkedin_search_result_success():
    item = {
        "url": "https://www.linkedin.com/in/aravind-n-998877",
        "title": "Aravind N - AI Engineer at Swiggy | BITS Pilani | LinkedIn",
        "content": "Bengaluru · Education: BITS Pilani · 12 mutual connections",
    }
    contact = parse_linkedin_search_result(item, tier="1_ALUMNI", company="Swiggy")
    assert contact is not None
    assert contact.name == "Aravind N"
    assert contact.tier == "1_ALUMNI"
    assert contact.is_bits_alum is True
    assert contact.bits_type == "FULL_TIME"
    assert contact.email == "aravind.n@swiggy.in"
    assert contact.email_status in ("PATTERN_GUESS", "VERIFIED")
    assert contact.mutual_connections is True


def test_parse_linkedin_search_result_directory_or_company_rejected():
    # Directory page
    item_dir = {
        "url": "https://www.linkedin.com/in/dir/John/Smith",
        "title": "Top 10 Profiles for John Smith | LinkedIn",
        "content": "Directory of profiles",
    }
    assert parse_linkedin_search_result(item_dir, tier="2_TEAM_ENGINEER_OR_HM", company="NetApp") is None

    # Company page
    item_comp = {
        "url": "https://www.linkedin.com/company/netapp",
        "title": "NetApp | LinkedIn",
        "content": "Data storage company",
    }
    assert parse_linkedin_search_result(item_comp, tier="2_TEAM_ENGINEER_OR_HM", company="NetApp") is None


# ============================================================================
# PART 5: find_hr_email_for_company Prioritization
# ============================================================================

def test_find_hr_email_for_company_prioritizes_human_email():
    human_contact = ContactPerson(
        name="Vivek Sharma",
        headline="AI Lead at Cred",
        linkedin_url="https://www.linkedin.com/in/vivek-sharma",
        tier="2_TEAM_ENGINEER_OR_HM",
        relevance_note="AI Lead",
        email="vivek.sharma@cred.club",
        email_status="VERIFIED",
    )

    # When verified human contact exists, returns that human email!
    email = find_hr_email_for_company(
        company="Cred",
        job_url="https://cred.club/careers",
        jd_text="Contact jobs@cred.club for queries",
        contacts=[human_contact],
    )
    assert email == "vivek.sharma@cred.club"

    # When no contacts exist, falls back to JD text email
    email_jd = find_hr_email_for_company(
        company="Cred",
        job_url="https://cred.club/careers",
        jd_text="Send your resume to talent@cred.club",
        contacts=[],
    )
    assert email_jd == "talent@cred.club"

    # When neither exists, falls back to recruiting@{domain}
    email_fallback = find_hr_email_for_company(
        company="Cred",
        job_url="https://cred.club/careers",
        jd_text="No email here",
        contacts=[],
    )
    assert email_fallback == "recruiting@cred.club"


# ============================================================================
# PART 6: find_contacts_for_company Ranking & Max Contacts
# ============================================================================

@patch("src.nodes.enrich.search_dork_engine")
def test_find_contacts_for_company_ranking_and_capping(mock_dork):
    clear_contacts_cache()

    # Tier 1 (BITS) results: 1 full-time, 1 WILP
    t1_results = [
        {
            "url": "https://www.linkedin.com/in/bits-alum-fulltime",
            "title": "Aman Verma - SDE 2 at NetApp | BITS Pilani | LinkedIn",
            "content": "Bengaluru · Education: BITS Pilani",
        },
        {
            "url": "https://www.linkedin.com/in/bits-alum-wilp",
            "title": "Bhavna Patel - SDE 2 at NetApp | BPHC | LinkedIn",
            "content": "Bengaluru · Education: BITS Pilani WILP",
        },
    ]

    # Tier 2 results: 1 AI/ML engineer, 1 general engineer
    t2_results = [
        {
            "url": "https://www.linkedin.com/in/ai-lead",
            "title": "Chetan Rao - Machine Learning Lead at NetApp | LinkedIn",
            "content": "Bengaluru · Leading LLM agents team",
        },
        {
            "url": "https://www.linkedin.com/in/backend-dev",
            "title": "Divya Sharma - Software Engineer at NetApp | LinkedIn",
            "content": "Bengaluru · Backend distributed systems",
        },
    ]

    # Tier 3 results: 1 recruiter
    t3_results = [
        {
            "url": "https://www.linkedin.com/in/recruiter-netapp",
            "title": "Esha Nair - Technical Recruiter at NetApp | LinkedIn",
            "content": "Bengaluru · Hiring tech talent at NetApp",
        }
    ]

    mock_dork.side_effect = [t1_results, t2_results, t3_results]

    contacts = find_contacts_for_company("NetApp", role="AI Engineer", max_contacts=4)

    assert len(contacts) == 4
    # Check ranking:
    # 1. Full-time BITS
    assert contacts[0].name == "Aman Verma"
    assert contacts[0].bits_type == "FULL_TIME"
    # 2. BITS WILP
    assert contacts[1].name == "Bhavna Patel"
    assert contacts[1].bits_type == "WILP"
    # 3. AI/ML Lead (stated interest)
    assert contacts[2].name == "Chetan Rao"
    assert contacts[2].stated_ai_ml_interest is True
    # 4. Other team engineer
    assert contacts[3].name == "Divya Sharma"

    # Verify cache hit on second call
    mock_dork.reset_mock()
    contacts_cached = find_contacts_for_company("NetApp", max_contacts=4)
    assert len(contacts_cached) == 4
    assert mock_dork.call_count == 0  # hit cache!
