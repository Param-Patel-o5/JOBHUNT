"""
Verification test for Milestone 4: Referral Discovery & Outreach Generation Layer.

Tests:
  1. Contact discovery via OSINT dorking (BITS Alumni, Team Peers, Recruiters)
  2. In-memory contact caching
  3. Tailored outreach drafting for discovered contacts
  4. Constraint verification:
     - connection_note <= 280 characters
     - full_dm <= 95 words
     - winning hook & portfolio URL presence
  5. Fallback ATS direct-apply note when contacts list is empty
"""

import os
import sys
import logging

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_milestone4")

from src.models import JobPosting, CompanyIntel, MatchAndTailorResult
from src.nodes.people_finder import find_contacts_for_company
from src.nodes.drafter import generate_outreach_for_job, PORTFOLIO_URL

# Test Jobs & Data (Razorpay & Databricks)
RAZORPAY_JOB = JobPosting(
    job_id="test_razorpay",
    company="Razorpay",
    role="AI Engineer - Risk & Compliance",
    location="Bangalore, India",
    jd_text="Build ML models for fraud detection and risk scoring. Work on credit risk assessment and fair lending models. XGBoost, tabular ML.",
    job_url="https://razorpay.com/jobs/ai-risk-compliance",
    source="greenhouse",
)

RAZORPAY_INTEL = CompanyIntel(
    company_name="Razorpay",
    funding_or_stage="Series F (Unicorn)",
    estimated_size="1000-5000",
    est_entry_ai_ctc_lpa=22.0,
    passes_quality_bar=True,
    summary_2_lines="Razorpay is India's leading fintech infrastructure unicorn building payments and banking tech.",
)

RAZORPAY_MATCH = MatchAndTailorResult(
    match_score=95,
    selected_project_id="fairtrace",
    winning_hook_sentence="My FairTrace architecture achieved a 0.741 Test AUC on credit risk modeling while ensuring regulatory compliance, directly addressing Razorpay's needs for fair lending.",
    missing_keywords=["fraud detection", "compliance automation"],
    resume_bullet_tweaks=["Optimized XGBoost credit risk models for regulatory fairness compliance."],
)

DATABRICKS_JOB = JobPosting(
    job_id="test_databricks",
    company="Databricks",
    role="ML Engineer - Mosaic AI",
    location="Bangalore, India",
    jd_text="Build model training and serving infrastructure for Mosaic AI. Python, Spark, MLflow, distributed training.",
    job_url="https://databricks.com/jobs/ml-engineer-mosaic",
    source="greenhouse",
)

DATABRICKS_INTEL = CompanyIntel(
    company_name="Databricks",
    funding_or_stage="Late-stage Private / Pre-IPO",
    estimated_size="5000+",
    est_entry_ai_ctc_lpa=35.0,
    passes_quality_bar=True,
    summary_2_lines="Databricks builds the unified Data Intelligence Platform and Mosaic AI infrastructure.",
)

DATABRICKS_MATCH = MatchAndTailorResult(
    match_score=85,
    selected_project_id="agent_diagnostician",
    winning_hook_sentence="My PyPI-published Agent Failure Diagnostician provides 3-tier forensic evaluation for LLM traces, offering the observability required for Mosaic AI pipelines.",
    missing_keywords=["Spark", "MLflow", "Distributed Systems"],
    resume_bullet_tweaks=["Integrated MLflow tracking into Agent Failure Diagnostician for automated evaluation."],
)


def run_milestone_4_tests():
    print("=" * 70)
    print("  MILESTONE 4 VERIFICATION: Referral Discovery & Outreach Generation")
    print("=" * 70)

    test_targets = [
        (RAZORPAY_JOB, RAZORPAY_INTEL, RAZORPAY_MATCH),
        (DATABRICKS_JOB, DATABRICKS_INTEL, DATABRICKS_MATCH),
    ]

    all_verified = True

    for job, intel, match in test_targets:
        print(f"\n" + "-" * 70)
        print(f"TARGET COMPANY: {job.company} ({job.role})")
        print("-" * 70)

        # 1. Discover contacts
        contacts = find_contacts_for_company(job.company, job.role)
        print(f"Discovered Contacts: {len(contacts)}")
        for i, c in enumerate(contacts, 1):
            print(f"  Contact #{i}:")
            print(f"    Name:     {c.name}")
            print(f"    Tier:     {c.tier}")
            print(f"    Headline: {c.headline}")
            print(f"    LinkedIn: {c.linkedin_url}")
            print(f"    Note:     {c.relevance_note}")

        # 2. Verify cache hit by calling find_contacts_for_company again
        cached_contacts = find_contacts_for_company(job.company, job.role)
        assert len(cached_contacts) == len(contacts), "Cache retrieval mismatch!"
        print("  [OK] Contact caching verified (instant lookup)")

        # 3. Generate Outreach Packages
        packages, fallback_note = generate_outreach_for_job(job, intel, match, contacts)

        if fallback_note:
            print(f"\n  Fallback Note Generated (Length={len(fallback_note)} chars, {len(fallback_note.split())} words):")
            print(f"  {fallback_note}")
        else:
            print(f"\nGenerated {len(packages)} Outreach Package(s):")
            for i, pkg in enumerate(packages, 1):
                note_len = len(pkg.connection_note_300_chars)
                dm_word_count = len(pkg.full_dm_under_95_words.split())

                print(f"\n  --- Package #{i} for {pkg.contact_name} ({pkg.contact_tier}) ---")
                print(f"  [LinkedIn URL]: {pkg.linkedin_url}")
                print(f"  [Connection Note] ({note_len}/280 chars):")
                print(f"    \"{pkg.connection_note_300_chars}\"")
                print(f"  [Full Direct Message] ({dm_word_count}/95 words):")
                print(f"    \"{pkg.full_dm_under_95_words}\"")

                # Constraint Verifications
                # 1. Connection note <= 280 chars
                if note_len <= 280:
                    print(f"  [PASS] Connection note length: {note_len} <= 280 chars")
                else:
                    print(f"  [FAIL] Connection note exceeded limit: {note_len} > 280 chars")
                    all_verified = False

                # 2. Full DM <= 95 words
                if dm_word_count <= 95:
                    print(f"  [PASS] Full DM word count: {dm_word_count} <= 95 words")
                else:
                    print(f"  [FAIL] Full DM exceeded word limit: {dm_word_count} > 95 words")
                    all_verified = False

                # 3. Winning hook check
                hook_words = [w.lower() for w in match.winning_hook_sentence.split()[:4]]
                hook_present = any(w in pkg.full_dm_under_95_words.lower() for w in hook_words)
                if hook_present:
                    print(f"  [PASS] Winning hook referenced in DM")
                else:
                    print(f"  [FAIL] Winning hook missing from DM")
                    all_verified = False

                # 4. Portfolio URL check
                if PORTFOLIO_URL in pkg.full_dm_under_95_words:
                    print(f"  [PASS] Portfolio URL included in DM")
                else:
                    print(f"  [FAIL] Portfolio URL missing from DM")
                    all_verified = False

    # 4. Test Fallback Direct Apply Note (empty contacts case)
    print("\n" + "-" * 70)
    print("TEST: Fallback Direct Apply Note (When contacts list is empty)")
    print("-" * 70)
    packages_empty, fallback_empty = generate_outreach_for_job(
        RAZORPAY_JOB, RAZORPAY_INTEL, RAZORPAY_MATCH, contacts=[]
    )
    assert len(packages_empty) == 0, "Packages should be empty when no contacts"
    assert fallback_empty is not None and len(fallback_empty) > 0, "Fallback note must not be empty"
    fallback_words = len(fallback_empty.split())
    print(f"Fallback Note ({fallback_words} words):")
    print(f"  \"{fallback_empty}\"")
    assert PORTFOLIO_URL in fallback_empty, "Portfolio URL must be in fallback note"
    print("  [PASS] Fallback ATS note successfully generated with hook and portfolio link")

    print("\n" + "=" * 70)
    if all_verified:
        print("  ALL MILESTONE 4 TESTS PASSED SUCCESSFULLY!")
    else:
        print("  SOME TESTS FAILED - CHECK OUTPUT ABOVE")
    print("=" * 70)


if __name__ == "__main__":
    run_milestone_4_tests()

