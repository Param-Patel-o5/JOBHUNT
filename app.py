"""
JobHunt OS — Linear & Notion-Style High-Velocity Triage & Referral Tracking Dashboard.

Design Principles:
  - Zero "AI Slop": Clean typography, high contrast, warm paper alabaster aesthetic (#F7F7F5).
  - 4 Dedicated Workflow Tabs + Full Spreadsheet Tracker:
      Tab 1: 🔥 Today's Referral Asks (CONNECTED_READY_TO_ASK & CONNECT_SENT).
      Tab 2: 🆕 New High-Match Jobs (≥ 75%) with 1-click blank invites and copyable DMs.
      Tab 3: 🏆 Active Referrals (REFERRAL_ASKED & REFERRED_APPLIED - protected state).
      Tab 4: 💤 Stale / Direct Email Fallback (STALE_NO_RESPONSE - Hunter.io email fallback).
      Tab 5: 📊 Full Application Tracker & Excel-friendly CSV export.
  - Streamlit 2026 Compliance: Uses width="stretch", zero deprecation warnings, wrap_lines=True on code blocks.
"""

import json
from datetime import datetime
from typing import List, Dict, Any, Optional

import streamlit as st
import pandas as pd

from src.db import (
    init_db,
    auto_transition_stale_connections,
    get_dashboard_stats,
    get_overdue_followups,
    load_jobs_dataframe,
    update_job_status_and_notes,
    update_single_job_status,
    VALID_STATUSES,
)
from src.graph import run_daily_pipeline

PORTFOLIO_URL = "https://param-dev.vercel.app"

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

    /* Constrain main block to 980px focus container */
    .block-container {
        max-width: 980px !important;
        padding-top: 1.25rem !important;
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
        margin-bottom: 1.0rem;
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
        padding: 1.35rem 1.65rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
        margin-top: 0.75rem;
        margin-bottom: 1.15rem;
    }

    /* Typography & Hierarchy */
    .role-title {
        font-size: 1.35rem;
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
        font-size: 0.80rem;
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
        margin: 0.9rem 0;
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

    /* Contact Subheaders & Badges */
    .contact-title {
        font-size: 0.92rem;
        font-weight: 700;
        color: #111827;
        margin-bottom: 0.2rem;
    }
    .contact-meta {
        font-size: 0.82rem;
        color: #64748B;
        margin-bottom: 0.5rem;
        line-height: 1.4;
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

    /* Verified Signal Badges */
    .badge-bits {
        background: #EFF6FF !important;
        color: #1D4ED8 !important;
        border: 1px solid #BFDBFE !important;
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        padding: 0.15rem 0.5rem !important;
        border-radius: 4px !important;
        display: inline-block !important;
        margin-right: 0.25rem !important;
    }
    .badge-wilp {
        background: #F3E8FF !important;
        color: #7E22CE !important;
        border: 1px solid #E9D5FF !important;
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        padding: 0.15rem 0.5rem !important;
        border-radius: 4px !important;
        display: inline-block !important;
        margin-right: 0.25rem !important;
    }
    .badge-aiml {
        background: #ECFDF5 !important;
        color: #047857 !important;
        border: 1px solid #A7F3D0 !important;
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        padding: 0.15rem 0.5rem !important;
        border-radius: 4px !important;
        display: inline-block !important;
        margin-right: 0.25rem !important;
    }
    .badge-senior {
        background: #FEF3C7 !important;
        color: #B45309 !important;
        border: 1px solid #FDE68A !important;
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        padding: 0.15rem 0.5rem !important;
        border-radius: 4px !important;
        display: inline-block !important;
        margin-right: 0.25rem !important;
    }
    .badge-mid {
        background: #F1F5F9 !important;
        color: #334155 !important;
        border: 1px solid #CBD5E1 !important;
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        padding: 0.15rem 0.5rem !important;
        border-radius: 4px !important;
        display: inline-block !important;
        margin-right: 0.25rem !important;
    }
    .badge-junior {
        background: #F8FAFC !important;
        color: #475569 !important;
        border: 1px solid #E2E8F0 !important;
        font-size: 0.75rem !important;
        font-weight: 500 !important;
        padding: 0.15rem 0.5rem !important;
        border-radius: 4px !important;
        display: inline-block !important;
        margin-right: 0.25rem !important;
    }
    .badge-mutual {
        background: #F0FDF4 !important;
        color: #166534 !important;
        border: 1px solid #BBF7D0 !important;
        font-size: 0.75rem !important;
        font-weight: 500 !important;
        padding: 0.15rem 0.5rem !important;
        border-radius: 4px !important;
        display: inline-block !important;
        margin-right: 0.25rem !important;
    }
    .badge-email {
        background: #F8FAFC !important;
        color: #0F172A !important;
        border: 1px solid #E2E8F0 !important;
        font-size: 0.76rem !important;
        font-family: ui-monospace, SFMono-Regular, monospace !important;
        padding: 0.15rem 0.5rem !important;
        border-radius: 4px !important;
        display: inline-block !important;
    }

    /* Lifecycle Status Banners */
    .status-banner-ready {
        background: #FEF08A;
        color: #854D0E;
        border: 1px solid #FACC15;
        font-weight: 700;
        font-size: 0.84rem;
        padding: 0.45rem 0.85rem;
        border-radius: 6px;
        margin-bottom: 0.75rem;
        display: inline-block;
    }
    .status-banner-sent {
        background: #F1F5F9;
        color: #475569;
        border: 1px solid #CBD5E1;
        font-size: 0.82rem;
        padding: 0.4rem 0.75rem;
        border-radius: 6px;
        margin-bottom: 0.75rem;
        display: inline-block;
    }
    .status-banner-stale {
        background: #FEF2F2;
        color: #991B1B;
        border: 1px solid #FECACA;
        font-size: 0.84rem;
        padding: 0.5rem 0.85rem;
        border-radius: 6px;
        margin-bottom: 0.85rem;
        display: inline-block;
        line-height: 1.45;
    }

    /* Inbox Zero Empty State */
    .inbox-zero {
        background: #FFFFFF;
        border: 1px dashed #D4D4D8;
        border-radius: 8px;
        padding: 2.5rem 2rem;
        text-align: center;
        margin: 1.5rem 0;
    }
    .inbox-zero-title {
        font-size: 1.20rem;
        font-weight: 700;
        color: #18181B;
        margin-bottom: 0.35rem;
    }
    .inbox-zero-subtitle {
        font-size: 0.88rem;
        color: #71717A;
        max-width: 480px;
        margin: 0 auto 1.0rem auto;
        line-height: 1.5;
    }

    /* Explicit Button Styles */
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


def format_time_ago(ts_str: Optional[str]) -> str:
    """Formats an ISO or SQLite timestamp into human-readable relative time."""
    if not ts_str or str(ts_str) in ("None", "nan", ""):
        return "recently"
    try:
        clean_ts = str(ts_str)[:19]
        dt = datetime.fromisoformat(clean_ts.replace(" ", "T"))
        diff = datetime.now() - dt
        days = diff.days
        if days == 0:
            hours = int(diff.total_seconds() // 3600)
            if hours == 0:
                return "just now"
            return f"{hours}h ago"
        elif days == 1:
            return "yesterday"
        else:
            return f"{days} days ago"
    except Exception:
        return str(ts_str)[:10]


def format_contact_badges(c: Dict[str, Any]) -> str:
    """Renders sleek HTML badges for verified contact signals."""
    badges = []

    # 1. BITS Alumni Signal
    is_bits = c.get("is_bits_alum", False)
    bits_type = c.get("bits_type", "NONE")
    tier = c.get("tier", "")
    if is_bits or "1_ALUMNI" in tier:
        if bits_type == "FULL_TIME":
            badges.append('<span class="badge-bits">🎓 BITS Pilani (Campus)</span>')
        elif bits_type == "WILP":
            badges.append('<span class="badge-wilp">🎓 BITS WILP</span>')
        else:
            badges.append('<span class="badge-bits">🎓 BITS Pilani Alum</span>')

    # 2. Stated AI/ML Interest
    if c.get("stated_ai_ml_interest"):
        badges.append('<span class="badge-aiml">⚡ AI/ML Specialist</span>')

    # 3. Seniority Tier
    exp_level = c.get("years_experience_level", "")
    headline = c.get("headline", "")
    if exp_level == "senior" or any(kw in headline.lower() for kw in ["lead", "manager", "director", "head", "principal", "staff"]):
        badges.append('<span class="badge-senior">👑 Leadership / Senior</span>')
    elif exp_level == "mid":
        badges.append('<span class="badge-mid">⚙️ Mid-Level Tech</span>')
    elif exp_level == "junior":
        badges.append('<span class="badge-junior">🌱 Peer / Junior</span>')

    # 4. Mutual Connections
    if c.get("mutual_connections"):
        badges.append('<span class="badge-mutual">🤝 Mutual Connections</span>')

    # 5. Email Badge
    email = c.get("email") or ""
    email_status = c.get("email_status") or "PATTERN_GUESS"
    if email:
        badges.append(f'<span class="badge-email">✉️ <b>{email}</b> ({email_status})</span>')

    return " ".join(badges)


# -----------------------------------------------------------------------------
# Top Identity Header & Pipeline Trigger
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
                        <b>{stats.get('today_asks', 0)}</b> referral asks in flight &nbsp;·&nbsp; 
                        <b>{stats.get('total_new', 0)}</b> new to triage &nbsp;·&nbsp; 
                        <b>{stats.get('referrals_asked', 0)}</b> active referrals &nbsp;·&nbsp; 
                        <b>{stats.get('stale', 0)}</b> stale email fallback
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


# -----------------------------------------------------------------------------
# TAB 1: 🔥 Today's Referral Asks (CONNECTED_READY_TO_ASK & CONNECT_SENT)
# -----------------------------------------------------------------------------
def render_today_referral_asks():
    """Renders active outreach tracker: contacts awaiting acceptance or ready for referral DM today."""
    df = load_jobs_dataframe()
    if df.empty:
        st.info("No jobs in database yet.")
        return

    # Filter jobs in either CONNECTED_READY_TO_ASK or CONNECT_SENT
    df_asks = df[df["status"].isin(["CONNECTED_READY_TO_ASK", "CONNECT_SENT"])].copy()

    if df_asks.empty:
        st.markdown(
            """
            <div class="inbox-zero">
                <div class="inbox-zero-title">Zero Pending Referral Asks</div>
                <div class="inbox-zero-subtitle">
                    You have no outstanding connection invites awaiting DMs.
                    Head to Tab 2 (New High-Match Roles) to send blank invites to fresh target companies.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # Sort: CONNECTED_READY_TO_ASK on top (urgent action needed!), then by connect_sent_at
    def sort_key(row):
        is_ready = 0 if row["status"] == "CONNECTED_READY_TO_ASK" else 1
        return (is_ready, str(row.get("connect_sent_at", "")))

    rows = df_asks.to_dict(orient="records")
    rows.sort(key=sort_key)

    st.markdown(
        f"<p style='color: #64748B; font-size: 0.88rem; margin-bottom: 0.85rem;'>"
        f"<b>{len(rows)} connections in flight.</b> Check who accepted on LinkedIn, copy your 3–5 sentence Referral DM below, and mark as asked."
        f"</p>",
        unsafe_allow_html=True,
    )

    for job in rows:
        contacts = parse_json_safely(job.get("contacts_json")) or []
        drafts = parse_json_safely(job.get("outreach_drafts_json")) or []
        sent_ts = job.get("connect_sent_at") or job.get("outreach_sent_at")
        sent_ago = format_time_ago(sent_ts)
        is_ready = job["status"] == "CONNECTED_READY_TO_ASK"

        st.markdown('<div class="flashcard">', unsafe_allow_html=True)

        # Header Row
        col_h1, col_h2 = st.columns([3.8, 1.2])
        with col_h1:
            st.markdown(
                f"""
                <div class="role-title">{job['role']} <span style="font-weight: 400; color: #71717A;">at</span> <span class="company-name">{job['company']}</span></div>
                <div class="role-subtitle">📍 {job.get('location', 'India')} &nbsp;·&nbsp; Est: {job.get('est_ctc_lpa', '18')} LPA</div>
                """,
                unsafe_allow_html=True,
            )
        with col_h2:
            st.markdown(
                f"""
                <div style="text-align: right;">
                    <span class="match-pill">{job.get('match_score', 0)}% Match</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # Status Banner
        if is_ready:
            st.markdown(
                '<div class="status-banner-ready">🤝 Connection Accepted — Send Referral DM Today!</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="status-banner-sent">⏳ Blank Invite Sent ({sent_ago}) — Awaiting acceptance on LinkedIn</div>',
                unsafe_allow_html=True,
            )

        # Render Contacts with Direct DM & Email
        if contacts:
            if len(contacts) > 1:
                tabs = st.tabs([f"Contact {i+1}: {c.get('name', 'Contact')}" for i, c in enumerate(contacts)])
                for idx, tab in enumerate(tabs):
                    with tab:
                        c = contacts[idx]
                        d = drafts[idx] if idx < len(drafts) else {}
                        badges_html = format_contact_badges(c)

                        st.markdown(
                            f"""
                            <div class="contact-title">{c.get('name', 'Team Member')} &nbsp;·&nbsp; <span style="font-weight: normal; color: #64748B;">{c.get('headline', '')}</span></div>
                            <div style="margin-bottom: 0.65rem;">{badges_html}</div>
                            """,
                            unsafe_allow_html=True,
                        )
                        if c.get("linkedin_url"):
                            st.link_button(f"Open LinkedIn Profile ({c.get('name')})", c.get("linkedin_url"), width="stretch")

                        st.markdown('<div class="step-box-header">POST-CONNECTION REFERRAL DM (3–5 Sentences Honest Ask — Copy & Send)</div>', unsafe_allow_html=True)
                        dm = d.get("full_dm_under_95_words") or f"Hi {c.get('name', '').split()[0]}, I'm applying for {job['role']} at {job['company']}. You can see my work here: {PORTFOLIO_URL}."
                        st.code(dm, language=None, wrap_lines=True)

                        if d.get("direct_email_draft"):
                            with st.expander("Or send direct via Hunter.io email"):
                                st.code(d.get("direct_email_draft"), language=None, wrap_lines=True)
            else:
                c = contacts[0]
                d = drafts[0] if drafts else {}
                badges_html = format_contact_badges(c)
                st.markdown(
                    f"""
                    <div class="contact-title">{c.get('name', 'Team Member')} &nbsp;·&nbsp; <span style="font-weight: normal; color: #64748B;">{c.get('headline', '')}</span></div>
                    <div style="margin-bottom: 0.65rem;">{badges_html}</div>
                    """,
                    unsafe_allow_html=True,
                )
                if c.get("linkedin_url"):
                    st.link_button(f"Open LinkedIn Profile ({c.get('name')})", c.get("linkedin_url"), width="stretch")

                st.markdown('<div class="step-box-header">POST-CONNECTION REFERRAL DM (3–5 Sentences Honest Ask — Copy & Send)</div>', unsafe_allow_html=True)
                dm = d.get("full_dm_under_95_words") or f"Hi {c.get('name', '').split()[0]}, I'm applying for {job['role']} at {job['company']}. You can see my work here: {PORTFOLIO_URL}."
                st.code(dm, language=None, wrap_lines=True)

                if d.get("direct_email_draft"):
                    with st.expander("Or send direct via Hunter.io email"):
                        st.code(d.get("direct_email_draft"), language=None, wrap_lines=True)

        st.markdown("<hr style='border: none; border-top: 1px solid #F0F0EE; margin: 1.0rem 0 0.85rem 0;'>", unsafe_allow_html=True)

        # Lifecycle Action Controls
        act_c1, act_c2, act_c3, act_c4 = st.columns([1.6, 2.0, 1.8, 1.6])
        with act_c1:
            if not is_ready:
                if st.button("🤝 Contact Accepted", key=f"ready_{job['job_id']}", width="stretch", help="Mark that the contact accepted your LinkedIn invite"):
                    update_single_job_status(job["job_id"], "CONNECTED_READY_TO_ASK")
                    st.toast(f"{job['company']} marked as Connected (Ready to Ask)!")
                    st.rerun()
            else:
                st.caption("Awaiting your DM")

        with act_c2:
            if st.button("✅ Mark Referral Asked (DM Sent)", type="primary", key=f"asked_{job['job_id']}", width="stretch", help="Referral DM sent — moves to Active Referrals"):
                update_single_job_status(job["job_id"], "REFERRAL_ASKED")
                st.toast(f"Referral asked for {job['company']}! Moved to Tab 3.")
                st.rerun()

        with act_c3:
            if st.button("⏳ Mark Stale / Time Lost", key=f"stale_{job['job_id']}", width="stretch", help="No response on LinkedIn — move to Direct Email Fallback"):
                update_single_job_status(job["job_id"], "STALE_NO_RESPONSE")
                st.toast(f"{job['company']} moved to Stale / Email Fallback.")
                st.rerun()

        with act_c4:
            if st.button("💼 Move to Applied", key=f"app_{job['job_id']}", width="stretch"):
                update_single_job_status(job["job_id"], "REFERRED_APPLIED")
                st.toast(f"{job['company']} marked as Applied!")
                st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# TAB 2: 🆕 New High-Match Jobs (≥ 75%)
# -----------------------------------------------------------------------------
def render_triage_queue():
    """Renders single-card flashcard triage workspace for fresh, unreviewed >= 75% roles."""
    df_new = load_jobs_dataframe(status_filter="NEW")
    if df_new.empty:
        new_jobs = []
    else:
        # Enforce >= 75% match score filter
        df_filtered = df_new[df_new["match_score"] >= 75]
        new_jobs = df_filtered.to_dict(orient="records")

    total_jobs = len(new_jobs)

    if total_jobs == 0:
        st.markdown(
            """
            <div class="inbox-zero">
                <div class="inbox-zero-title">Inbox Zero (≥ 75% Match Roles)</div>
                <div class="inbox-zero-subtitle">
                    All fresh high-match roles have been reviewed. Track pending outreach in Tab 1,
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
            f"Job {i+1} of {total_jobs}: {j['company']} — {j['role']} ({j['match_score']}%)"
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

    # 1. Action Bar directly at top of card
    contacts = parse_json_safely(job.get("contacts_json")) or []
    referrer_names_default = ", ".join(c.get("name", "") for c in contacts if c.get("name")) if contacts else ""

    act1, act2, act3, act4 = st.columns([2.0, 1.8, 1.0, 1.4])
    with act1:
        if st.button("🚀 Blank Invite Sent", width="stretch", type="primary", help="Track blank LinkedIn connection request"):
            ref_name_to_save = job.get("referrer_name") or referrer_names_default
            update_single_job_status(
                job_id=job["job_id"],
                new_status="CONNECT_SENT",
                referrer_name=ref_name_to_save,
            )
            st.toast(f"Connection tracked for {job['company']}! Moved to Tab 1.")
            st.rerun()
    with act2:
        if st.button("⚡ Applied Direct", width="stretch", help="Applied directly without waiting for referral"):
            update_single_job_status(job["job_id"], "APPLIED_DIRECT")
            st.toast(f"Marked applied direct for {job['company']}.")
            st.rerun()
    with act3:
        if st.button("✕ Skip", width="stretch", help="Archive role"):
            update_single_job_status(job["job_id"], "SKIPPED")
            st.toast(f"Skipped {job['company']}.")
            st.rerun()
    with act4:
        st.link_button("View Job Posting", job["job_url"], width="stretch")

    st.markdown("<hr style='border: none; border-top: 1px solid #F0F0EE; margin: 1.0rem 0;'>", unsafe_allow_html=True)

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

    # Subtitle Meta
    loc = job.get("location") or "Bengaluru / India"
    source = (job.get("source") or "Direct").upper()
    est_ctc = job.get("est_ctc_lpa")
    ctc_text = f"Est: {est_ctc} LPA" if est_ctc else "CTC: Competitive"
    stage = job.get("company_stage") or "Growth"

    st.markdown(
        f"""
        <div class="role-subtitle">
            {ctc_text} &nbsp;·&nbsp; {loc} &nbsp;·&nbsp; {stage} &nbsp;·&nbsp; {source}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 3. Company Summary
    company_summary = job.get("company_summary")
    if company_summary:
        st.markdown(f'<div class="overview-text">{company_summary}</div>', unsafe_allow_html=True)

    # 4. Winning Pitch Hook
    winning_hook = job.get("winning_hook")
    if winning_hook:
        st.markdown(
            f"""
            <div class="pitch-quote-box">
                <div class="pitch-label">Winning Technical Hook & Alignment</div>
                <div class="pitch-text">"{winning_hook}"</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # 5. Verified Contacts (Up to 4)
    drafts = parse_json_safely(job.get("outreach_drafts_json")) or []
    fallback_note = job.get("fallback_note")

    st.markdown('<div class="section-heading" style="margin-top: 1.1rem;">Verified Target Contacts & Outreach Packages</div>', unsafe_allow_html=True)

    if contacts:
        contact_tabs = st.tabs([
            f"Contact {i+1}: {c.get('name', 'Contact')}"
            for i, c in enumerate(contacts)
        ])
        for idx, tab in enumerate(contact_tabs):
            with tab:
                c = contacts[idx]
                d = drafts[idx] if drafts and idx < len(drafts) else {}
                badges_html = format_contact_badges(c)

                st.markdown(
                    f"""
                    <div class="contact-title">{c.get('name', 'Team Member')} &nbsp;·&nbsp; <span style="font-weight: normal; color: #64748B;">{c.get('headline', '')}</span></div>
                    <div style="margin-bottom: 0.65rem;">{badges_html}</div>
                    """,
                    unsafe_allow_html=True,
                )
                if c.get("linkedin_url"):
                    st.link_button(f"Open LinkedIn Profile to Send Blank Invite ({c.get('name')})", c.get("linkedin_url"), width="stretch")

                st.markdown('<div class="step-box-header">STEP 1: Connection Strategy (Free-Tier Blank Request)</div>', unsafe_allow_html=True)
                st.caption("💡 Send blank connection request (preserves 3 free monthly notes). Once accepted, send Step 2 DM below.")

                st.markdown('<div class="step-box-header">STEP 2: Post-Connection Referral DM (3–5 Sentences Honest Referral Ask)</div>', unsafe_allow_html=True)
                dm = d.get("full_dm_under_95_words", f"Hi {c.get('name', '').split()[0]}, I'm applying for {job['role']} at {job['company']}. You can see my work here: {PORTFOLIO_URL}.")
                st.code(dm, language=None, wrap_lines=True)

                if d.get("direct_email_draft"):
                    st.markdown('<div class="step-box-header">DIRECT EMAIL: Hunter.io Referral Outreach</div>', unsafe_allow_html=True)
                    st.code(d.get("direct_email_draft"), language=None, wrap_lines=True)

    elif fallback_note:
        st.markdown('<div class="contact-title">Direct Application Cover Note</div>', unsafe_allow_html=True)
        st.caption("Zero verified alumni found — use this tailor-fit note in application cover letter field:")
        st.code(fallback_note, language=None, wrap_lines=True)

    # 6. Progressive Disclosure Expanders
    st.markdown("<div style='margin-top: 1.1rem;'></div>", unsafe_allow_html=True)

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
        st.text_area("Full Job Description", value=raw_jd, height=300, disabled=True)

    st.markdown('</div>', unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# TAB 3: 🏆 Active Referrals (REFERRAL_ASKED & REFERRED_APPLIED)
# -----------------------------------------------------------------------------
def render_active_referrals():
    """Protected tracker for active referral requests. Never overwritten by scraper runs."""
    df = load_jobs_dataframe()
    if df.empty:
        st.info("No applications in database.")
        return

    df_active = df[df["status"].isin(["REFERRAL_ASKED", "REFERRED_APPLIED", "ASKED_REFERRAL", "APPLIED_VIA_REFERRAL"])].copy()

    if df_active.empty:
        st.markdown(
            """
            <div class="inbox-zero">
                <div class="inbox-zero-title">No Active Referrals Yet</div>
                <div class="inbox-zero-subtitle">
                    Once contacts accept your connection on LinkedIn and you send the referral DM in Tab 1,
                    click "Mark Referral Asked" to track them here.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    rows = df_active.to_dict(orient="records")

    st.markdown(
        f"<p style='color: #64748B; font-size: 0.88rem; margin-bottom: 0.85rem;'>"
        f"<b>{len(rows)} active referral pipelines.</b> Protected state — these rows are permanently safeguarded against automated pipeline overwrites."
        f"</p>",
        unsafe_allow_html=True,
    )

    for job in rows:
        contacts = parse_json_safely(job.get("contacts_json")) or []
        c_name = contacts[0].get("name", "there") if contacts else (job.get("referrer_name") or "there")
        sent_ts = job.get("outreach_sent_at")
        sent_ago = format_time_ago(sent_ts)
        is_applied = job["status"] in ("REFERRED_APPLIED", "APPLIED_VIA_REFERRAL")

        st.markdown('<div class="flashcard">', unsafe_allow_html=True)

        col_t1, col_t2 = st.columns([3.8, 1.2])
        with col_t1:
            st.markdown(
                f"""
                <div class="role-title">{job['role']} <span style="font-weight: 400; color: #71717A;">at</span> <span class="company-name">{job['company']}</span></div>
                <div class="role-subtitle">Referrer: <b>{c_name}</b> &nbsp;·&nbsp; Asked: {sent_ago} &nbsp;·&nbsp; Est: {job.get('est_ctc_lpa', '18')} LPA</div>
                """,
                unsafe_allow_html=True,
            )
        with col_t2:
            st.link_button("View Job Posting", job["job_url"], width="stretch")

        # 48-Hour Overdue Follow-Up Bump Alert
        if not is_applied and sent_ts:
            try:
                clean_ts = str(sent_ts)[:19]
                dt = datetime.fromisoformat(clean_ts.replace(" ", "T"))
                hours_elapsed = (datetime.now() - dt).total_seconds() / 3600
                if hours_elapsed >= 48:
                    st.markdown(
                        f"""
                        <div style="background: #FEF3C7; border: 1px solid #FDE68A; padding: 0.6rem 0.9rem; border-radius: 6px; font-size: 0.84rem; color: #92400E; margin-bottom: 0.75rem;">
                            ⚠️ <b>48-Hour Follow-Up Due:</b> Referral asked {int(hours_elapsed)}h ago without updates. Send a polite bump below:
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    bump_message = (
                        f"Hi {c_name.split()[0]}, hope you're having a great week! Following up briefly on my note "
                        f"regarding the {job['role']} role at {job['company']} — would love to connect "
                        f"when you have a moment: {PORTFOLIO_URL}"
                    )
                    st.code(bump_message, language=None, wrap_lines=True)
                    if st.button("Follow-Up Bump Sent (Reset 48h)", key=f"bump_{job['job_id']}"):
                        update_single_job_status(job["job_id"], "REFERRAL_ASKED")
                        st.toast(f"Follow-up recorded for {job['company']}. 48h clock reset.")
                        st.rerun()
            except Exception:
                pass

        st.markdown("<hr style='border: none; border-top: 1px solid #F0F0EE; margin: 0.85rem 0 0.75rem 0;'>", unsafe_allow_html=True)

        col_act1, col_act2, col_act3, col_act4 = st.columns([2, 1.8, 1.8, 1.5])
        with col_act1:
            if not is_applied:
                if st.button("🎉 Move to Referred / Applied", type="primary", key=f"ref_app_{job['job_id']}", width="stretch"):
                    update_single_job_status(job["job_id"], "REFERRED_APPLIED")
                    st.toast(f"Moved {job['company']} to Referred / Applied!")
                    st.rerun()
            else:
                st.caption("✅ Application Submitted")

        with col_act2:
            if st.button("📅 Interview Scheduled", key=f"interview_{job['job_id']}", width="stretch"):
                update_single_job_status(job["job_id"], "INTERVIEW")
                st.toast(f"Congratulations! Moved {job['company']} to Interview.")
                st.rerun()

        with col_act3:
            if st.button("🏆 Offer Received", key=f"offer_{job['job_id']}", width="stretch"):
                update_single_job_status(job["job_id"], "OFFER")
                st.toast(f"Offer logged for {job['company']}!")
                st.rerun()

        with col_act4:
            if st.button("❌ Close / Rejected", key=f"close_{job['job_id']}", width="stretch"):
                update_single_job_status(job["job_id"], "REJECTED")
                st.toast(f"Closed referral for {job['company']}.")
                st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# TAB 4: 💤 Stale / Direct Email Fallback (STALE_NO_RESPONSE)
# -----------------------------------------------------------------------------
def render_stale_direct_email_fallback():
    """Renders contacts who sat pending on LinkedIn for >5 days with Hunter.io cold email fallback."""
    df = load_jobs_dataframe(status_filter="STALE_NO_RESPONSE")
    if df.empty:
        st.markdown(
            """
            <div class="inbox-zero">
                <div class="inbox-zero-title">Zero Stale Connections</div>
                <div class="inbox-zero-subtitle">
                    None of your pending connection invites have timed out (>5 days).
                    All active outreach is progressing on schedule.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    rows = df.to_dict(orient="records")

    st.markdown(
        """
        <div class="status-banner-stale">
            <b>💤 Stale LinkedIn Connection Fallback:</b> These contacts did not accept connection requests on LinkedIn after 5+ days.
            Rather than waiting forever, reach out directly to their verified Hunter.io email below, or archive the role.
        </div>
        """,
        unsafe_allow_html=True,
    )

    for job in rows:
        contacts = parse_json_safely(job.get("contacts_json")) or []
        drafts = parse_json_safely(job.get("outreach_drafts_json")) or []
        sent_ts = job.get("connect_sent_at") or job.get("outreach_sent_at")
        sent_ago = format_time_ago(sent_ts)

        st.markdown('<div class="flashcard">', unsafe_allow_html=True)

        col_s1, col_s2 = st.columns([3.8, 1.2])
        with col_s1:
            st.markdown(
                f"""
                <div class="role-title">{job['role']} <span style="font-weight: 400; color: #71717A;">at</span> <span class="company-name">{job['company']}</span></div>
                <div class="role-subtitle">Invite sent: {sent_ago} &nbsp;·&nbsp; Est: {job.get('est_ctc_lpa', '18')} LPA &nbsp;·&nbsp; Status: STALE_NO_RESPONSE</div>
                """,
                unsafe_allow_html=True,
            )
        with col_s2:
            st.link_button("View Job Posting", job["job_url"], width="stretch")

        if contacts:
            c = contacts[0]
            d = drafts[0] if drafts else {}
            badges_html = format_contact_badges(c)

            st.markdown(
                f"""
                <div class="contact-title">{c.get('name', 'Contact')} &nbsp;·&nbsp; <span style="font-weight: normal; color: #64748B;">{c.get('headline', '')}</span></div>
                <div style="margin-bottom: 0.65rem;">{badges_html}</div>
                """,
                unsafe_allow_html=True,
            )

            email_draft = d.get("direct_email_draft")
            if not email_draft:
                from src.nodes.drafter import build_direct_email_draft
                from src.models import ContactPerson, JobPosting
                email_draft = build_direct_email_draft(
                    ContactPerson.model_validate(c),
                    JobPosting(job_id=job["job_id"], company=job["company"], role=job["role"], location=job.get("location", ""), jd_text="", job_url=job["job_url"], source=""),
                    d.get("full_dm_under_95_words", "")
                )

            st.markdown('<div class="step-box-header">DIRECT COLD EMAIL (Send to Verified Hunter.io Address Above)</div>', unsafe_allow_html=True)
            st.code(email_draft, language=None, wrap_lines=True)

        st.markdown("<hr style='border: none; border-top: 1px solid #F0F0EE; margin: 0.85rem 0;'>", unsafe_allow_html=True)

        col_st1, col_st2, col_st3 = st.columns([2.0, 2.0, 1.5])
        with col_st1:
            if st.button("📧 Cold Email Sent", type="primary", key=f"email_sent_{job['job_id']}", width="stretch"):
                update_single_job_status(job["job_id"], "REFERRAL_ASKED")
                st.toast(f"Direct cold email logged for {job['company']}! Moved to Active Referrals.")
                st.rerun()

        with col_st2:
            if st.button("🤝 Belatedly Accepted on LinkedIn", key=f"accept_late_{job['job_id']}", width="stretch"):
                update_single_job_status(job["job_id"], "CONNECTED_READY_TO_ASK")
                st.toast(f"{job['company']} restored to Ready to Ask in Tab 1!")
                st.rerun()

        with col_st3:
            if st.button("🗑️ Dismiss / Archive", key=f"dismiss_{job['job_id']}", width="stretch"):
                update_single_job_status(job["job_id"], "SKIPPED")
                st.toast(f"Archived {job['company']}.")
                st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# TAB 5: 📊 Full Application Tracker & CSV Export
# -----------------------------------------------------------------------------
def export_rich_tracker_csv(df: pd.DataFrame) -> str:
    """Exports a clean, unpacked Excel-friendly CSV with full contact and outreach details."""
    if df.empty:
        return ""

    rows_data = []
    for _, row in df.iterrows():
        contacts = parse_json_safely(row.get("contacts_json")) or []
        drafts = parse_json_safely(row.get("outreach_drafts_json")) or []

        c1 = contacts[0] if len(contacts) > 0 else {}
        d1 = drafts[0] if len(drafts) > 0 else {}
        c2 = contacts[1] if len(contacts) > 1 else {}
        d2 = drafts[1] if len(drafts) > 1 else {}
        c3 = contacts[2] if len(contacts) > 2 else {}
        d3 = drafts[2] if len(drafts) > 2 else {}
        c4 = contacts[3] if len(contacts) > 3 else {}
        d4 = drafts[3] if len(drafts) > 3 else {}

        sent_at = str(row.get("outreach_sent_at", ""))
        sent_clean = sent_at[:16] if sent_at and sent_at not in ("None", "nan") else ""

        connect_sent = str(row.get("connect_sent_at", ""))
        connect_clean = connect_sent[:16] if connect_sent and connect_sent not in ("None", "nan") else ""

        created_at = str(row.get("created_at", ""))
        created_clean = created_at[:10] if created_at and created_at not in ("None", "nan") else ""

        rows_data.append({
            "Company": row.get("company", ""),
            "Role": row.get("role", ""),
            "Status": row.get("status", ""),
            "Job URL": row.get("job_url", ""),
            "Surfaced Date": created_clean,
            "Connection Sent Date": connect_clean,
            "Referral Asked Date": sent_clean,
            "Est CTC LPA": row.get("est_ctc_lpa", ""),
            "HR / Referral Email": row.get("hr_email", ""),
            "Contact 1 Name": c1.get("name", ""),
            "Contact 1 Email": c1.get("email", ""),
            "Contact 1 Tier": c1.get("tier", ""),
            "Contact 1 Headline": c1.get("headline", ""),
            "Contact 1 LinkedIn": c1.get("linkedin_url", ""),
            "Contact 1 Step 1 Note": d1.get("connection_note_300_chars", ""),
            "Contact 1 Step 2 DM": d1.get("full_dm_under_95_words", ""),
            "Contact 1 Direct Email": d1.get("direct_email_draft", ""),
            "Contact 2 Name": c2.get("name", ""),
            "Contact 2 Email": c2.get("email", ""),
            "Contact 2 Tier": c2.get("tier", ""),
            "Contact 2 Headline": c2.get("headline", ""),
            "Contact 2 LinkedIn": c2.get("linkedin_url", ""),
            "Contact 2 Step 1 Note": d2.get("connection_note_300_chars", ""),
            "Contact 2 Step 2 DM": d2.get("full_dm_under_95_words", ""),
            "Contact 2 Direct Email": d2.get("direct_email_draft", ""),
            "Contact 3 Name": c3.get("name", ""),
            "Contact 3 Email": c3.get("email", ""),
            "Contact 3 LinkedIn": c3.get("linkedin_url", ""),
            "Contact 3 Step 1 Note": d3.get("connection_note_300_chars", ""),
            "Contact 3 Step 2 DM": d3.get("full_dm_under_95_words", ""),
            "Contact 3 Direct Email": d3.get("direct_email_draft", ""),
            "Contact 4 Name": c4.get("name", ""),
            "Contact 4 Email": c4.get("email", ""),
            "Contact 4 LinkedIn": c4.get("linkedin_url", ""),
            "Contact 4 Step 1 Note": d4.get("connection_note_300_chars", ""),
            "Contact 4 Step 2 DM": d4.get("full_dm_under_95_words", ""),
            "Contact 4 Direct Email": d4.get("direct_email_draft", ""),
            "Direct Cover Note": row.get("fallback_note", ""),
            "Winning Hook": row.get("winning_hook", ""),
            "Notes": row.get("notes", ""),
        })

    rich_df = pd.DataFrame(rows_data)
    return rich_df.to_csv(index=False)


def render_application_tracker():
    """Renders exact spreadsheet with inline status, hr_email, and referrer editing."""
    st.markdown("### Application Tracker & Spreadsheet")

    col_filter, col_spacer = st.columns([2.5, 2.5])
    with col_filter:
        status_options = ["ALL"] + VALID_STATUSES
        selected_filter = st.selectbox("Filter by Stage", options=status_options, index=0)

    df = load_jobs_dataframe(status_filter=selected_filter)

    if df.empty:
        st.info(f"No applications found for stage '{selected_filter}'.")
        return

    # Columns in requested order
    display_cols = [
        "company",
        "role",
        "job_url",
        "est_ctc_lpa",
        "hr_email",
        "referrer_name",
        "status",
        "outreach_sent_at",
        "notes",
    ]

    available_cols = [c for c in display_cols if c in df.columns]
    edit_df = df[available_cols + ["job_id"]].copy()

    column_config = {
        "company": st.column_config.TextColumn("Company", disabled=True, width="medium"),
        "role": st.column_config.TextColumn("Role", disabled=True, width="medium"),
        "job_url": st.column_config.LinkColumn("Job Posting", display_text="Open Job", width="small"),
        "est_ctc_lpa": st.column_config.NumberColumn("Est. CTC (LPA)", format="₹%.1fL", disabled=True, width="small"),
        "hr_email": st.column_config.TextColumn("HR / Referral Email", width="medium"),
        "referrer_name": st.column_config.TextColumn("Referrer Name", width="medium"),
        "status": st.column_config.SelectboxColumn("Stage", options=VALID_STATUSES, required=True, width="medium"),
        "outreach_sent_at": st.column_config.TextColumn("Outreach Sent Date", disabled=True, width="small"),
        "notes": st.column_config.TextColumn("Notes / Context", width="large"),
        "job_id": None,
    }

    st.markdown('<div class="table-container">', unsafe_allow_html=True)
    edited_df = st.data_editor(
        edit_df,
        column_config=column_config,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key="tracker_spreadsheet_editor",
    )
    st.markdown('</div>', unsafe_allow_html=True)

    col_btn1, col_btn2 = st.columns([1.5, 3.5])
    with col_btn1:
        if st.button("Save Spreadsheet Changes", type="primary", width="stretch"):
            updates = update_job_status_and_notes(edited_df)
            st.toast(f"Successfully saved {updates} updates to database.")
            st.rerun()

    with col_btn2:
        csv_data = export_rich_tracker_csv(df)
        if csv_data:
            st.download_button(
                label="📥 Export Rich Tracker CSV (All Contacts & DMs)",
                data=csv_data,
                file_name=f"jobhunt_tracker_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                width="stretch",
            )


# -----------------------------------------------------------------------------
# Main Application Entrypoint
# -----------------------------------------------------------------------------
def main():
    render_header()

    # Automatically transition connections older than 5 days to STALE_NO_RESPONSE
    auto_transition_stale_connections(stale_days=5)

    stats = get_dashboard_stats()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        f"🔥 Today's Referral Asks ({stats.get('today_asks', 0)})",
        f"🆕 New High-Match Roles ({stats.get('total_new', 0)})",
        f"🏆 Active Referrals ({stats.get('referrals_asked', 0)})",
        f"💤 Stale / Email Fallback ({stats.get('stale', 0)})",
        "📊 Full Application Tracker",
    ])

    with tab1:
        render_today_referral_asks()
    with tab2:
        render_triage_queue()
    with tab3:
        render_active_referrals()
    with tab4:
        render_stale_direct_email_fallback()
    with tab5:
        render_application_tracker()


if __name__ == "__main__":
    main()
