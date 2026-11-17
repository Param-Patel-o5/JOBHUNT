"""
Unit tests for the overhauled scraper architecture (src/nodes/scrape.py).
Tests clean Job ID extraction, company flood capping, and title parsing.
"""

import pytest
from src.nodes.scrape import (
    extract_clean_job_id,
    _parse_title_company,
    deduplicate_and_cap_jobs,
)
from src.models import JobPosting


# =========================================================================
# 1. Tests for Clean Job ID Extraction
# =========================================================================

def test_extract_clean_job_id_linkedin():
    # Standard view URL
    url1 = "https://www.linkedin.com/jobs/view/4487742567/"
    assert extract_clean_job_id(url1) == "4487742567"

    # URL with tracking parameters
    url2 = "https://www.linkedin.com/jobs/view/4487742567?refId=abc&trackingId=xyz"
    assert extract_clean_job_id(url2) == "4487742567"

    # Slugged title URL
    url3 = "https://in.linkedin.com/jobs/view/ai-engineer-at-netapp-4487742567"
    assert extract_clean_job_id(url3) == "4487742567"

    # currentJobId parameter
    url4 = "https://www.linkedin.com/jobs/search/?currentJobId=4487742567&keywords=AI"
    assert extract_clean_job_id(url4) == "4487742567"


def test_extract_clean_job_id_ats_platforms():
    # Greenhouse
    gh_url = "https://boards.greenhouse.io/swiggy/jobs/6543210"
    assert extract_clean_job_id(gh_url) == "6543210"

    # Lever
    lev_url = "https://jobs.lever.co/palantir/5c23a7bb-1e42-4f3b-8c6e-923f18e1d234"
    assert extract_clean_job_id(lev_url) == "5c23a7bb"

    # Ashby
    ash_url = "https://jobs.ashbyhq.com/mistral/a7b8c9d0-1234-5678-90ab-cdef12345678"
    assert extract_clean_job_id(ash_url) == "a7b8c9d0"


def test_extract_clean_job_id_startup_boards():
    # YC Work at a Startup
    yc_url = "https://www.workatastartup.com/jobs/56789"
    assert extract_clean_job_id(yc_url) == "56789"

    # Wellfound
    wf_url = "https://wellfound.com/jobs/3456789-ai-engineer"
    assert extract_clean_job_id(wf_url) == "3456789"

    # Instahyre
    insta_url = "https://www.instahyre.com/job-123456-ai-engineer-at-cred/"
    assert extract_clean_job_id(insta_url) == "123456"

    # Himalayas
    him_url = "https://himalayas.app/companies/acme/jobs/ml-engineer-99"
    assert extract_clean_job_id(him_url) == "ml-engineer-"


def test_extract_clean_job_id_fallback():
    url = "https://example.com/careers/special"
    job_id = extract_clean_job_id(url, company="Acme", role="AI Engineer")
    assert len(job_id) == 10
    assert job_id.isalnum()


# =========================================================================
# 2. Tests for Title and Company Parsing
# =========================================================================

def test_parse_title_company_various_sources():
    # YC Work at a Startup
    comp, role = _parse_title_company(
        "AI Engineer at Decagon - Work at a Startup",
        "https://www.workatastartup.com/jobs/123"
    )
    assert comp == "Decagon"
    assert role == "AI Engineer"

    # Wellfound
    comp, role = _parse_title_company(
        "Harvey hiring Machine Learning Engineer in Bengaluru | Wellfound",
        "https://wellfound.com/jobs/456"
    )
    assert comp == "Harvey"
    assert role == "Machine Learning Engineer"

    # Instahyre
    comp, role = _parse_title_company(
        "AI Engineer Job at Swiggy in Bengaluru - Instahyre",
        "https://www.instahyre.com/job-789"
    )
    assert comp == "Swiggy"
    assert role == "AI Engineer"

    # LinkedIn
    comp, role = _parse_title_company(
        "NetApp hiring AI Engineer in Bengaluru, Karnataka, India | LinkedIn",
        "https://www.linkedin.com/jobs/view/999"
    )
    assert comp == "NetApp"
    assert role == "AI Engineer"


# =========================================================================
# 3. Tests for Company Flood Capping & Deduplication
# =========================================================================

def test_company_flood_cap_enforces_max_two_roles():
    # 5 roles from Stripe (with different legal suffixes: Stripe, Stripe Inc, Stripe India)
    stripe_jobs = [
        JobPosting(job_id="s1", company="Stripe", role="AI Engineer", location="Bengaluru", jd_text="ML", job_url="https://stripe.com/1", source="linkedin"),
        JobPosting(job_id="s2", company="Stripe Inc", role="Machine Learning Engineer", location="Bengaluru", jd_text="ML", job_url="https://stripe.com/2", source="greenhouse"),
        JobPosting(job_id="s3", company="Stripe India Pvt Ltd", role="LLM Engineer", location="Bengaluru", jd_text="ML", job_url="https://stripe.com/3", source="ashby"),
        JobPosting(job_id="s4", company="Stripe", role="Data Scientist - AI", location="Bengaluru", jd_text="ML", job_url="https://stripe.com/4", source="lever"),
        JobPosting(job_id="s5", company="Stripe Technologies", role="GenAI Engineer", location="Bengaluru", jd_text="ML", job_url="https://stripe.com/5", source="wellfound"),
    ]

    # 3 roles from Cred
    cred_jobs = [
        JobPosting(job_id="c1", company="Cred", role="AI Engineer", location="Bengaluru", jd_text="ML", job_url="https://cred.club/1", source="instahyre"),
        JobPosting(job_id="c2", company="Cred", role="Machine Learning Engineer", location="Bengaluru", jd_text="ML", job_url="https://cred.club/2", source="greenhouse"),
        JobPosting(job_id="c3", company="Cred India", role="Data Scientist", location="Bengaluru", jd_text="ML", job_url="https://cred.club/3", source="linkedin"),
    ]

    # 1 role from Swiggy
    swiggy_jobs = [
        JobPosting(job_id="sw1", company="Swiggy", role="AI Engineer", location="Bengaluru", jd_text="ML", job_url="https://swiggy.com/1", source="linkedin"),
    ]

    all_jobs = stripe_jobs + cred_jobs + swiggy_jobs
    assert len(all_jobs) == 9

    deduped = deduplicate_and_cap_jobs(all_jobs, max_per_company=2)

    # Stripe must have exactly 2 roles (not 5)
    stripe_surviving = [j for j in deduped if "stripe" in j.company.lower()]
    assert len(stripe_surviving) == 2

    # Cred must have exactly 2 roles (not 3)
    cred_surviving = [j for j in deduped if "cred" in j.company.lower()]
    assert len(cred_surviving) == 2

    # Swiggy must have 1 role
    swiggy_surviving = [j for j in deduped if "swiggy" in j.company.lower()]
    assert len(swiggy_surviving) == 1

    # Total surviving must be 2 + 2 + 1 = 5
    assert len(deduped) == 5


def test_deduplicate_identical_company_role_across_channels():
    # Same job found on both LinkedIn and Instahyre
    job_li = JobPosting(
        job_id="4487742567",
        company="NetApp",
        role="AI Engineer",
        location="Bengaluru, India",
        jd_text="Build agentic systems.",
        job_url="https://www.linkedin.com/jobs/view/4487742567",
        source="linkedin",
    )
    job_insta = JobPosting(
        job_id="insta-1234",
        company="NetApp India Pvt Ltd",
        role="AI Engineer",
        location="Bengaluru",
        jd_text="Build agentic systems.",
        job_url="https://www.instahyre.com/job-1234",
        source="instahyre",
    )

    deduped = deduplicate_and_cap_jobs([job_li, job_insta], max_per_company=2)
    # The duplicate (NetApp, AI Engineer) must be dropped
    assert len(deduped) == 1
    assert deduped[0].source == "linkedin"
