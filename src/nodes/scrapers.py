"""
Compatibility wrapper for scrapers.py -> forwards to scrape.py.
"""

from src.nodes.scrape import (
    run_all_scrapers,
    generate_job_id,
    extract_clean_job_id,
    clean_html_to_text,
    search_dork_engine,
    hydrate_full_jd_via_jina,
    scrape_channel_linkedin,
    scrape_channel_ycombinator,
    scrape_channel_wellfound,
    scrape_channel_india_tech,
    deduplicate_and_cap_jobs,
)

__all__ = [
    "run_all_scrapers",
    "generate_job_id",
    "extract_clean_job_id",
    "clean_html_to_text",
    "search_dork_engine",
    "hydrate_full_jd_via_jina",
    "scrape_channel_linkedin",
    "scrape_channel_ycombinator",
    "scrape_channel_wellfound",
    "scrape_channel_india_tech",
    "deduplicate_and_cap_jobs",
]
