"""
Unit Test Suite for the 6-Step Referral DM Specification in src/nodes/drafter.py.
"""

import re
from unittest.mock import patch, MagicMock
import pytest

from src.models import (
    JobPosting,
    CompanyIntel,
    MatchAndTailorResult,
    ContactPerson,
    OutreachPackage,
)
from src.nodes.drafter import (
    PORTFOLIO_URL,
    BLANK_CONNECTION_STRATEGY,
    determine_opener_type,
    select_projects_for_contact,
    sanitize_referral_dm,
    generate_deterministic_referral_dm,
    build_direct_email_draft,
    _build_fallback_note,
    generate_outreach_for_job,
)


# ============================================================================
# PART 1: Opener Type Determination (Step 1)
# ============================================================================

def test_determine_opener_type_bits_full_time():
    contact = ContactPerson(
        name="Rahul Verma",
        headline="AI Engineer at Swiggy",
        linkedin_url="https://linkedin.com/in/rahul",
        tier="1_ALUMNI",
        relevance_note="BITS Pilani",
        is_bits_alum=True,
        bits_type="FULL_TIME",
    )
    assert determine_opener_type(contact) == "BITS_FULL_TIME"


def test_determine_opener_type_bits_wilp():
    contact = ContactPerson(
        name="Sunil Rao",
        headline="Tech Lead at Swiggy",
        linkedin_url="https://linkedin.com/in/sunil",
        tier="1_ALUMNI",
        relevance_note="BITS WILP",
        is_bits_alum=True,
        bits_type="WILP",
    )
    assert determine_opener_type(contact) == "BITS_WILP"


def test_determine_opener_type_ai_ml_overlap():
    contact = ContactPerson(
        name="Ananya Sen",
        headline="Machine Learning Engineer at Swiggy",
        linkedin_url="https://linkedin.com/in/ananya",
        tier="2_TEAM_ENGINEER_OR_HM",
        relevance_note="ML Team",
        is_bits_alum=False,
        bits_type="NONE",
        stated_ai_ml_interest=True,
    )
    assert determine_opener_type(contact) == "AI_ML_OVERLAP"


def test_determine_opener_type_mutual_connections():
    contact = ContactPerson(
        name="Karan Dave",
        headline="Engineering Manager at Swiggy",
        linkedin_url="https://linkedin.com/in/karan",
        tier="2_TEAM_ENGINEER_OR_HM",
        relevance_note="Manager",
        is_bits_alum=False,
        bits_type="NONE",
        stated_ai_ml_interest=False,
        mutual_connections=True,
    )
    assert determine_opener_type(contact) == "MUTUAL"


def test_determine_opener_type_plain_direct():
    contact = ContactPerson(
        name="Meera Iyer",
        headline="Technical Recruiter at Swiggy",
        linkedin_url="https://linkedin.com/in/meera",
        tier="3_RECRUITER",
        relevance_note="Recruiter",
        is_bits_alum=False,
        bits_type="NONE",
        stated_ai_ml_interest=False,
        mutual_connections=False,
    )
    assert determine_opener_type(contact) == "PLAIN_DIRECT"


# ============================================================================
# PART 2: Project Selection & Seniority/Technicality Gate (Step 3)
# ============================================================================

def test_select_projects_for_contact():
    match_result = MatchAndTailorResult(
        match_score=85,
        selected_project_id="agent_diagnostician",
        winning_hook_sentence="Built an open-source PyPI library for multi-agent LLM debugging.",
        missing_keywords=[],
    )

    # 1. Technical AI contact -> allows 2 projects
    tech_contact = ContactPerson(
        name="Aravind S",
        headline="Senior AI Engineer",
        linkedin_url="https://linkedin.com/in/aravind",
        tier="2_TEAM_ENGINEER_OR_HM",
        relevance_note="",
        stated_ai_ml_interest=True,
        years_experience_level="senior",
    )
    descs_tech = select_projects_for_contact(tech_contact, match_result)
    assert len(descs_tech) == 2
    assert "PyPI" in descs_tech[0]

    # 2. Non-AI recruiter / junior non-tech -> allows 1 project only
    recruiter_contact = ContactPerson(
        name="Sneha P",
        headline="Technical Recruiter",
        linkedin_url="https://linkedin.com/in/sneha",
        tier="3_RECRUITER",
        relevance_note="",
        stated_ai_ml_interest=False,
        years_experience_level="junior",
    )
    descs_rec = select_projects_for_contact(recruiter_contact, match_result)
    assert len(descs_rec) == 1


# ============================================================================
# PART 3: Deterministic Referral DM Generator (Steps 1–5)
# ============================================================================

def test_generate_deterministic_referral_dm_bits_full_time_and_stretch():
    contact = ContactPerson(
        name="Rohit Sharma",
        headline="Senior ML Engineer at Cred",
        linkedin_url="https://linkedin.com/in/rohit",
        tier="1_ALUMNI",
        relevance_note="",
        is_bits_alum=True,
        bits_type="FULL_TIME",
    )
    job = JobPosting(
        job_id="CR-901",
        company="Cred",
        role="AI Engineer",
        location="Bengaluru",
        jd_text="Requires 3+ years experience",
        job_url="https://cred.club/careers/901",
        source="linkedin",
        required_yoe=3,  # >= 2 YoE stretch!
    )
    dm = generate_deterministic_referral_dm(
        contact,
        job,
        ["an open-source PyPI library for diagnosing multi-agent LLM trace failures"],
        "BITS_FULL_TIME",
    )

    # Rule checks:
    # 1. Lead with fellow BITSian
    assert "fellow BITSian here" in dm
    # 2. State role & Job ID
    assert "AI Engineer" in dm
    assert "Job ID: CR-901" in dm
    # 3. Experience stretch acknowledgment
    assert "I know the experience bar is a stretch for where I'm at right now" in dm
    # 4. Plain project
    assert "open-source PyPI library for diagnosing multi-agent LLM trace failures" in dm
    # 5. Standalone portfolio link
    assert "You can see my work here: https://param-dev.vercel.app." in dm
    # 6. Referral ask & advice close
    assert "Would really appreciate a referral" in dm
    assert "advice" in dm
    # 7. No banned em dashes or exclamations
    assert "—" not in dm
    assert "--" not in dm
    assert "!" not in dm


def test_generate_deterministic_referral_dm_plain_direct_fresher():
    contact = ContactPerson(
        name="Divya M",
        headline="HR Manager at NetApp",
        linkedin_url="https://linkedin.com/in/divya",
        tier="3_RECRUITER",
        relevance_note="",
        is_bits_alum=False,
        bits_type="NONE",
    )
    job = JobPosting(
        job_id="NA-44",
        company="NetApp",
        role="Associate Software Engineer",
        location="Bengaluru",
        jd_text="Entry level fresher",
        job_url="https://netapp.com/careers/44",
        source="greenhouse",
        required_yoe=0,  # Fresher, no stretch disclaimer
    )
    dm = generate_deterministic_referral_dm(
        contact,
        job,
        ["an open-source PyPI library for diagnosing multi-agent LLM trace failures"],
        "PLAIN_DIRECT",
    )

    # Lead plainly without fake hook or BITS mention
    assert dm.startswith("Hi Divya, I'm applying for the Associate Software Engineer role at NetApp")
    assert "BITSian" not in dm
    # No stretch disclaimer since required_yoe = 0
    assert "stretch" not in dm
    # Portfolio present
    assert "You can see my work here: https://param-dev.vercel.app." in dm


# ============================================================================
# PART 4: Deterministic Post-Processor (sanitize_referral_dm - Step 6)
# ============================================================================

def test_sanitize_referral_dm_replaces_em_dashes_and_exclamations():
    raw = (
        "Hi Rohit, fellow BITSian here—applying for the AI Engineer role at Cred! "
        "I built an open-source library--it diagnoses agent failures! "
        "You can see my work here: https://param-dev.vercel.app. "
        "Would love a referral if possible!"
    )
    clean = sanitize_referral_dm(raw, first_name="Rohit")
    assert "—" not in clean
    assert "--" not in clean
    assert "!" not in clean


def test_sanitize_referral_dm_strips_thanks_for_connecting():
    raw = (
        "Hi Rohit, thanks for connecting! I am applying for the AI Engineer role at Cred. "
        "I recently built an open-source PyPI library for diagnosing multi-agent LLM trace failures. "
        "You can see my work here: https://param-dev.vercel.app. "
        "Would really appreciate a referral if you think I'm a fit."
    )
    clean = sanitize_referral_dm(raw, first_name="Rohit")
    assert "thanks for connecting" not in clean.lower()
    assert "thank you for connecting" not in clean.lower()
    assert clean.startswith("Hi Rohit, ")


def test_sanitize_referral_dm_strips_banned_ai_words():
    raw = (
        "Hi Rohit, I am applying for AI Engineer. My project aligns perfectly with your cutting-edge tech. "
        "I am passionate about this groundbreaking synergy and thrilled to build systems. "
        "You can see my work here: https://param-dev.vercel.app. "
        "Would really appreciate a referral if you think I'm a fit."
    )
    clean = sanitize_referral_dm(raw, first_name="Rohit")
    for bw in [
        "aligns perfectly",
        "cutting-edge",
        "groundbreaking",
        "passionate about",
        "synergy",
        "thrilled",
    ]:
        assert bw not in clean.lower()


def test_sanitize_referral_dm_enforces_3_to_5_sentences():
    raw = (
        "Hi Rohit, I'm applying for AI Engineer at Cred. "
        "I recently built an open-source PyPI library for diagnosing multi-agent LLM trace failures. "
        "You can see my work here: https://param-dev.vercel.app. "
        "Would really appreciate a referral if you think I'm a fit, and happy to share my resume and Job ID if helpful. "
        "Either way, would love any advice you have for someone entering this space."
    )
    clean = sanitize_referral_dm(raw, first_name="Rohit")
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean) if s.strip()]
    assert 3 <= len(sentences) <= 5
    # Single paragraph check (no newlines)
    assert "\n" not in clean


def test_sanitize_referral_dm_injects_stretch_when_missing():
    # JD requires 3 YoE, but LLM omitted stretch disclaimer
    raw = (
        "Hi Rohit, fellow BITSian here, applying for the AI Engineer role at Cred. "
        "I recently built an open-source PyPI library for diagnosing multi-agent LLM trace failures. "
        "You can see my work here: https://param-dev.vercel.app. "
        "Would really appreciate a referral if you think I'm a fit."
    )
    clean = sanitize_referral_dm(
        raw,
        first_name="Rohit",
        required_yoe=3,  # >= 2 YoE
        opener_type="BITS_FULL_TIME",
    )
    assert "stretch" in clean.lower()


# ============================================================================
# PART 5: Direct Email Draft Generation
# ============================================================================

def test_build_direct_email_draft():
    contact = ContactPerson(
        name="Vivek Sharma",
        headline="AI Lead at Cred",
        linkedin_url="https://linkedin.com/in/vivek",
        tier="2_TEAM_ENGINEER_OR_HM",
        relevance_note="",
    )
    job = JobPosting(
        job_id="CR-777",
        company="Cred",
        role="Staff AI Engineer",
        location="Bengaluru",
        jd_text="",
        job_url="https://cred.club/careers/777",
        source="lever",
    )
    referral_dm = (
        "Hi Vivek, I'm applying for the Staff AI Engineer role at Cred (Job ID: CR-777). "
        "I recently built an open-source PyPI library for diagnosing multi-agent LLM trace failures. "
        "You can see my work here: https://param-dev.vercel.app. "
        "Would really appreciate a referral if you think I'm a fit."
    )

    email = build_direct_email_draft(contact, job, referral_dm)

    assert "Subject: Referral inquiry: Staff AI Engineer (Job ID: CR-777) - Param Patel (BITS Pilani)" in email
    assert "Hi Vivek," in email
    assert "Param Patel" in email
    assert "BITS Pilani" in email
    assert PORTFOLIO_URL in email
    assert "attached my resume" in email


# ============================================================================
# PART 6: Fallback Direct Application Cover Note
# ============================================================================

def test_build_fallback_note():
    job = JobPosting(
        job_id="SW-101",
        company="Swiggy",
        role="AI Engineer",
        location="Bengaluru",
        jd_text="",
        job_url="https://swiggy.in/careers/101",
        source="linkedin",
        required_yoe=2,
    )
    intel = CompanyIntel(
        company_name="Swiggy",
        funding_or_stage="Public",
        estimated_size="5000+",
        est_entry_ai_ctc_lpa=22.0,
        passes_quality_bar=True,
        summary_2_lines="Swiggy builds food delivery and quick-commerce logistics infrastructure.",
    )
    match_result = MatchAndTailorResult(
        match_score=90,
        selected_project_id="agent_diagnostician",
        winning_hook_sentence="Built an open-source PyPI library for agent debugging.",
        missing_keywords=[],
    )

    note = _build_fallback_note(job, intel, match_result)
    assert "Hi Swiggy hiring team" in note
    assert "Param Patel, a 2027 graduate from BITS Pilani" in note
    assert "AI Engineer" in note
    assert "Job ID: SW-101" in note
    assert "stretch" in note.lower()
    assert PORTFOLIO_URL in note


# ============================================================================
# PART 7: Full generate_outreach_for_job Integration
# ============================================================================

@patch("src.nodes.drafter.invoke_structured_llm")
def test_generate_outreach_for_job_sets_blank_connection_strategy(mock_llm):
    mock_llm.return_value = OutreachPackage(
        contact_name="Anand Kumar",
        contact_tier="1_ALUMNI",
        linkedin_url="https://linkedin.com/in/anand",
        connection_note_300_chars="",
        full_dm_under_95_words=(
            "Hi Anand, fellow BITSian here, applying for the AI Engineer role at NetApp (Job ID: NA-555). "
            "I recently built an open-source PyPI library for diagnosing multi-agent LLM trace failures. "
            "You can see my work here: https://param-dev.vercel.app. "
            "Would really appreciate a referral if you think I'm a fit, and happy to share my resume and Job ID if helpful. "
            "Either way, would love any advice you have for someone entering this space."
        ),
        direct_email_draft="",
    )

    contact = ContactPerson(
        name="Anand Kumar",
        headline="AI Lead at NetApp",
        linkedin_url="https://linkedin.com/in/anand",
        tier="1_ALUMNI",
        relevance_note="BITS Pilani",
        is_bits_alum=True,
        bits_type="FULL_TIME",
    )
    job = JobPosting(
        job_id="NA-555",
        company="NetApp",
        role="AI Engineer",
        location="Bengaluru",
        jd_text="AI systems engineering",
        job_url="https://netapp.com/careers/555",
        source="linkedin",
        required_yoe=1,
    )
    intel = CompanyIntel(
        company_name="NetApp",
        funding_or_stage="Public",
        estimated_size="10000+",
        est_entry_ai_ctc_lpa=20.0,
        passes_quality_bar=True,
        summary_2_lines="Data infrastructure and cloud storage.",
    )
    match_result = MatchAndTailorResult(
        match_score=88,
        selected_project_id="agent_diagnostician",
        winning_hook_sentence="Built PyPI library for agent tracing.",
        missing_keywords=[],
    )

    packages, fallback = generate_outreach_for_job(job, intel, match_result, [contact])

    assert len(packages) == 1
    assert fallback is None
    pkg = packages[0]

    # Verify Step 1 Connection Note is set to BLANK strategy
    assert pkg.connection_note_300_chars == BLANK_CONNECTION_STRATEGY

    # Verify Step 2 Referral DM
    dm = pkg.full_dm_under_95_words
    assert "fellow BITSian here" in dm
    assert "AI Engineer" in dm
    assert PORTFOLIO_URL in dm
    assert "referral" in dm.lower()
    assert "!" not in dm
    assert "—" not in dm

    # Verify Direct Email Draft
    assert pkg.direct_email_draft != ""
    assert "Referral inquiry: AI Engineer (Job ID: NA-555)" in pkg.direct_email_draft
