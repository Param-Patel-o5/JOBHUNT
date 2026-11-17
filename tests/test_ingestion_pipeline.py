import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Ensure root directory is on PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv()

from src.nodes.scrapers import (
    scrape_wwr_rss,
    scrape_public_json_apis,
    scrape_dorked_boards,
    scrape_linkedin_glassdoor,
)
from src.nodes.gatekeeper import filter_jobs
from src.models import JobPosting

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_ingestion")


def test_and_diagnose_pipeline():
    print("=" * 80)
    print("      LANGGRAPH JOB HUNT PIPELINE - INGESTION & GATEKEEPER DIAGNOSTICS      ")
    print("=" * 80)

    # -------------------------------------------------------------
    # 1. Run Scraper Channels Individually
    # -------------------------------------------------------------
    print("\n[+] Step 1: Running Scraper Channels...")

    print(" -> Polling Channel 1: WeWorkRemotely RSS Feeds...")
    wwr_jobs = scrape_wwr_rss()

    print(" -> Polling Channel 2: Public JSON APIs (Himalayas, Greenhouse, Ashby, Lever)...")
    api_jobs = scrape_public_json_apis()

    has_tavily = bool(os.getenv("TAVILY_API_KEY", "").strip())
    print(f" -> Polling Channel 3: Tavily Search Dorking + Jina Hydration (Key present: {has_tavily})...")
    dork_jobs = scrape_dorked_boards()

    print(" -> Polling Channel 4: JobSpy (LinkedIn & Glassdoor - India)...")
    jobspy_jobs = scrape_linkedin_glassdoor()

    raw_jobs = wwr_jobs + api_jobs + dork_jobs + jobspy_jobs

    # Channel Summary Table
    print("\n" + "-" * 80)
    print(f"{'Channel / Source':<45} | {'Count':<10}")
    print("-" * 80)
    print(f"{'Channel 1: WeWorkRemotely RSS':<45} | {len(wwr_jobs):<10}")
    print(f"{'Channel 2: Public JSON APIs (Himalayas/Greenhouse/Ashby)':<45} | {len(api_jobs):<10}")
    print(f"{'Channel 3: Dorked Boards + Jina Reader Hydration':<45} | {len(dork_jobs):<10}")
    print(f"{'Channel 4: JobSpy (LinkedIn/Glassdoor)':<45} | {len(jobspy_jobs):<10}")
    print("-" * 80)
    print(f"{'Total Raw Ingested':<45} | {len(raw_jobs):<10}")
    print("-" * 80)

    # -------------------------------------------------------------
    # 2. Run Gatekeeper Filter
    # -------------------------------------------------------------
    print("\n[+] Step 2: Running Deterministic Zero-Cost Gatekeeper...")
    surviving_jobs, stats = filter_jobs(raw_jobs)

    print("\n" + "=" * 80)
    print("                      GATEKEEPER REJECTION BREAKDOWN                        ")
    print("=" * 80)
    print(f" Total Incoming Jobs              : {stats['total_incoming']}")
    print(f"  [-] Dropped (Already Seen in DB): {stats['dropped_seen']}")
    print(f"  [-] Dropped (Blacklisted Company: {stats['dropped_blacklisted']}")
    print(f"  [-] Dropped (Senior/Lead Title) : {stats.get('dropped_invalid_title', 0)}")
    print(f"  [-] Dropped (Irrelevant Role)   : {stats.get('dropped_contract_or_rlhf', 0)}")
    print(f"  [-] Dropped (High YoE > 2 years): {stats['dropped_high_yoe']}")
    print(f"  [-] Dropped (Geo-Locked US/EU)  : {stats.get('dropped_invalid_location', 0)}")
    print("-" * 80)
    print(f" [PASS] PASSED GATEKEEPER            : {stats.get('passed_filter', 0)}")
    print("=" * 80)

    # -------------------------------------------------------------
    # 3. Top Surviving Jobs Inspection
    # -------------------------------------------------------------
    print("\n[+] Step 3: Top Surviving Candidates for LLM Enrichment:\n")
    top_candidates = surviving_jobs[:3]

    if not top_candidates:
        print(" [!] No jobs survived all strict deterministic filters in this batch.")
    else:
        for idx, job in enumerate(top_candidates, 1):
            print(f"--- Surviving Job #{idx} ---")
            print(f" Company     : {job.company}")
            print(f" Role        : {job.role}")
            print(f" Source      : {job.source}")
            print(f" Location    : {job.location}")
            print(f" Job ID      : {job.job_id}")
            print(f" JD Text Len : {len(job.jd_text)} characters (Full-Text Hydration Verified)")
            print(f" Job URL     : {job.job_url}")
            snippet = job.jd_text[:180].replace("\n", " ").encode("ascii", errors="replace").decode("ascii")
            print(f" Snippet     : {snippet}...")
            print()

    print("=" * 80)
    print(" [OK] DIAGNOSTIC RUN COMPLETE.")
    print("=" * 80)


if __name__ == "__main__":
    test_and_diagnose_pipeline()

