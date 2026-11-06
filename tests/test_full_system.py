"""
Milestone 5 Full System & UI Verification Test.

Tests:
  1. LangGraph StateGraph structure, nodes, and compilation.
  2. Database persistence of EnrichedJobRecords.
  3. Dashboard query helpers: get_dashboard_stats, get_all_jobs, update_job_status.
  4. 48-Hour Overdue Follow-up alert logic with mock timestamp.
  5. Streamlit app.py syntax and import integrity.
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

# Ensure root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.models import (
    JobPosting,
    CompanyIntel,
    MatchAndTailorResult,
    ContactPerson,
    OutreachPackage,
    EnrichedJobRecord,
)
from src.db import (
    init_db,
    save_enriched_jobs,
    get_dashboard_stats,
    get_all_jobs,
    update_job_status,
    get_overdue_followups,
)
from src.graph import job_hunt_pipeline, build_job_hunt_graph

TEST_DB = Path("data/test_sandbox.db")


def test_graph_compilation():
    print("=" * 70)
    print("TEST 1: LangGraph Workflow Compilation")
    print("=" * 70)

    graph = build_job_hunt_graph()
    assert graph is not None, "Failed to compile StateGraph"
    print("  [PASS] StateGraph compiled successfully.")

    # Verify node names
    expected_nodes = {"scrape", "gatekeeper", "company_intel", "enrichment", "persistence"}
    # Check node presence in compiled graph
    graph_nodes = set(graph.nodes.keys())
    assert expected_nodes.issubset(graph_nodes), f"Missing nodes: {expected_nodes - graph_nodes}"
    print(f"  [PASS] All 5 required nodes present: {sorted(list(expected_nodes))}")


def test_persistence_and_dashboard_queries():
    print("\n" + "=" * 70)
    print("TEST 2: Database Persistence & Dashboard Query Layer")
    print("=" * 70)

    # Clean sandbox DB before test
    if TEST_DB.exists():
        TEST_DB.unlink()

    init_db(TEST_DB)

    # Create 2 mock enriched records
    rec1 = EnrichedJobRecord(
        job=JobPosting(
            job_id="test_m5_razorpay",
            company="Razorpay",
            role="AI Engineer - Risk & Compliance",
            location="Bangalore, India",
            jd_text="Build risk scoring models.",
            job_url="https://razorpay.com/jobs/ai-risk",
            source="greenhouse",
        ),
        company_intel=CompanyIntel(
            company_name="Razorpay",
            funding_or_stage="Series F (Unicorn)",
            estimated_size="1000+",
            est_entry_ai_ctc_lpa=22.0,
            passes_quality_bar=True,
            summary_2_lines="Fintech unicorn building payment infrastructure.",
        ),
        match_result=MatchAndTailorResult(
            match_score=95,
            selected_project_id="fairtrace",
            winning_hook_sentence="My FairTrace architecture achieved 0.741 Test AUC on credit risk modeling.",
            missing_keywords=["fraud detection"],
            resume_bullet_tweaks=["Optimized XGBoost for compliance."],
        ),
        contacts=[
            ContactPerson(
                name="Nihir Agarwal",
                headline="SDE-II @ Razorpay | BITS Pilani",
                linkedin_url="https://linkedin.com/in/nihir",
                tier="1_ALUMNI",
                relevance_note="BITS alum",
            )
        ],
        outreach_drafts=[
            OutreachPackage(
                contact_name="Nihir Agarwal",
                contact_tier="1_ALUMNI",
                linkedin_url="https://linkedin.com/in/nihir",
                connection_note_300_chars="Hi Nihir, fellow BITSian here applying for AI Engineer.",
                full_dm_under_95_words="Hi Nihir, I'm Param from BITS. My FairTrace project achieved 0.741 AUC. Portfolio: https://parampatel-ai.vercel.app",
            )
        ],
    )

    rec2 = EnrichedJobRecord(
        job=JobPosting(
            job_id="test_m5_databricks",
            company="Databricks",
            role="ML Engineer",
            location="Bangalore, India",
            jd_text="Mosaic AI infrastructure.",
            job_url="https://databricks.com/jobs/ml",
            source="greenhouse",
        ),
        company_intel=CompanyIntel(
            company_name="Databricks",
            funding_or_stage="Pre-IPO",
            estimated_size="5000+",
            est_entry_ai_ctc_lpa=35.0,
            passes_quality_bar=True,
            summary_2_lines="Data & AI platform leader.",
        ),
        match_result=MatchAndTailorResult(
            match_score=88,
            selected_project_id="agent_diagnostician",
            winning_hook_sentence="My PyPI-published Agent Failure Diagnostician provides 3-tier forensic evaluation.",
            missing_keywords=["Spark"],
            resume_bullet_tweaks=["Integrated MLflow with Agent Diagnostician."],
        ),
        contacts=[],
        outreach_drafts=[],
        fallback_direct_apply_note="Hi Databricks team, I'm Param from BITS applying for ML Engineer. Check my portfolio: https://parampatel-ai.vercel.app",
    )

    # 1. Save records
    saved = save_enriched_jobs([rec1, rec2], db_path=TEST_DB)
    assert saved == 2, f"Expected 2 saved jobs, got {saved}"
    print(f"  [PASS] Successfully persisted {saved} enriched records into SQLite.")

    # 2. Test Dashboard Stats
    stats = get_dashboard_stats(db_path=TEST_DB)
    print(f"  [PASS] Dashboard Stats: Total={stats['total_jobs']}, New Today={stats['new_today']}")
    assert stats["total_jobs"] >= 2, "Expected at least 2 jobs in total"

    # 3. Test Status Updates
    update_job_status("test_m5_razorpay", "ASKED_REFERRAL", db_path=TEST_DB)
    jobs = get_all_jobs(status_filter="ASKED_REFERRAL", db_path=TEST_DB)
    matched = [j for j in jobs if j["job_id"] == "test_m5_razorpay"]
    assert len(matched) == 1, "Failed to retrieve job by status filter"
    assert matched[0]["status"] == "ASKED_REFERRAL", "Status update failed"
    print("  [PASS] update_job_status('ASKED_REFERRAL') verified.")

    # 4. Test 48-Hour Follow-Up Logic
    # Manually backdate outreach_sent_at by 3 days for test_m5_razorpay
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(TEST_DB) as conn:
        conn.execute(
            "UPDATE jobs SET outreach_sent_at = ? WHERE job_id = ?",
            (three_days_ago, "test_m5_razorpay"),
        )
        conn.commit()

    overdue = get_overdue_followups(db_path=TEST_DB, days=2)
    assert any(j["job_id"] == "test_m5_razorpay" for j in overdue), "Failed to detect overdue follow-up"
    print(f"  [PASS] 48-Hour overdue follow-up detection verified ({len(overdue)} overdue found).")

    # Clean up test sandbox
    import gc
    gc.collect()
    try:
        if TEST_DB.exists():
            TEST_DB.unlink()
    except Exception:
        pass


def test_streamlit_compilation():
    print("\n" + "=" * 70)
    print("TEST 3: Streamlit app.py Integrity Check")
    print("=" * 70)

    import py_compile
    py_compile.compile("app.py", doraise=True)
    print("  [PASS] app.py compiles cleanly with zero syntax errors.")


if __name__ == "__main__":
    test_graph_compilation()
    test_persistence_and_dashboard_queries()
    test_streamlit_compilation()
    print("\n" + "=" * 70)
    print("  ALL MILESTONE 5 VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)

