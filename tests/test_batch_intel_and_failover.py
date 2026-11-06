"""
Verification test for Batch Company Intel Evaluation and 503/Failover Resilience.

Tests:
  1. clean_company_name() normalization.
  2. Immediate zero-LLM drop for generic/confidential company names.
  3. Batch company evaluation latency (<15 seconds for uncached companies).
  4. 503/Unavailable/Timeout detection in llm_router.
"""

import os
import sys
import time
import logging

# Ensure root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from src.models import JobPosting
from src.nodes.company_intel import (
    clean_company_name,
    is_generic_company,
    evaluate_companies_for_jobs,
)
from src.llm_router import _is_server_unavailable_error, LITE_TIER_MODELS


def test_clean_company_name():
    print("=" * 70)
    print("TEST 1: clean_company_name & Generic Detection")
    print("=" * 70)

    # Test cleaning
    t1 = clean_company_name("Talentskeet Consulting • Bangalore Urban • Remote")
    assert t1 == "Talentskeet Consulting", f"Got: '{t1}'"
    print(f"  [PASS] 'Talentskeet Consulting • Bangalore Urban • Remote' -> '{t1}'")

    t2 = clean_company_name("Gleanwork | Enterprise Search & RAG")
    assert t2 == "Gleanwork", f"Got: '{t2}'"
    print(f"  [PASS] 'Gleanwork | Enterprise Search & RAG' -> '{t2}'")

    t3 = clean_company_name("Scale AI - Data Infrastructure")
    assert t3 == "Scale AI", f"Got: '{t3}'"
    print(f"  [PASS] 'Scale AI - Data Infrastructure' -> '{t3}'")

    # Test generic detection
    assert is_generic_company("Stealth Startup") is True
    assert is_generic_company("Confidential Company") is True
    assert is_generic_company("Unknown") is True
    assert is_generic_company("Google") is False
    assert is_generic_company("Databricks") is False
    print("  [PASS] Generic employer detection verified (zero LLM waste for stealth/confidential).")


def test_503_error_detection():
    print("\n" + "=" * 70)
    print("TEST 2: 503 / Unavailable / Timeout Error Detection")
    print("=" * 70)

    class Mock503Error(Exception):
        status_code = 503

    assert _is_server_unavailable_error(Mock503Error("503 Service Unavailable")) is True
    assert _is_server_unavailable_error(Exception("The model is overloaded. Please try again later.")) is True
    assert _is_server_unavailable_error(Exception("Deadline Exceeded: timed out after 20s")) is True
    assert _is_server_unavailable_error(Exception("429 ResourceExhausted")) is False

    print("  [PASS] 503 / Overload / Timeout detection correctly flags immediate model switch.")
    print(f"  [PASS] LITE_TIER_MODELS chain: {LITE_TIER_MODELS}")
    assert LITE_TIER_MODELS[0] == "gemini-3.5-flash-lite", "gemini-3.5-flash-lite must be primary"


def test_batch_company_intel_latency():
    print("\n" + "=" * 70)
    print("TEST 3: Batch Company Intel Speed & Latency (<15 seconds)")
    print("=" * 70)

    # 3 companies (including 1 noisy name and 1 generic name)
    sample_jobs = [
        JobPosting(
            job_id="test_glean_01",
            company="Gleanwork • Bangalore Urban • Remote",
            role="AI Search Engineer",
            location="Bangalore",
            jd_text="Build enterprise generative search, hybrid retrieval, vector search over work data.",
            job_url="https://glean.com/jobs/1",
            source="greenhouse",
        ),
        JobPosting(
            job_id="test_stripe_01",
            company="Stripe | Financial Infrastructure",
            role="ML Engineer - Fraud",
            location="Bangalore",
            jd_text="Build machine learning models to detect fraud and manage risk across global transactions.",
            job_url="https://stripe.com/jobs/1",
            source="greenhouse",
        ),
        JobPosting(
            job_id="test_stealth_01",
            company="Stealth Startup",
            role="Founding AI Engineer",
            location="Remote",
            jd_text="Building next gen stealth AI product.",
            job_url="https://wellfound.com/jobs/1",
            source="wellfound",
        ),
    ]

    start_time = time.time()
    surviving_pairs, stats = evaluate_companies_for_jobs(sample_jobs)
    elapsed = time.time() - start_time

    print(f"\nExecution Stats:")
    print(f"  Elapsed Time:      {elapsed:.2f} seconds")
    print(f"  Total Companies:   {stats['total_companies']}")
    print(f"  Generic Dropped:   {stats['generic_dropped']}")
    print(f"  API Calls:         {stats['api_calls']}")
    print(f"  Surviving Pairs:   {len(surviving_pairs)}")

    assert elapsed < 15.0, f"Batch evaluation took too long: {elapsed:.2f}s (target < 15s)"
    assert stats["generic_dropped"] >= 1, "Generic employer should have been dropped immediately"
    print(f"  [PASS] Batch evaluation finished in {elapsed:.2f}s (well under 15s limit).")

    for job, intel in surviving_pairs:
        print(f"    - {intel.company_name}: stage={intel.funding_or_stage}, CTC={intel.est_entry_ai_ctc_lpa} LPA")


if __name__ == "__main__":
    test_clean_company_name()
    test_503_error_detection()
    test_batch_company_intel_latency()
    print("\n" + "=" * 70)
    print("  ALL BATCH & PERFORMANCE TESTS PASSED!")
    print("=" * 70)

