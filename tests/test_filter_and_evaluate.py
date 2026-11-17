"""
Unit tests for deterministic filtering (src/nodes/filter.py)
and evaluation match score floor (src/nodes/evaluate.py).
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.nodes.filter import (
    is_valid_location,
    extract_required_yoe,
    is_valid_role_title,
    filter_jobs,
)
from src.nodes.evaluate import (
    score_and_tailor_jobs,
    MATCH_SCORE_FLOOR,
)
from src.models import JobPosting, CompanyIntel, MatchAndTailorResult


# =========================================================================
# 1. Tests for Geographic & Remote Filter (is_valid_location)
# =========================================================================

def test_geographic_hard_reject_foreign_locations():
    foreign_locs = [
        "San Francisco, CA",
        "New York, NY",
        "Seattle, WA",
        "Austin, TX",
        "United States",
        "USA",
        "London, UK",
        "Toronto, Canada",
        "Berlin, Germany",
        "Paris, France",
        "Sydney, Australia",
    ]
    for loc in foreign_locs:
        valid, reason = is_valid_location(loc, "Building cutting-edge AI systems.")
        assert valid is False, f"Expected '{loc}' to be rejected, but got accepted"
        assert "FILTER REJECT" in reason


def test_geographic_hard_reject_generic_remote():
    # Generic remote without India specification
    generic_remotes = [
        "Remote",
        "Worldwide / Remote",
        "Anywhere",
        "Remote, Global",
    ]
    for loc in generic_remotes:
        valid, reason = is_valid_location(loc, "Join our global distributed engineering team.")
        assert valid is False, f"Expected generic '{loc}' to be rejected"
        assert "Remote role without explicit India presence" in reason


def test_geographic_reject_us_work_authorization_restriction():
    # Location says Remote, but JD restricts to US citizens or US residency
    loc = "Remote"
    jd_texts = [
        "Candidates must reside in the US.",
        "Role open only to US citizens only due to compliance.",
        "Must be authorized to work in the United States without sponsorship.",
        "EU timezones only.",
    ]
    for jd in jd_texts:
        valid, reason = is_valid_location(loc, jd)
        assert valid is False
        assert "FILTER REJECT" in reason


def test_geographic_permitted_india_locations():
    permitted = [
        ("Bengaluru, Karnataka, India", "AI startup in HSR Layout"),
        ("Bangalore", "Fast growing LLM platform"),
        ("Hyderabad, Telangana", "Building multi-agent systems"),
        ("Pune, Maharashtra", "Deep learning team"),
        ("Mumbai", "Fintech AI"),
        ("Gurugram, Haryana", "Agentic automation"),
        ("Gurgaon", "RAG research team"),
        ("Noida, Uttar Pradesh", "Computer vision pipelines"),
        ("Chennai, Tamil Nadu", "Healthcare AI"),
        ("Delhi", "Applied ML team"),
        ("Remote - India", "100% remote within India"),
        ("India Remote", "Remote anywhere in India"),
        ("Remote (India)", "Hiring remote engineers across India"),
        ("Remote", "We are a remote-first team. This role is open to Remote - India candidates."),
        ("Remote", "Location: anywhere in India. Work from home."),
    ]
    for loc, jd in permitted:
        valid, reason = is_valid_location(loc, jd)
        assert valid is True, f"Expected '{loc}' to be permitted. Reason was: {reason}"


# =========================================================================
# 2. Tests for Experience Cap & Extraction (extract_required_yoe)
# =========================================================================

def test_extract_required_yoe_standard_ranges():
    assert extract_required_yoe("Requires 3+ years of experience building Python ML systems.") == 3
    assert extract_required_yoe("Candidates should have 2-4 years of experience in deep learning.") == 2
    assert extract_required_yoe("Minimum 4 years of hands-on experience with LLMs.") == 4
    assert extract_required_yoe("Freshers or 0-2 years of experience welcome.") == 0
    assert extract_required_yoe("Early career role, no experience required.") == 0


def test_extract_required_yoe_ignores_preferred_and_company_history():
    # "5+ years preferred" should be ignored when base is 2
    jd_preferred = "Requires 2+ years of experience with PyTorch. 5+ years of experience preferred."
    assert extract_required_yoe(jd_preferred) == 2

    # Company age should be ignored
    jd_company = "Our company has 10+ years of experience delivering cloud solutions. Requires 1 year of experience in AI."
    assert extract_required_yoe(jd_company) == 1


def test_extract_required_yoe_hard_reject_5plus():
    jd_senior_exp = "Must have at least 5+ years of experience architecting large scale distributed ML infrastructure."
    yoe = extract_required_yoe(jd_senior_exp)
    assert yoe >= 5


# =========================================================================
# 3. Tests for Role Type & Title Segregation (is_valid_role_title)
# =========================================================================

def test_role_title_hard_reject_internships():
    internships = [
        "AI Intern",
        "Machine Learning Internship",
        "Graduate Trainee - AI/ML",
        "Data Science Apprentice",
        "GenAI Co-op",
        "Student Researcher - AI",
    ]
    for title in internships:
        valid, reason = is_valid_role_title(title)
        assert valid is False, f"Expected internship '{title}' to be rejected"
        assert "Internship / Trainee" in reason


def test_role_title_hard_reject_senior_leadership():
    seniors = [
        "Senior AI Engineer",
        "Sr. Machine Learning Engineer",
        "Staff AI Scientist",
        "Principal ML Engineer",
        "Lead GenAI Architect",
        "Engineering Manager - AI",
        "Director of Machine Learning",
        "VP of Artificial Intelligence",
        "Head of AI",
    ]
    for title in seniors:
        valid, reason = is_valid_role_title(title)
        assert valid is False, f"Expected senior title '{title}' to be rejected"
        assert "Senior / Leadership" in reason


def test_role_title_hard_reject_non_ai_tracks():
    non_ai = [
        "DevOps Engineer",
        "DevOps Engineer - AI Infrastructure",
        "SRE (Site Reliability Engineer)",
        "Data Engineer",
        "Data Analyst",
        "Business Analyst",
        "Frontend Engineer",
        "Frontend Developer (AI App)",
        "UI/UX Designer",
        "iOS Engineer",
        "Android Developer",
        "QA Automation Engineer",
        "SDET - AI Platform",
        "Security Engineer",
        "Network Engineer",
    ]
    for title in non_ai:
        valid, reason = is_valid_role_title(title)
        assert valid is False, f"Expected non-AI track '{title}' to be rejected"
        assert "Non-AI track role" in reason


def test_role_title_hard_reject_pure_software_without_ai():
    pure_swe = [
        "Software Engineer",
        "Backend Engineer",
        "Full Stack Developer",
        "SDE-1",
        "Software Developer",
    ]
    for title in pure_swe:
        valid, reason = is_valid_role_title(title)
        assert valid is False, f"Expected pure SWE title '{title}' to be rejected"
        assert "lacks required AI/ML core token" in reason


def test_role_title_permitted_ai_titles():
    permitted_titles = [
        "AI Engineer",
        "Associate AI Engineer",
        "Machine Learning Engineer",
        "Software Engineer - Machine Learning",
        "Backend Engineer (LLM & Agents)",
        "Data Scientist",
        "Data Scientist - GenAI",
        "Deep Learning Engineer",
        "Generative AI Engineer",
        "NLP Engineer",
        "Computer Vision Engineer",
        "Agentic AI Engineer",
        "RAG Systems Engineer",
        "Applied AI Engineer",
    ]
    for title in permitted_titles:
        valid, reason = is_valid_role_title(title)
        assert valid is True, f"Expected '{title}' to be valid. Reason was: {reason}"


# =========================================================================
# 4. Tests for Master filter_jobs Integration
# =========================================================================

def test_filter_jobs_integration():
    sample_jobs = [
        # 1. Valid AI Engineer in Bengaluru (0-4 YoE) -> PASS
        JobPosting(
            job_id="valid-1",
            company="NeuralWorks",
            role="AI Engineer",
            location="Bengaluru, Karnataka, India",
            jd_text="Looking for an AI Engineer with 2+ years of experience building LLM pipelines.",
            job_url="https://example.com/1",
            source="greenhouse",
        ),
        # 2. Foreign location (San Francisco) -> REJECT
        JobPosting(
            job_id="reject-geo",
            company="USCorp",
            role="Machine Learning Engineer",
            location="San Francisco, CA",
            jd_text="Join our SF office with 1 year of ML experience.",
            job_url="https://example.com/2",
            source="ashby",
        ),
        # 3. Generic Remote without India -> REJECT
        JobPosting(
            job_id="reject-remote",
            company="GlobalTech",
            role="GenAI Engineer",
            location="Remote",
            jd_text="Worldwide remote role.",
            job_url="https://example.com/3",
            source="himalayas",
        ),
        # 4. 5+ YoE senior experience requirement -> REJECT
        JobPosting(
            job_id="reject-yoe",
            company="MegaScale",
            role="AI Engineer",
            location="Hyderabad, India",
            jd_text="Minimum 6+ years of experience required in production ML.",
            job_url="https://example.com/4",
            source="lever",
        ),
        # 5. Internship -> REJECT
        JobPosting(
            job_id="reject-intern",
            company="InnovateAI",
            role="AI Intern",
            location="Pune, India",
            jd_text="6-month full-time internship for students.",
            job_url="https://example.com/5",
            source="jobspy",
        ),
        # 6. Non-AI Track (DevOps) -> REJECT
        JobPosting(
            job_id="reject-devops",
            company="InfraCloud",
            role="DevOps Engineer",
            location="Bengaluru, India",
            jd_text="Manage Kubernetes clusters with 2 years experience.",
            job_url="https://example.com/6",
            source="greenhouse",
        ),
        # 7. Pure Backend without AI token -> REJECT
        JobPosting(
            job_id="reject-backend",
            company="FinPlatform",
            role="Backend Engineer",
            location="Gurugram, India",
            jd_text="Build Django REST APIs with 2 years experience.",
            job_url="https://example.com/7",
            source="lever",
        ),
        # 8. Valid Remote - India Role -> PASS
        JobPosting(
            job_id="valid-2",
            company="AgentFlow",
            role="Associate AI Engineer",
            location="Remote - India",
            jd_text="Build LangGraph agents. 1-3 years experience required.",
            job_url="https://example.com/8",
            source="ashby",
        ),
    ]

    surviving, stats = filter_jobs(sample_jobs)
    assert len(surviving) == 2
    surviving_ids = [j.job_id for j in surviving]
    assert "valid-1" in surviving_ids
    assert "valid-2" in surviving_ids

    assert stats["dropped_invalid_location"] == 2  # SF + Generic Remote
    assert stats["dropped_high_yoe"] == 1         # 6+ YoE
    assert stats["dropped_invalid_title"] == 3    # Intern + DevOps + Pure Backend


# =========================================================================
# 5. Tests for Strict Match Score Floor (>= 75%)
# =========================================================================

@patch("src.nodes.evaluate.save_rejected_evaluated_job")
@patch("src.nodes.evaluate.invoke_structured_llm")
def test_score_and_tailor_jobs_enforces_75_percent_floor(mock_llm, mock_save_reject):
    # Setup test pairs
    job_high = JobPosting(
        job_id="job-high",
        company="HighMatchAI",
        role="AI Engineer",
        location="Bengaluru, India",
        jd_text="LangGraph multi-agent systems and PyPI observability.",
        job_url="https://example.com/high",
        source="ashby",
    )
    job_low = JobPosting(
        job_id="job-low",
        company="LowMatchTech",
        role="Data Scientist",
        location="Pune, India",
        jd_text="Excel statistical forecasting and legacy SQL models.",
        job_url="https://example.com/low",
        source="greenhouse",
    )
    intel = CompanyIntel(
        company_name="TestCorp",
        funding_or_stage="Series B",
        estimated_size="100-250",
        est_entry_ai_ctc_lpa=20.0,
        passes_quality_bar=True,
        summary_2_lines="TestCorp builds AI systems.",
    )

    # Mock high score (88%) and low score (60%)
    high_result = MatchAndTailorResult(
        match_score=88,
        selected_project_id="agent_diagnostician",
        winning_hook_sentence="Candidate built an open-source agent diagnostician.",
        missing_keywords=["evals"],
        resume_bullet_tweaks=["Engineered LLM tracing."],
        jd_core_requirements=["Build LangGraph agents"],
    )
    low_result = MatchAndTailorResult(
        match_score=60,
        selected_project_id="fairtrace",
        winning_hook_sentence="Weak alignment with legacy data science tasks.",
        missing_keywords=["spss", "excel"],
        resume_bullet_tweaks=["Reviewed stats."],
        jd_core_requirements=["Excel models"],
    )

    mock_llm.side_effect = [high_result, low_result]

    pairs = [(job_high, intel), (job_low, intel)]
    results = score_and_tailor_jobs(pairs)

    # Only high score (>= 75%) must pass through
    assert len(results) == 1
    assert results[0][0].job_id == "job-high"
    assert results[0][2].match_score == 88

    # Low score (< 75%) must trigger save_rejected_evaluated_job
    mock_save_reject.assert_called_once()
    called_args = mock_save_reject.call_args[0]
    assert called_args[0].job_id == "job-low"
    assert called_args[2].match_score == 60
