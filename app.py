"""
JobHunt OS — Linear & Notion-Style High-Velocity Triage Dashboard.

Design Principles:
  - Zero "AI Slop": No dark mode neon glows, no cartoon gradients, zero emojis.
  - Warm Paper & Ink Aesthetic: Alabaster (#F7F7F5) background, crisp borders (#E6E6E2), dark ink text (#111827).
  - Single-Card Flashcard Focus Mode: Constrained 960px width for distraction-free triage.
  - 3 Core Views:
      1. Triage Queue (One card at a time, high velocity, 1-click copy).
      2. Application Tracker (Exact 8-column interactive spreadsheet with inline editing).
      3. Follow-Ups (48-hour overdue referral bumps).
  - Streamlit 2026 Compliance: Uses width="stretch", zero deprecation warnings, wrap_lines=True on code blocks.
"""

import json
from datetime import datetime
from typing import List, Dict, Any, Optional

import streamlit as st
import pandas as pd

from src.db import (
    init_db,
    get_dashboard_stats,
    get_overdue_followups,
    load_jobs_dataframe,
    update_job_status_and_notes,
    update_single_job_status,
    VALID_STATUSES,
)
from src.graph import run_daily_pipeline

# -----------------------------------------------------------------------------
# Page Configuration
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="JobHunt OS",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
)

# -----------------------------------------------------------------------------
# Warm Paper & Ink Minimalist CSS (Strict Light Mode Enforcement)
# -----------------------------------------------------------------------------
st.markdown(
    """
    <style>
    /* Hide Streamlit Top Header & Menu */
    header[data-testid="stHeader"] {
        display: none !important;
    }
    #MainMenu {
        visibility: hidden !important;
    }
    footer {
        visibility: hidden !important;
    }

    /* Alabaster Warm Paper Canvas */
    .stApp {
        background-color: #F7F7F5 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
        color: #111827 !important;
    }

    /* Constrain main block to 960px focus container */
    .block-container {
        max-width: 960px !important;
        padding-top: 1.5rem !important;
        padding-bottom: 2.5rem !important;
        margin: 0 auto !important;
    }

    /* Top Identity Header */
    .app-header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        border-bottom: 1px solid #E6E6E2;
        padding-bottom: 0.85rem;
        margin-bottom: 1.25rem;
    }
    .app-title {
        font-size: 1.35rem;
        font-weight: 700;
        letter-spacing: -0.025em;
        color: #111827;
        margin: 0;
    }
    .app-stats {
        font-size: 0.82rem;
        color: #71717A;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }

    /* Clean Flashcard Surface */
    .flashcard {
        background: #FFFFFF;
        border: 1px solid #E6E6E2;
        border-radius: 8px;
        padding: 1.5rem 1.75rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
        margin-top: 0.75rem;
        margin-bottom: 1.25rem;
    }

    /* Typography & Hierarchy */
    .role-title {
        font-size: 1.45rem;
        font-weight: 700;
        letter-spacing: -0.02em;
        color: #111827;
        margin: 0;
        line-height: 1.25;
    }
    .company-name {
        font-weight: 600;
        color: #111827;
    }
    .role-subtitle {
        font-size: 0.86rem;
        color: #71717A;
        margin-top: 0.35rem;
        margin-bottom: 0.85rem;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    .section-heading {
        font-size: 0.82rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #475569;
        margin-bottom: 0.45rem;
    }
    .overview-text {
        font-size: 0.90rem;
        color: #334155;
        line-height: 1.55;
        margin-bottom: 0.65rem;
    }
    .hr-email-badge {
        font-size: 0.82rem;
        color: #0F172A;
        background: #F1F5F9;
        padding: 0.25rem 0.6rem;
        border-radius: 4px;
        display: inline-block;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        border: 1px solid #E2E8F0;
    }

    /* Match Pill */
    .match-pill {
        display: inline-block;
        font-size: 0.78rem;
        font-weight: 700;
        padding: 0.2rem 0.65rem;
        border-radius: 9999px;
        background: #ECFDF5;
        color: #065F46;
        border: 1px solid #A7F3D0;
        font-family: ui-monospace, SFMono-Regular, monospace;
    }

    /* Pitch Quote Box */
    .pitch-quote-box {
        background: #FBFBFA;
        border: 1px solid #E6E6E2;
        border-left: 3.5px solid #0F172A;
        border-radius: 6px;
        padding: 0.85rem 1.1rem;
        margin: 1.1rem 0;
    }
    .pitch-label {
        font-size: 0.72rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #0F172A;
        margin-bottom: 0.25rem;
        font-family: ui-monospace, monospace;
    }
    .pitch-text {
        font-size: 0.92rem;
        color: #1F2937;
        line-height: 1.5;
    }

    /* Contact Subheaders & Boxes */
    .contact-title {
        font-size: 0.88rem;
        font-weight: 700;
        color: #111827;
        margin-bottom: 0.15rem;
    }
    .contact-meta {
        font-size: 0.78rem;
        color: #71717A;
        margin-bottom: 0.5rem;
        line-height: 1.35;
    }
    .step-box-header {
        font-size: 0.72rem;
        font-weight: 700;
        color: #334155;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-top: 0.75rem;
        margin-bottom: 0.25rem;
        font-family: ui-monospace, monospace;
    }

    /* Inbox Zero Empty State */
    .inbox-zero {
        background: #FFFFFF;
        border: 1px dashed #D4D4D8;
        border-radius: 8px;
        padding: 3rem 2rem;
        text-align: center;
        margin: 2rem 0;
    }
    .inbox-zero-title {
        font-size: 1.25rem;
        font-weight: 700;
        color: #18181B;
        margin-bottom: 0.5rem;
    }
    .inbox-zero-subtitle {
        font-size: 0.9rem;
        color: #71717A;
        max-width: 440px;
        margin: 0 auto 1.5rem auto;
        line-height: 1.5;
    }

    /* Explicit Button Styles to Prevent Dark-Mode Contrast Bugs */
    .stButton > button {
        background-color: #FFFFFF !important;
        color: #0F172A !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 6px !important;
        font-weight: 500 !important;
        font-size: 0.85rem !important;
        transition: all 0.15s ease-in-out !important;
    }
    .stButton > button:hover {
        background-color: #F8FAFC !important;
        border-color: #94A3B8 !important;
        color: #0F172A !important;
    }
    .stButton > button[kind="primary"], .stButton > button[data-testid="baseButton-primary"] {
        background-color: #0F172A !important;
        color: #FFFFFF !important;
        border: 1px solid #0F172A !important;
        font-weight: 600 !important;
    }
    .stButton > button[kind="primary"]:hover, .stButton > button[data-testid="baseButton-primary"]:hover {
        background-color: #1E293B !important;
        border-color: #1E293B !important;
        color: #FFFFFF !important;
    }
    .stLinkButton > a {
        background-color: #FFFFFF !important;
        color: #0F172A !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 6px !important;
        font-weight: 500 !important;
        font-size: 0.85rem !important;
        text-decoration: none !important;
    }
    .stLinkButton > a:hover {
        background-color: #F8FAFC !important;
        border-color: #94A3B8 !important;
        color: #0F172A !important;
    }

    /* Expander Styling */
    [data-testid="stExpander"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E6E6E2 !important;
        border-radius: 6px !important;
        margin-top: 0.5rem !important;
    }
    [data-testid="stExpander"] details summary {
        color: #0F172A !important;
        font-weight: 600 !important;
    }

    /* Code Block Contrast Fix */
    [data-testid="stCodeBlock"] {
        background-color: #F8FAFC !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 6px !important;
    }
    [data-testid="stCodeBlock"] code {
        color: #0F172A !important;
        font-size: 0.85rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------
def parse_json_safely(val: Any) -> Any:
    """Safely decodes JSON or returns default empty structure."""
    if isinstance(val, (list, dict)):
        return val
    if not val or not isinstance(val, str):
        return []
    try:
        return json.loads(val)
    except Exception:
        return []


def format_contact_tier(tier: str) -> str:
    """Formats contact tier for clear human readability."""
    if "1_ALUMNI" in tier:
        return "BITS Alum"
    if "2_TEAM" in tier:
        return "Team Engineer / HM"
    if "3_RECRUITER" in tier:
        return "Recruiter"
    return "Contact"


# -----------------------------------------------------------------------------
# Header Navigation & Metric Bar
# -----------------------------------------------------------------------------
def render_header():
    """Renders sleek top control header with live counts and pipeline trigger."""
    init_db()
    stats = get_dashboard_stats()

    c_left, c_right = st.columns([3.2, 1.2])

    with c_left:
        st.markdown(
            f"""
            <div class="app-header">
                <div>
                    <span class="app-title">JobHunt OS</span>
                    <span style="margin-left: 0.75rem;" class="app-stats">
                        <b>{stats.get('total_new', 0)}</b> NEW to triage &nbsp;·&nbsp; 
                        <b>{stats.get('pipeline_active', 0)}</b> active &nbsp;·&nbsp; 
                        <b>{stats.get('referrals_asked', 0)}</b> referrals &nbsp;·&nbsp; 
                        <b>{stats.get('interviews', 0)}</b> interviews
                    </span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c_right:
        if st.button("Fetch New Jobs", width="stretch", help="Run ingestion & enrichment pipeline"):
            with st.spinner("Scraping and analyzing job boards..."):
                run_daily_pipeline()
            st.toast("Pipeline run complete! Refreshed jobs.")
            st.rerun()

    # View Switcher
    views = ["Triage Queue", "Application Tracker", "Follow-Ups"]
    if hasattr(st, "segmented_control"):
        selected_view = st.segmented_control(
            "Navigation",
            views,
            default="Triage Queue",
            label_visibility="collapsed",
        )
    else:
        selected_view = st.radio(
            "Navigation",
            views,
            horizontal=True,
            label_visibility="collapsed",
        )

    return selected_view or "Triage Queue"


# -----------------------------------------------------------------------------
# View 1: Triage Queue (Single-Card "Flashcard Focus Mode")
# -----------------------------------------------------------------------------
def render_triage_queue():
    """Renders the high-velocity single-card flashcard triage workspace."""
    df_new = load_jobs_dataframe(status_filter="NEW")
    new_jobs = df_new.to_dict(orient="records")
    total_jobs = len(new_jobs)

    if total_jobs == 0:
        st.markdown(
            """
            <div class="inbox-zero">
                <div class="inbox-zero-title">Inbox Zero</div>
                <div class="inbox-zero-subtitle">
                    All new postings have been reviewed. Track active applications in the Tracker
                    or click "Fetch New Jobs" above to scrape fresh roles.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # Initialize / clamp session state index
    if "triage_idx" not in st.session_state:
        st.session_state.triage_idx = 0
    if st.session_state.triage_idx >= total_jobs:
        st.session_state.triage_idx = max(0, total_jobs - 1)
    if st.session_state.triage_idx < 0:
        st.session_state.triage_idx = 0

    idx = st.session_state.triage_idx
    job = new_jobs[idx]

    # --- Stepper Navigation Bar ---
    step_col1, step_col2, step_col3 = st.columns([1, 4.5, 1])
    with step_col1:
        if st.button("Previous", width="stretch", disabled=(idx == 0)):
            st.session_state.triage_idx = max(0, idx - 1)
            st.rerun()

    with step_col2:
        options = [
            f"Job {i+1} of {total_jobs}: {j['company']} — {j['role']}"
            for i, j in enumerate(new_jobs)
        ]
        selected_option = st.selectbox(
            "Select Job",
            options=options,
            index=idx,
            label_visibility="collapsed",
        )
        selected_idx = options.index(selected_option)
        if selected_idx != idx:
            st.session_state.triage_idx = selected_idx
            st.rerun()

    with step_col3:
        if st.button("Next", width="stretch", disabled=(idx == total_jobs - 1)):
            st.session_state.triage_idx = min(total_jobs - 1, idx + 1)
            st.rerun()

    # --- Main Flashcard Surface ---
    st.markdown('<div class="flashcard">', unsafe_allow_html=True)

    # 1. Action Bar directly at top of card (Zero empty white box above it)
    contacts = parse_json_safely(job.get("contacts_json"))
    referrer_names_default = ", ".join(c.get("name", "") for c in contacts if c.get("name")) if contacts else ""

    act1, act2, act3, act4 = st.columns([1.8, 1.6, 1.1, 1.4])
    with act1:
        if st.button("🔗 Connection Request Sent", width="stretch", type="primary"):
            ref_name_to_save = job.get("referrer_name") or referrer_names_default
            update_single_job_status(
                job_id=job["job_id"],
                new_status="CONNECT_SENT",
                referrer_name=ref_name_to_save,
            )
            st.toast(f"Connection request logged for {job['company']}.")
            st.rerun()
    with act2:
        if st.button("↗ Applied Direct (No Referral)", width="stretch"):
            update_single_job_status(job["job_id"], "APPLIED_DIRECT")
            st.toast(f"Marked applied direct for {job['company']}.")
            st.rerun()
    with act3:
        if st.button("✕ Skip Role", width="stretch"):
            update_single_job_status(job["job_id"], "SKIPPED")
            st.toast(f"Skipped {job['company']}.")
            st.rerun()
    with act4:
        st.link_button("Open Job Posting", job["job_url"], width="stretch")

    st.markdown("<hr style='border: none; border-top: 1px solid #F0F0EE; margin: 1.1rem 0;'>", unsafe_allow_html=True)

    # 2. Header & Clean Typographic Subtitle
    h_left, h_right = st.columns([4, 1.2])
    with h_left:
        st.markdown(
            f"""
            <div class="role-title">
                {job['role']} <span style="font-weight: 400; color: #71717A;">at</span> <span class="company-name">{job['company']}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with h_right:
        score = job.get("match_score", 0)
        st.markdown(
            f"""
            <div style="text-align: right;">
                <span class="match-pill">{score}% Match</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    loc = job.get("location") or "Remote / Hybrid"
    stage = job.get("company_stage") or "Growth"
    ctc = f"Est. ~{job['est_ctc_lpa']} LPA" if job.get("est_ctc_lpa") else "Competitive CTC"
    source = job.get("source") or "Direct"
    st.markdown(
        f'<div class="role-subtitle">{loc} &nbsp;·&nbsp; {stage} &nbsp;·&nbsp; {ctc} &nbsp;·&nbsp; via {source}</div>',
        unsafe_allow_html=True,
    )

    # 3. Company & JD Breakdown (2-Column Layout)
    col_comp, col_jd = st.columns(2)
    with col_comp:
        st.markdown('<div class="section-heading">Company Overview</div>', unsafe_allow_html=True)
        summary = job.get("company_summary") or f"{job['company']} builds modern software and engineering products."
        st.markdown(f'<div class="overview-text">{summary}</div>', unsafe_allow_html=True)
        hr_email_val = job.get("hr_email") or f"careers@{job['company'].lower().replace(' ', '')}.com (pattern)"
        st.markdown(
            f'<div class="hr-email-badge">HR / Recruiting Email: <b>{hr_email_val}</b></div>',
            unsafe_allow_html=True,
        )

    with col_jd:
        st.markdown('<div class="section-heading">Role Requirements Summary</div>', unsafe_allow_html=True)
        jd_bullets = parse_json_safely(job.get("jd_summary_json"))
        if jd_bullets:
            for b in jd_bullets[:5]:
                st.markdown(f"<div style='font-size: 0.88rem; color: #334155; margin-bottom: 0.3rem;'>• {b}</div>", unsafe_allow_html=True)
        else:
            st.markdown(
                f"<div style='font-size: 0.88rem; color: #475569;'>• Builds core machine learning and LLM infrastructure.<br>"
                f"• Collaborates with engineering team on high-reliability features.<br>"
                f"• Requires hands-on Python/AI development experience.</div>",
                unsafe_allow_html=True,
            )

    # 4. Specific Project Fit Callout
    project_id = job.get("selected_project") or "Portfolio Arsenal"
    hook = job.get("winning_hook") or "Candidate portfolio demonstrates production-grade engineering alignment with this role."
    st.markdown(
        f"""
        <div class="pitch-quote-box">
            <div class="pitch-label">Selected Project Fit: {project_id.upper()}</div>
            <div class="pitch-text">{hook}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 5. Side-by-Side Outreach Contacts (Two-Stage Human Networking)
    drafts = parse_json_safely(job.get("outreach_drafts_json"))
    fallback_note = job.get("fallback_note")

    col_c1, col_c2 = st.columns(2)

    # Contact 1
    with col_c1:
        if contacts and len(contacts) > 0:
            c1 = contacts[0]
            d1 = drafts[0] if drafts and len(drafts) > 0 else {}
            tier_badge = format_contact_tier(c1.get("tier", ""))
            st.markdown(
                f"""
                <div class="contact-title">Contact 1: {c1.get('name', 'Team Member')}</div>
                <div class="contact-meta">{tier_badge} &nbsp;·&nbsp; {c1.get('headline', '')}</div>
                """,
                unsafe_allow_html=True,
            )
            if c1.get("linkedin_url"):
                st.link_button(f"Open LinkedIn Profile ({c1.get('name')})", c1.get("linkedin_url"), width="stretch")

            st.markdown('<div class="step-box-header">STEP 1: Connection Request Note (Mentor/Advice Frame — ≤ 190 chars)</div>', unsafe_allow_html=True)
            note1 = d1.get("connection_note_300_chars", f"Hi {c1.get('name', '').split()[0]}, fellow BITSian here. Would love to connect and learn about your work at {job['company']}!")
            st.code(note1, language=None, wrap_lines=True)

            st.markdown('<div class="step-box-header">STEP 2: Post-Connection DM (Plain English Proof + Low-Hassle Referral Ask — ≤ 85 words)</div>', unsafe_allow_html=True)
            dm1 = d1.get("full_dm_under_95_words", f"Hi {c1.get('name', '').split()[0]}, thanks for connecting! I'm applying for {job['role']} at {job['company']}. My work: https://parampatel-ai.vercel.app")
            st.code(dm1, language=None, wrap_lines=True)
        elif fallback_note:
            st.markdown('<div class="contact-title">Direct Application Cover Note</div>', unsafe_allow_html=True)
            st.markdown('<div class="contact-meta">Zero verified alumni found — use this tailor-fit note in application cover note</div>', unsafe_allow_html=True)
            st.code(fallback_note, language=None, wrap_lines=True)

    # Contact 2 or Fallback
    with col_c2:
        if contacts and len(contacts) > 1:
            c2 = contacts[1]
            d2 = drafts[1] if drafts and len(drafts) > 1 else {}
            tier_badge = format_contact_tier(c2.get("tier", ""))
            st.markdown(
                f"""
                <div class="contact-title">Contact 2: {c2.get('name', 'Team Member')}</div>
                <div class="contact-meta">{tier_badge} &nbsp;·&nbsp; {c2.get('headline', '')}</div>
                """,
                unsafe_allow_html=True,
            )
            if c2.get("linkedin_url"):
                st.link_button(f"Open LinkedIn Profile ({c2.get('name')})", c2.get("linkedin_url"), width="stretch")

            st.markdown('<div class="step-box-header">STEP 1: Connection Request Note (Mentor/Advice Frame — ≤ 190 chars)</div>', unsafe_allow_html=True)
            note2 = d2.get("connection_note_300_chars", f"Hi {c2.get('name', '').split()[0]}, came across your work at {job['company']}. Would love to connect!")
            st.code(note2, language=None, wrap_lines=True)

            st.markdown('<div class="step-box-header">STEP 2: Post-Connection DM (Plain English Proof + Low-Hassle Referral Ask — ≤ 85 words)</div>', unsafe_allow_html=True)
            dm2 = d2.get("full_dm_under_95_words", f"Hi {c2.get('name', '').split()[0]}, thanks for connecting! Applying for {job['role']} at {job['company']}. My work: https://parampatel-ai.vercel.app")
            st.code(dm2, language=None, wrap_lines=True)
        elif contacts and len(contacts) == 1 and fallback_note:
            st.markdown('<div class="contact-title">Direct Application Cover Note</div>', unsafe_allow_html=True)
            st.markdown('<div class="contact-meta">Alternative direct apply note for ATS cover letter</div>', unsafe_allow_html=True)
            st.code(fallback_note, language=None, wrap_lines=True)
        elif not contacts and not fallback_note:
            st.markdown('<div class="contact-title">Direct Application Cover Note</div>', unsafe_allow_html=True)
            fallback_gen = f"Hi {job['company']} team, I am applying for the {job['role']} role. My portfolio highlights production AI/ML systems: https://parampatel-ai.vercel.app"
            st.code(fallback_gen, language=None, wrap_lines=True)

    # 6. Progressive Disclosure Expanders
    st.markdown("<div style='margin-top: 1.25rem;'></div>", unsafe_allow_html=True)

    with st.expander("Copy-Paste Resume Bullets & Missing Keywords"):
        tweaks = parse_json_safely(job.get("resume_tweaks_json"))
        missing = parse_json_safely(job.get("missing_keywords_json"))

        col_t1, col_t2 = st.columns([1.5, 1])
        with col_t1:
            st.markdown("<b>Ready-to-Paste Resume Lines:</b>", unsafe_allow_html=True)
            if tweaks:
                for b in tweaks:
                    st.markdown(f"• {b}")
            else:
                st.caption("Standard profile bullets match JD requirements cleanly.")

        with col_t2:
            st.markdown("<b>ATS Missing Keywords:</b>", unsafe_allow_html=True)
            if missing:
                st.markdown(", ".join(f"`{k}`" for k in missing))
            else:
                st.caption("No significant keywords missing.")

    with st.expander("Read Full Raw Job Description"):
        raw_jd = job.get("jd_text") or "No raw JD text available for this role."
        st.text_area("Full Job Description", value=raw_jd, height=320, disabled=True)

    st.markdown('</div>', unsafe_allow_html=True)  # Close flashcard


# -----------------------------------------------------------------------------
# View 2: Application Tracker (Exact 8-Column Excel Spreadsheet Replacement)
# -----------------------------------------------------------------------------
def render_application_tracker():
    """Renders exact 8-column interactive spreadsheet with inline status, hr_email, and referrer editing."""
    st.markdown("### Application Tracker")

    # Workflow Instruction Callout
    st.markdown(
        """
        <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-left: 3.5px solid #0F172A; padding: 0.75rem 1rem; border-radius: 6px; font-size: 0.85rem; color: #334155; margin-bottom: 1rem; line-height: 1.5;">
            <b>Workflow:</b> After they accept your connection on LinkedIn, send the Full DM and change status to <code>ASKED_REFERRAL</code>. Once you submit the application, change to <code>APPLIED_VIA_REFERRAL</code>.
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_filter, col_spacer = st.columns([2, 3])
    with col_filter:
        status_options = ["ALL"] + VALID_STATUSES
        selected_filter = st.selectbox("Filter by Stage", options=status_options, index=0)

    df = load_jobs_dataframe(status_filter=selected_filter)

    if df.empty:
        st.info(f"No applications found for stage '{selected_filter}'.")
        return

    # Exact 8 columns in requested order: Company, Role, Est. CTC, HR Email, Referrer, Stage, Sent Date, Notes
    columns_in_order = [
        "company",
        "role",
        "est_ctc_lpa",
        "hr_email",
        "referrer_name",
        "status",
        "outreach_sent_at",
        "notes",
    ]

    # Keep job_id for database updates
    edit_df = df[["job_id"] + columns_in_order].copy()

    # Format outreach_sent_at as a clean Date/Time string
    if "outreach_sent_at" in edit_df.columns:
        edit_df["outreach_sent_at"] = edit_df["outreach_sent_at"].apply(
            lambda x: str(x)[:16] if pd.notnull(x) and str(x).strip() not in ("", "None") else "—"
        )

    col_config = {
        "job_id": None,  # Hidden from view
        "company": st.column_config.TextColumn("Company", disabled=True, width="medium"),
        "role": st.column_config.TextColumn("Role", disabled=True, width="medium"),
        "est_ctc_lpa": st.column_config.NumberColumn("Est. CTC", format="%.1f LPA", disabled=True, width="small"),
        "hr_email": st.column_config.TextColumn("HR Email", width="medium"),
        "referrer_name": st.column_config.TextColumn("Referrer", width="medium"),
        "status": st.column_config.SelectboxColumn("Stage", options=VALID_STATUSES, required=True, width="medium"),
        "outreach_sent_at": st.column_config.TextColumn("Sent Date", disabled=True, width="small"),
        "notes": st.column_config.TextColumn("Notes", width="large"),
    }

    edited_df = st.data_editor(
        edit_df,
        column_config=col_config,
        disabled=["company", "role", "est_ctc_lpa", "outreach_sent_at"],
        hide_index=True,
        width="stretch",
        key="tracker_data_editor_8col",
    )

    st.markdown("<div style='margin-top: 0.85rem;'></div>", unsafe_allow_html=True)
    c1, c2 = st.columns([1.5, 1.5])

    with c1:
        if st.button("Save Tracker Changes", width="stretch", type="primary"):
            updated_count = update_job_status_and_notes(edited_df)
            st.toast(f"Successfully saved {updated_count} record updates!")
            st.rerun()

    with c2:
        csv_data = df.to_csv(index=False)
        st.download_button(
            "Export Tracker to CSV",
            data=csv_data,
            file_name=f"jobhunt_tracker_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            width="stretch",
        )


# -----------------------------------------------------------------------------
# View 3: Follow-Ups (>48h Referral Bump Queue)
# -----------------------------------------------------------------------------
def render_follow_ups():
    """Renders the dedicated 48-hour follow-up queue with ready-to-copy bump notes."""
    st.markdown("### Referral Follow-Up Queue")
    st.markdown(
        "<p style='color: #71717A; font-size: 0.9rem;'>Alerts for jobs where referral was asked (<code>ASKED_REFERRAL</code>) ≥ 48 hours ago without updates. Send a polite 25-word bump. (Note: Jobs in <code>CONNECT_SENT</code> do not trigger follow-ups until connection is accepted and referral is asked).</p>",
        unsafe_allow_html=True,
    )

    overdue_jobs = get_overdue_followups(days=2)

    if not overdue_jobs:
        st.markdown(
            """
            <div class="inbox-zero">
                <div class="inbox-zero-title">All Caught Up</div>
                <div class="inbox-zero-subtitle">
                    No referrals are pending follow-up (>48 hours). When you change a job stage to
                    "ASKED_REFERRAL" in the Tracker, it will automatically appear here if awaiting a response for 48 hours.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown(f"<b>{len(overdue_jobs)} follow-ups due today:</b>", unsafe_allow_html=True)

    for job in overdue_jobs:
        contacts = job.get("contacts", [])
        c_name = contacts[0].get("name", "there") if contacts else (job.get("referrer_name") or "there")
        sent_at = str(job.get("outreach_sent_at", ""))[:16]

        st.markdown('<div class="flashcard">', unsafe_allow_html=True)
        f_top1, f_top2 = st.columns([3.5, 1.5])
        with f_top1:
            st.markdown(
                f"""
                <div class="contact-title">{job['role']} at {job['company']}</div>
                <div class="contact-meta">Referral asked to <b>{c_name}</b> on {sent_at}</div>
                """,
                unsafe_allow_html=True,
            )
        with f_top2:
            st.link_button("View Job Posting", job["job_url"], width="stretch")

        bump_message = (
            f"Hi {c_name}, hope you're having a great week! Following up briefly on my note "
            f"regarding the {job['role']} role at {job['company']} — would love to connect "
            f"when you have a moment: https://parampatel-ai.vercel.app"
        )

        st.markdown('<div class="step-box-header">Polite Follow-Up Bump (1-Click Copy)</div>', unsafe_allow_html=True)
        st.code(bump_message, language=None, wrap_lines=True)

        b_c1, b_c2, b_c3 = st.columns([1.5, 1.7, 1.5])
        with b_c1:
            if st.button("Follow-Up Sent", key=f"bump_{job['job_id']}", width="stretch"):
                update_single_job_status(job["job_id"], "ASKED_REFERRAL")
                st.toast(f"Follow-up recorded for {job['company']}. 48h clock reset.")
                st.rerun()
        with b_c2:
            if st.button("Move to Applied (Referral)", key=f"adv_{job['job_id']}", width="stretch"):
                update_single_job_status(job["job_id"], "APPLIED_VIA_REFERRAL")
                st.toast(f"Moved {job['company']} to APPLIED_VIA_REFERRAL.")
                st.rerun()
        with b_c3:
            if st.button("Mark No Response", key=f"skip_{job['job_id']}", width="stretch"):
                update_single_job_status(job["job_id"], "SKIPPED")
                st.toast(f"Closed follow-up for {job['company']}.")
                st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Main Application Entrypoint
# -----------------------------------------------------------------------------
def main():
    view = render_header()

    if view == "Triage Queue":
        render_triage_queue()
    elif view == "Application Tracker":
        render_application_tracker()
    elif view == "Follow-Ups":
        render_follow_ups()


if __name__ == "__main__":
    main()
