"""
Intelligence Layer Verification Script.

Tests:
  1. Upgraded Gatekeeper (contract/RLHF trap detection)
  2. Company Intel evaluation with SQLite caching
  3. Match & Tailor scoring with project selection

Handles missing GOOGLE_API_KEY gracefully.
"""

import os
import sys
import logging

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_intelligence")

from pathlib import Path
from src.models import JobPosting, CompanyIntel
from src.db import init_db

TEST_DB = Path("data/test_sandbox.db")
from src.nodes.gatekeeper import filter_jobs

# ============================================================
# Test Data: Mix of trap jobs + legitimate AI roles
# ============================================================

SAMPLE_JOBS = [
    # TRAP 1: RLHF contract gig - should be caught by new contract/RLHF gate
    JobPosting(
        job_id="trap001",
        company="Askable",
        role="Software Engineer, AI Coding Tasks (Contract)",
        location="Remote",
        jd_text="Join our platform to complete AI coding tasks. Rate code outputs for RLHF training. Flexible hours, contract-based. Pay per task completed.",
        job_url="https://askable.com/jobs/ai-coding-tasks",
        source="wellfound",
    ),
    # TRAP 2: Known RLHF platform - should be caught by blacklist or contract gate
    JobPosting(
        job_id="trap002",
        company="Outlier",
        role="AI Trainer - Python",
        location="Remote",
        jd_text="Train AI models by writing and evaluating code. Flexible freelance opportunity. Python expertise required.",
        job_url="https://outlier.ai/jobs/ai-trainer",
        source="linkedin",
    ),
    # TRAP 3: Freelance annotation gig
    JobPosting(
        job_id="trap003",
        company="Scale Data",
        role="Data Annotation Specialist",
        location="Remote",
        jd_text="Annotate data for machine learning models. Part-time freelance position.",
        job_url="https://scaledata.com/jobs/annotator",
        source="linkedin",
    ),
    # LEGIT 1: Cohere - should pass all gates
    JobPosting(
        job_id="legit001",
        company="Cohere",
        role="Machine Learning Engineer",
        location="Remote - India",
        jd_text="We are building the future of language AI. Looking for ML Engineers to work on large language model training and inference optimization. Experience with transformers, PyTorch, distributed training. 0-2 years experience.",
        job_url="https://cohere.com/jobs/ml-engineer",
        source="greenhouse",
    ),
    # LEGIT 2: Razorpay - fintech, should trigger fairtrace project
    JobPosting(
        job_id="legit002",
        company="Razorpay",
        role="AI Engineer - Risk & Compliance",
        location="Bangalore, India",
        jd_text="Build ML models for fraud detection and risk scoring. Work on credit risk assessment, compliance automation, and fair lending models. Experience with XGBoost, tabular ML, regulatory compliance. Fintech domain knowledge preferred.",
        job_url="https://razorpay.com/jobs/ai-risk",
        source="greenhouse",
    ),
    # LEGIT 3: Perplexity - agentic AI
    JobPosting(
        job_id="legit003",
        company="Perplexity",
        role="Applied AI Engineer",
        location="Remote",
        jd_text="Work on retrieval-augmented generation, agent-based search systems, and LLM orchestration. Build production-grade RAG pipelines with hybrid search. Experience with vector databases, reranking, and multi-agent systems.",
        job_url="https://perplexity.ai/jobs/ai-engineer",
        source="ashby",
    ),
    # LEGIT 4: Databricks - should pass (famous ML company)
    JobPosting(
        job_id="legit004",
        company="Databricks",
        role="ML Engineer",
        location="Bangalore, India",
        jd_text="Join the ML team building Mosaic AI. Work on model training infrastructure, MLflow integrations, and serving systems. Python, Spark, deep learning frameworks. Strong engineering fundamentals required.",
        job_url="https://databricks.com/jobs/ml-engineer",
        source="greenhouse",
    ),
    # TRAP 4: Senior role - should be caught by senior title filter
    JobPosting(
        job_id="trap004",
        company="Google",
        role="Senior Machine Learning Engineer",
        location="Bangalore, India",
        jd_text="Lead ML infrastructure projects. 5+ years of experience required.",
        job_url="https://google.com/jobs/senior-ml",
        source="linkedin",
    ),
]


def test_upgraded_gatekeeper():
    """Test that the upgraded gatekeeper catches contract/RLHF traps."""
    print("\n" + "=" * 70)
    print("TEST 1: Upgraded Gatekeeper (Contract/RLHF Trap Detection)")
    print("=" * 70)

    surviving, stats = filter_jobs(SAMPLE_JOBS)

    print(f"\nInput: {stats['total_incoming']} jobs")
    print(f"Output: {stats['passed_gatekeeper']} survived")
    print("\nDrop breakdown:")
    for key, val in stats.items():
        if key.startswith("dropped_"):
            reason = key.replace("dropped_", "").replace("_", " ").title()
            print(f"  {reason}: {val}")

    print(f"\nSurviving jobs:")
    for j in surviving:
        print(f"  [PASS] {j.company} - {j.role}")

    # Verify traps were caught
    surviving_ids = {j.job_id for j in surviving}
    trap_ids = {"trap001", "trap002", "trap003", "trap004"}
    caught_traps = trap_ids - surviving_ids
    escaped_traps = trap_ids & surviving_ids

    print(f"\nTraps caught: {len(caught_traps)}/{len(trap_ids)}")
    if escaped_traps:
        print(f"  [WARNING] These traps ESCAPED: {escaped_traps}")
    else:
        print("  [OK] All traps successfully caught!")

    # Verify contract/RLHF specific stat
    rlhf_drops = stats.get("dropped_contract_or_rlhf", 0)
    print(f"\nContract/RLHF gate drops: {rlhf_drops}")
    assert rlhf_drops >= 1, "Contract/RLHF gate should have caught at least 1 trap!"
    print("  [OK] Contract/RLHF gate is working!")

    return surviving


def test_company_intel(surviving_jobs):
    """Test company intel evaluation with caching."""
    print("\n" + "=" * 70)
    print("TEST 2: Company Intel Evaluation + SQLite Cache")
    print("=" * 70)

    has_api_key = bool(os.getenv("GOOGLE_API_KEY"))
    if not has_api_key:
        print("\n[WARNING] GOOGLE_API_KEY not set in .env")
        print("Skipping LLM-dependent company intel test.")
        print("Add GOOGLE_API_KEY=your_key to .env to enable this test.")
        return []

    from src.nodes.company_intel import evaluate_companies_for_jobs

    # First run - should use API
    print("\n--- Run 1: Fresh evaluation (should use API) ---")
    pairs_1, stats_1 = evaluate_companies_for_jobs(surviving_jobs)

    print(f"\nRun 1 Stats:")
    for k, v in stats_1.items():
        print(f"  {k}: {v}")

    print(f"\nCompany evaluations:")
    seen_companies = set()
    for job, intel in pairs_1:
        if intel.company_name not in seen_companies:
            seen_companies.add(intel.company_name)
            status = "[PASS]" if intel.passes_quality_bar else "[FAIL]"
            print(
                f"  {status} {intel.company_name}: "
                f"stage={intel.funding_or_stage}, "
                f"est_ctc={intel.est_entry_ai_ctc_lpa} LPA, "
                f"size={intel.estimated_size}"
            )
            print(f"         {intel.summary_2_lines}")
            if intel.rejection_reason:
                print(f"         Reason: {intel.rejection_reason}")

    # Second run - should hit cache (0 API calls)
    print("\n--- Run 2: Cache verification (should use 0 API calls) ---")
    pairs_2, stats_2 = evaluate_companies_for_jobs(surviving_jobs)

    print(f"\nRun 2 Stats:")
    for k, v in stats_2.items():
        print(f"  {k}: {v}")

    assert stats_2["api_calls"] == 0, "Second run should use 0 API calls (all cached)!"
    assert stats_2["cached_hits"] == stats_2["total_companies"], "All companies should be cache hits!"
    print("\n  [OK] Cache is working! Zero API calls on second run.")

    return pairs_1


def test_matcher(job_intel_pairs):
    """Test the matcher/tailor scoring."""
    print("\n" + "=" * 70)
    print("TEST 3: Match & Tailor Scoring")
    print("=" * 70)

    has_api_key = bool(os.getenv("GOOGLE_API_KEY"))
    if not has_api_key:
        print("\n[WARNING] GOOGLE_API_KEY not set in .env")
        print("Skipping LLM-dependent matcher test.")
        print("Add GOOGLE_API_KEY=your_key to .env to enable this test.")
        return

    if not job_intel_pairs:
        print("\n[WARNING] No job-intel pairs to score (company intel may have dropped all)")
        return

    from src.nodes.matcher import score_and_tailor_jobs

    results = score_and_tailor_jobs(job_intel_pairs, max_jobs_to_score=10)

    print(f"\nScored {len(results)} jobs (sorted by match_score desc):\n")
    for i, (job, intel, match) in enumerate(results, 1):
        print(f"  #{i}. [{match.match_score}/100] {job.company} - {job.role}")
        print(f"      Project: {match.selected_project_id}")
        print(f"      Hook: {match.winning_hook_sentence}")
        print(f"      Missing: {', '.join(match.missing_keywords)}")
        print(f"      Tweaks:")
        for tweak in match.resume_bullet_tweaks:
            print(f"        - {tweak}")
        print()

    # Verify project selection logic
    for job, intel, match in results:
        if "razorpay" in job.company.lower():
            if match.selected_project_id == "fairtrace":
                print("  [OK] Razorpay correctly mapped to 'fairtrace' project!")
            else:
                print(
                    f"  [NOTE] Razorpay mapped to '{match.selected_project_id}' "
                    f"(expected 'fairtrace' for risk/compliance role)"
                )

    # Verify hook quality
    for job, intel, match in results:
        words = match.winning_hook_sentence.split()
        if len(words) > 28:
            print(f"  [WARNING] Hook too long ({len(words)} words) for {job.company}")


def test_db_cache_functions():
    """Test the cache functions directly."""
    print("\n" + "=" * 70)
    print("TEST 0: DB Cache Functions (No LLM needed)")
    print("=" * 70)

    from src.db import get_cached_company_intel, save_cached_company_intel

    init_db(TEST_DB)

    # Test save
    test_intel = CompanyIntel(
        company_name="TestCorp",
        funding_or_stage="Series A ($10M)",
        estimated_size="50-100",
        est_entry_ai_ctc_lpa=18.0,
        passes_quality_bar=True,
        summary_2_lines="TestCorp builds AI tools. Good engineering culture.",
        rejection_reason=None,
    )
    save_cached_company_intel("TestCorp", test_intel, db_path=TEST_DB)
    print("  [OK] save_cached_company_intel() succeeded")

    # Test retrieve
    retrieved = get_cached_company_intel("testcorp", db_path=TEST_DB)  # lowercase should work
    assert retrieved is not None, "Cache retrieval failed!"
    assert retrieved.company_name == "TestCorp"
    assert retrieved.est_entry_ai_ctc_lpa == 18.0
    assert retrieved.passes_quality_bar is True
    print("  [OK] get_cached_company_intel() succeeded (case-insensitive)")

    # Test cache miss
    missing = get_cached_company_intel("NonExistentCorp", db_path=TEST_DB)
    assert missing is None, "Should return None for uncached company!"
    print("  [OK] Cache miss returns None correctly")

    if TEST_DB.exists():
        TEST_DB.unlink()

    print("\n  All DB cache tests passed!")


if __name__ == "__main__":
    print("=" * 70)
    print("  INTELLIGENCE LAYER VERIFICATION")
    print("  Testing: Gatekeeper upgrade, Company Intel, Matcher")
    print("=" * 70)

    # Init DB
    init_db()

    # Test 0: DB cache (always runs, no LLM)
    test_db_cache_functions()

    # Test 1: Upgraded gatekeeper (always runs, no LLM)
    surviving = test_upgraded_gatekeeper()

    # Test 2: Company Intel (requires GOOGLE_API_KEY)
    pairs = test_company_intel(surviving)

    # Test 3: Matcher (requires GOOGLE_API_KEY + surviving pairs)
    test_matcher(pairs)

    print("\n" + "=" * 70)
    print("  ALL TESTS COMPLETE")
    print("=" * 70)
