"""
Milestone 5: LangGraph Daily Ingestion, Filtering & Enrichment Pipeline.

Orchestrates the entire job hunt automation loop:
  1. scrape_node: 4-Channel federated ingestion (WWR, Himalayas, Greenhouse/Lever/Ashby, JobSpy)
  2. gatekeeper_node: Deterministic 7-gate filtering (Seen, RLHF/contract, Blacklist, Senior, YoE, Geo)
  3. company_intel_node: Company quality & 15+ LPA gate with SQLite caching & search hydration
  4. enrichment_node: Artifact-to-JD hook mapping, contact discovery & personalized outreach drafting
  5. persistence_node: SQLite atomic persistence of enriched job records
"""

import logging
from typing import List, Dict, Any, Tuple
from langgraph.graph import StateGraph, START, END

from src.models import (
    JobPosting,
    CompanyIntel,
    EnrichedJobRecord,
    JobHuntGraphState,
)
from src.db import init_db, save_enriched_jobs
from src.nodes.scrapers import run_all_scrapers
from src.nodes.filter import filter_jobs
from src.nodes.company_intel import evaluate_companies_for_jobs
from src.nodes.evaluate import score_and_tailor_jobs
from src.nodes.people_finder import find_contacts_for_company, find_hr_email_for_company
from src.nodes.drafter import generate_outreach_for_job

logger = logging.getLogger("pipeline.graph")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


# =========================================================================
# Pipeline Nodes
# =========================================================================

def scrape_node(state: JobHuntGraphState) -> Dict[str, Any]:
    """Node 1: Runs all ingestion channels and aggregates raw postings."""
    logger.info("=== [Step 1/5] Starting Ingestion Scrapers ===")
    try:
        raw_postings = run_all_scrapers()
    except Exception as e:
        logger.error(f"[scrape_node] Scraping failed: {e}")
        raw_postings = []

    logger.info(f"[scrape_node] Ingestion completed. Scraped {len(raw_postings)} raw job postings.")
    return {"raw_jobs": raw_postings}


def gatekeeper_node(state: JobHuntGraphState) -> Dict[str, Any]:
    """Node 2: Deterministic zero-LLM-cost filtering gate."""
    raw_jobs = state.get("raw_jobs", [])
    logger.info(f"=== [Step 2/5] Running Deterministic Gatekeeper on {len(raw_jobs)} jobs ===")

    filtered, stats = filter_jobs(raw_jobs)
    logger.info(
        f"[gatekeeper_node] Filtered: {len(raw_jobs)} -> {len(filtered)} passed. "
        f"(Seen={stats.get('dropped_seen')}, Contract/RLHF={stats.get('dropped_contract_or_rlhf')}, "
        f"Senior={stats.get('dropped_senior_title')}, YoE={stats.get('dropped_high_yoe')})"
    )
    return {"filtered_jobs": filtered}


def company_intel_node(state: JobHuntGraphState) -> Dict[str, Any]:
    """Node 3: Company Viability & 15+ LPA Quality Gate (with SQLite caching)."""
    filtered_jobs = state.get("filtered_jobs", [])
    logger.info(f"=== [Step 3/5] Evaluating Company Intel for {len(filtered_jobs)} surviving jobs ===")

    if not filtered_jobs:
        return {"company_intel_pairs": []}

    surviving_pairs, stats = evaluate_companies_for_jobs(filtered_jobs)
    logger.info(
        f"[company_intel_node] Evaluated {stats.get('total_companies', 0)} companies: "
        f"{stats.get('cached_hits', 0)} cache hits, {stats.get('api_calls', 0)} API calls. "
        f"{len(surviving_pairs)} job-company pairs passed quality bar."
    )
    return {"company_intel_pairs": surviving_pairs}


def enrichment_node(state: JobHuntGraphState) -> Dict[str, Any]:
    """
    Node 4: Artifact Hook Mapper, Referral Discovery & Outreach Generation.
    Caps processing to top 15 jobs to preserve API rate-limits.
    """
    pairs: List[Tuple[JobPosting, CompanyIntel]] = state.get("company_intel_pairs", [])
    logger.info(f"=== [Step 4/5] Enriching top {min(len(pairs), 15)} jobs (Matching + Contacts + Drafting) ===")

    if not pairs:
        logger.warning("[enrichment_node] No job-company pairs to enrich.")
        return {"enriched_jobs": []}

    # Cap to top 15 jobs
    capped_pairs = pairs[:15]

    # 1. Score & Tailor Jobs (Matcher)
    scored_results = score_and_tailor_jobs(capped_pairs, max_jobs_to_score=15)

    enriched_records: List[EnrichedJobRecord] = []

    for i, (job, intel, match_result) in enumerate(scored_results, 1):
        logger.info(f"[enrichment_node] [{i}/{len(scored_results)}] Processing '{job.company}' - '{job.role}'")

        # 2. Discover Contacts (People Finder)
        try:
            contacts = find_contacts_for_company(job.company, job.role)
        except Exception as e:
            logger.error(f"[enrichment_node] People finder failed for {job.company}: {e}")
            contacts = []

        # 3. Discover HR / Recruiting Email
        try:
            hr_email = find_hr_email_for_company(job.company, job.job_url, job.jd_text)
        except Exception as e:
            logger.warning(f"[enrichment_node] HR email discovery failed for {job.company}: {e}")
            hr_email = ""

        # 4. Generate Outreach Drafts (Drafter)
        try:
            packages, fallback_note = generate_outreach_for_job(job, intel, match_result, contacts)
        except Exception as e:
            logger.error(f"[enrichment_node] Drafter failed for {job.company}: {e}")
            packages = []
            fallback_note = None

        referrer_names = ", ".join(c.name for c in contacts) if contacts else ""

        record = EnrichedJobRecord(
            job=job,
            company_intel=intel,
            match_result=match_result,
            contacts=contacts,
            outreach_drafts=packages,
            fallback_direct_apply_note=fallback_note,
            hr_email=hr_email,
            referrer_name=referrer_names,
        )
        enriched_records.append(record)

    logger.info(f"[enrichment_node] Successfully created {len(enriched_records)} EnrichedJobRecords.")
    return {"enriched_jobs": enriched_records}


def persistence_node(state: JobHuntGraphState) -> Dict[str, Any]:
    """Node 5: Persists all enriched job records into SQLite."""
    enriched = state.get("enriched_jobs", [])
    logger.info(f"=== [Step 5/5] Persisting {len(enriched)} EnrichedJobRecords to SQLite ===")

    if not enriched:
        logger.info("[persistence_node] No records to persist.")
        return {}

    saved_count = save_enriched_jobs(enriched)
    logger.info(f"[persistence_node] Successfully saved/updated {saved_count} jobs in SQLite DB.")
    return {}


# =========================================================================
# Graph Construction & Compilation
# =========================================================================

def build_job_hunt_graph() -> Any:
    """Builds and compiles the StateGraph workflow."""
    init_db()
    builder = StateGraph(JobHuntGraphState)

    # Register Nodes
    builder.add_node("scrape", scrape_node)
    builder.add_node("gatekeeper", gatekeeper_node)
    builder.add_node("company_intel", company_intel_node)
    builder.add_node("enrichment", enrichment_node)
    builder.add_node("persistence", persistence_node)

    # Register Edges
    builder.add_edge(START, "scrape")
    builder.add_edge("scrape", "gatekeeper")
    builder.add_edge("gatekeeper", "company_intel")
    builder.add_edge("company_intel", "enrichment")
    builder.add_edge("enrichment", "persistence")
    builder.add_edge("persistence", END)

    return builder.compile()


# Singleton compiled graph
job_hunt_pipeline = build_job_hunt_graph()


def run_daily_pipeline() -> JobHuntGraphState:
    """
    Convenience helper function to execute the daily pipeline end-to-end.
    Can be imported by CLI scripts, cron jobs, or the Streamlit dashboard.
    """
    logger.info("Starting Daily LangGraph Job Hunt Pipeline...")
    initial_state: JobHuntGraphState = {
        "raw_jobs": [],
        "filtered_jobs": [],
        "company_intel_pairs": [],
        "enriched_jobs": [],
    }

    final_state = job_hunt_pipeline.invoke(initial_state)
    logger.info("Daily LangGraph Job Hunt Pipeline completed successfully.")
    return final_state


if __name__ == "__main__":
    print("=" * 70)
    print("  EXECUTING DAILY LANGGRAPH JOB HUNT PIPELINE (CLI)")
    print("=" * 70)
    result = run_daily_pipeline()
    enriched = result.get("enriched_jobs", [])
    print(f"\nPipeline Finished. Total Enriched Jobs Processed: {len(enriched)}")
    for r in enriched:
        print(f"  - [{r.match_result.match_score}/100] {r.job.company} - {r.job.role} ({len(r.contacts)} contacts)")
    print("=" * 70)

