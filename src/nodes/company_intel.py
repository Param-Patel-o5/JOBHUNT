"""
Node 3: Company Intelligence & Viability Gate.

Groups incoming jobs by company, checks SQLite cache, cleans noisy names,
runs concurrent search snippet hydration, and evaluates companies in batches of up to 8
to minimize LLM latency and conserve API quota.
"""

import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Dict, Any, Optional
from pydantic import BaseModel, Field

from src.models import JobPosting, CompanyIntel
from src.db import get_cached_company_intel, save_cached_company_intel
from src.llm_router import invoke_structured_llm

logger = logging.getLogger("intelligence.company_intel")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

GENERIC_COMPANY_NAMES = {
    "startup", "unknown", "confidential", "stealth", "weworkremotely",
    "freelance", "n/a", "anonymous", "private", "stealth startup", "talent acquisition"
}


class BatchCompanyIntelResult(BaseModel):
    results: List[CompanyIntel] = Field(description="List of CompanyIntel objects for the requested companies")


def clean_company_name(raw_name: str) -> str:
    """
    Cleans noisy company names from scrapers.
    E.g.: 'Talentskeet Consulting • Bangalore Urban • Remote' -> 'Talentskeet Consulting'
    """
    if not raw_name:
        return ""
    # Split on bullet, pipe, or space-hyphen-space
    parts = re.split(r"\s*[•|]\s*|\s+-\s+", raw_name.strip())
    cleaned = parts[0].strip() if parts else raw_name.strip()
    return cleaned


def is_generic_company(cleaned_name: str) -> bool:
    """Detects unnamed, stealth, or generic employer placeholders."""
    c = cleaned_name.strip().lower()
    if not c or c in GENERIC_COMPANY_NAMES:
        return True
    return any(g in c for g in ["confidential", "stealth startup", "undisclosed"])


def _try_search_company(company: str) -> str:
    """
    Attempts a lightweight web search for company context.
    Returns concatenated snippet text, or empty string on failure.
    """
    try:
        from src.nodes.scrapers import search_dork_engine
        query = f'"{company}" funding stage headcount Glassdoor salary India AI Engineer'
        results = search_dork_engine(query, max_results=3)
        snippets = []
        for r in results:
            title = r.get("title", "")
            content = r.get("content", "")
            snippets.append(f"{title}: {content}")
        return "\n".join(snippets)[:1500]
    except Exception as e:
        logger.warning(f"Search failed for company '{company}': {e}")
        return ""


def _build_batch_company_eval_prompt(batch_items: List[Dict[str, str]]) -> str:
    """Builds a single prompt evaluating up to 8 companies simultaneously."""
    company_blocks = []
    for i, item in enumerate(batch_items, 1):
        company_blocks.append(
            f"--- COMPANY #{i}: {item['company']} ---\n"
            f"SEARCH CONTEXT:\n{item['search_context'] if item['search_context'] else 'No search context.'}\n"
            f"SAMPLE JD EXCERPT:\n{item['sample_jd'][:800]}\n"
        )
    companies_text = "\n".join(company_blocks)

    return f"""You are a senior job market analyst evaluating {len(batch_items)} companies for a fresh graduate (2027 batch, India-based) targeting AI/ML/LLM Engineer roles with >= 15 LPA CTC.

COMPANIES TO EVALUATE:
{companies_text}

EVALUATION RULES FOR EACH COMPANY:
1. company_name: EXACT company name as provided in the header above.
2. passes_quality_bar = True ONLY IF ALL of these hold:
   a. Legitimate product company, funded startup (Seed $2M+ / Series A+), or established tech MNC.
   b. NOT an IT staffing/body-shop agency, RLHF coding tasks platform, freelance marketplace, or unpaid student project.
   c. Realistically pays >= 15 LPA CTC for entry-level AI/ML roles in India (funded startups: 12-25 LPA; top MNCs: 20-45 LPA; body-shops: 4-8 LPA).
3. If passes_quality_bar = False, provide a concise rejection_reason (e.g. "IT staffing agency", "Estimated CTC < 15 LPA", "Unfunded startup").
4. est_entry_ai_ctc_lpa: Estimated entry-level CTC in LPA (numeric float).
5. funding_or_stage: e.g. "Series B ($35M)", "Public MNC", "Bootstrapped", "Seed ($2.5M)", "Unknown".
6. estimated_size: e.g. "50-200", "1000+", "10-50".
7. summary_2_lines: Write a proper 3 to 4 sentence plain-English paragraph explaining what product the company builds, who their customers are, their funding/scale, and what their engineering team focuses on (plain English, zero buzzword soup).

Return a BatchCompanyIntelResult object containing exactly {len(batch_items)} CompanyIntel items in the exact same order."""


def evaluate_companies_for_jobs(
    jobs: List[JobPosting],
) -> Tuple[List[Tuple[JobPosting, CompanyIntel]], Dict[str, int]]:
    """
    Evaluates company viability for incoming jobs using batch evaluation and SQLite caching.
    
    1. Normalizes and cleans company names.
    2. Immediately drops generic/confidential names without LLM calls.
    3. Retrieves cached company intel from SQLite (0 API calls).
    4. Fetches search snippets concurrently via ThreadPoolExecutor.
    5. Evaluates uncached companies in batches of up to 8 per LLM call.
    6. Persists newly evaluated companies into SQLite cache.

    Returns:
        Tuple of (surviving_pairs, stats_dict)
    """
    stats = {
        "total_jobs_in": len(jobs),
        "total_companies": 0,
        "cached_hits": 0,
        "generic_dropped": 0,
        "api_calls": 0,
        "passed_quality": 0,
        "dropped_quality": 0,
        "errors": 0,
    }

    # Group jobs by cleaned company name
    company_jobs: Dict[str, List[JobPosting]] = {}
    for job in jobs:
        cleaned = clean_company_name(job.company)
        job.company = cleaned  # Update posting with cleaned display name
        key = cleaned.lower()
        if key not in company_jobs:
            company_jobs[key] = []
        company_jobs[key].append(job)

    stats["total_companies"] = len(company_jobs)
    logger.info(f"[Company Intel] Evaluating {stats['total_companies']} unique companies from {len(jobs)} jobs")

    company_intel_map: Dict[str, CompanyIntel] = {}
    uncached_keys: List[str] = []

    # Step 1: Check cache & filter generic companies
    for key, job_list in company_jobs.items():
        display_name = job_list[0].company

        if is_generic_company(display_name):
            stats["generic_dropped"] += 1
            intel = CompanyIntel(
                company_name=display_name,
                funding_or_stage="Generic/Confidential",
                estimated_size="Unknown",
                est_entry_ai_ctc_lpa=0.0,
                passes_quality_bar=False,
                summary_2_lines="Generic or confidential posting without identified employer.",
                rejection_reason="Generic or confidential company posting",
            )
            company_intel_map[key] = intel
            save_cached_company_intel(key, intel)
            continue

        cached = get_cached_company_intel(key)
        if cached is not None:
            stats["cached_hits"] += 1
            company_intel_map[key] = cached
            logger.debug(f"[CACHE HIT] {display_name} -> passes={cached.passes_quality_bar}")
        else:
            uncached_keys.append(key)

    # Step 2: Fetch search snippets concurrently for uncached companies
    search_contexts: Dict[str, str] = {}
    if uncached_keys:
        logger.info(f"[Company Intel] Running concurrent search lookups for {len(uncached_keys)} uncached companies...")
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_key = {
                executor.submit(_try_search_company, company_jobs[k][0].company): k
                for k in uncached_keys
            }
            for future in as_completed(future_to_key):
                k = future_to_key[future]
                try:
                    search_contexts[k] = future.result()
                except Exception as e:
                    logger.warning(f"Search future failed for {k}: {e}")
                    search_contexts[k] = ""

    # Step 3: Batch LLM evaluation (batches of up to 8 companies)
    batch_size = 8
    for i in range(0, len(uncached_keys), batch_size):
        batch_keys = uncached_keys[i : i + batch_size]
        batch_items = []
        for k in batch_keys:
            d_name = company_jobs[k][0].company
            s_jd = company_jobs[k][0].jd_text or ""
            batch_items.append({
                "key": k,
                "company": d_name,
                "search_context": search_contexts.get(k, ""),
                "sample_jd": s_jd,
            })

        prompt = _build_batch_company_eval_prompt(batch_items)
        batch_names = [item["company"] for item in batch_items]
        logger.info(f"[Company Intel] Evaluating batch of {len(batch_items)} companies: {batch_names}")

        try:
            batch_res = invoke_structured_llm(BatchCompanyIntelResult, prompt, tier="lite")
            stats["api_calls"] += 1

            # Map results back to company keys
            results_list = batch_res.results if hasattr(batch_res, "results") else []
            for idx, item in enumerate(batch_items):
                k = item["key"]
                d_name = item["company"]
                if idx < len(results_list):
                    intel = results_list[idx]
                    intel.company_name = d_name  # Ensure exact casing
                else:
                    # Fallback if list length mismatch
                    intel = CompanyIntel(
                        company_name=d_name,
                        funding_or_stage="Unknown",
                        estimated_size="Unknown",
                        est_entry_ai_ctc_lpa=15.0,
                        passes_quality_bar=True,
                        summary_2_lines=f"{d_name} technology firm.",
                    )
                company_intel_map[k] = intel
                save_cached_company_intel(k, intel)

        except Exception as e:
            logger.error(f"[Company Intel] Batch evaluation failed: {e}. Falling back to single-company calls...")
            stats["errors"] += 1
            # Single-company fallback
            for item in batch_items:
                k = item["key"]
                d_name = item["company"]
                try:
                    single_prompt = _build_batch_company_eval_prompt([item])
                    single_res = invoke_structured_llm(BatchCompanyIntelResult, single_prompt, tier="lite")
                    stats["api_calls"] += 1
                    intel = single_res.results[0] if single_res.results else CompanyIntel(
                        company_name=d_name, funding_or_stage="Unknown", estimated_size="Unknown",
                        est_entry_ai_ctc_lpa=0.0, passes_quality_bar=False, summary_2_lines="Fallback failed."
                    )
                except Exception as ex:
                    logger.error(f"Single fallback failed for {d_name}: {ex}")
                    intel = CompanyIntel(
                        company_name=d_name,
                        funding_or_stage="Unknown (LLM Error)",
                        estimated_size="Unknown",
                        est_entry_ai_ctc_lpa=0.0,
                        passes_quality_bar=False,
                        summary_2_lines="Evaluation failed due to LLM error.",
                        rejection_reason="LLM evaluation error",
                    )
                company_intel_map[k] = intel
                save_cached_company_intel(k, intel)

    # Step 4: Build surviving pairs
    surviving_pairs: List[Tuple[JobPosting, CompanyIntel]] = []

    for key, job_list in company_jobs.items():
        intel = company_intel_map.get(key)
        if not intel:
            continue

        if intel.passes_quality_bar:
            stats["passed_quality"] += 1
            for job in job_list:
                surviving_pairs.append((job, intel))
        else:
            stats["dropped_quality"] += 1
            logger.info(f"[DROPPED] {intel.company_name}: {intel.rejection_reason or 'Failed quality bar'}")

    logger.info(
        f"[Company Intel] Finished: {stats['total_companies']} companies -> "
        f"{stats['cached_hits']} cached, {stats['generic_dropped']} generic dropped, "
        f"{stats['api_calls']} API calls. {len(surviving_pairs)} job-company pairs surviving."
    )

    return surviving_pairs, stats
