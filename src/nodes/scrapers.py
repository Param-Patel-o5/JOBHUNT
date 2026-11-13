import os
import re
import html
import time
import random
import hashlib
import logging
import xml.etree.ElementTree as ET
from typing import List, Optional, Set, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import httpx

from src.models import JobPosting

# Load environment variables (e.g. TAVILY_API_KEY)
load_dotenv()

logger = logging.getLogger("ingestion.scrapers")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def generate_job_id(company: str, role: str, url: str) -> str:
    """Generate deterministic 12-char hex MD5 job_id from company, role, and url."""
    raw = f"{company.strip().lower()}|{role.strip().lower()}|{url.strip().lower()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def clean_html_to_text(raw_html: str) -> str:
    """Cleanly strip HTML tags and decode HTML entities using standard library html and re."""
    if not raw_html:
        return ""
    # Unescape HTML entities
    text = html.unescape(raw_html)
    # Remove script and style elements
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    # Replace block-level tags and breaks with newlines
    text = re.sub(r"<(?:br\s*/?|p|div|li|tr|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Normalize multiple whitespace / newlines
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    cleaned = "\n".join([line for line in lines if line])
    return cleaned.strip()


# =====================================================================
# Channel 1: Targeted RSS Feeds (WeWorkRemotely)
# =====================================================================

WWR_RSS_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/remote-jobs.rss",
]

AI_ML_KEYWORDS = [
    "ai", "machine learning", "llm", "genai", "nlp",
    "computer vision", "deep learning", "rag", "agent"
]

DISALLOWED_REGIONS = [
    "us only", "usa only", "north america only", "europe only"
]


def scrape_wwr_rss() -> List[JobPosting]:
    """
    Channel 1: Scrapes We Work Remotely programming & data science RSS feeds.
    Filters for AI/ML keywords and excludes regions strictly locked to US/EU.
    """
    postings: List[JobPosting] = []
    headers = {"User-Agent": "JobHuntBot/1.0 (+https://github.com/)"}

    with httpx.Client(timeout=15.0, headers=headers, follow_redirects=True) as client:
        for feed_url in WWR_RSS_FEEDS:
            try:
                resp = client.get(feed_url)
                if resp.status_code != 200:
                    logger.warning(f"[WWR RSS] Failed to fetch {feed_url}: HTTP {resp.status_code}")
                    continue

                root = ET.fromstring(resp.content)
                channel = root.find("channel")
                if channel is None:
                    continue

                for item in channel.findall("item"):
                    raw_title = item.findtext("title") or ""
                    link = item.findtext("link") or ""
                    pub_date = item.findtext("pubDate") or None
                    raw_description = item.findtext("description") or ""
                    region = item.findtext("region") or "Remote"

                    # Parse company and role from "Company Name: Role Title"
                    if ":" in raw_title:
                        company_part, role_part = raw_title.split(":", 1)
                        company = company_part.strip()
                        role = role_part.strip()
                    else:
                        company = "WeWorkRemotely"
                        role = raw_title.strip()

                    jd_text = clean_html_to_text(raw_description)

                    # Region restriction filter
                    region_lower = region.strip().lower()
                    if any(disallowed in region_lower for disallowed in DISALLOWED_REGIONS):
                        continue

                    # Keyword filter: title or description contains AI/ML keywords
                    combined_text = f"{role} {jd_text}".lower()
                    if not any(re.search(rf"\b{re.escape(kw)}\b", combined_text) for kw in AI_ML_KEYWORDS):
                        continue

                    job_id = generate_job_id(company, role, link)
                    postings.append(
                        JobPosting(
                            job_id=job_id,
                            company=company,
                            role=role,
                            location=region.strip() or "Remote",
                            jd_text=jd_text,
                            job_url=link.strip(),
                            source="wwr",
                            posted_date=pub_date,
                        )
                    )
            except Exception as e:
                logger.error(f"[WWR RSS] Error scraping {feed_url}: {e}")

    logger.info(f"[WWR RSS] Scraped {len(postings)} jobs.")
    return postings


# =====================================================================
# Channel 2: Native Public JSON APIs
# =====================================================================

GREENHOUSE_SLUGS = [
    "scaleai", "gleanwork", "databricks", "stripe", "rubrik",
    "cohere", "appliedintuition", "figure", "instacart", "gusto",
    "ramp", "affirm", "brex", "flexport", "plaid", "toast",
    "reddit", "samsara", "postman", "razorpay", "cred", "swiggy",
    "groww", "meesho", "zepto", "inmobi", "deepgram", "tavily"
]

ASHBY_SLUGS = [
    "perplexity", "langchain", "elevenlabs", "linear",
    "together-ai", "mistral", "cursor", "modal", "poolside",
    "anysphere", "cognition", "baseten", "suno", "pika",
    "harvey", "character", "character-ai", "cartesia",
    "factory", "magic-dev", "replit", "decagon", "sierra"
]

LEVER_SLUGS = [
    "palantir", "atlassian", "spotify", "dataminr", "automattic",
    "duolingo", "gitlab", "discord", "huggingface"
]

TECH_TITLE_KEYWORDS = [
    "ai", "ml", "machine learning", "deep learning", "nlp", "computer vision",
    "data", "software", "engineer", "scientist", "founding", "genai", "llm"
]

INDIA_REMOTE_LOCATIONS = [
    "india", "bengaluru", "bangalore", "hyderabad", "pune", "remote", "gurgaon", "noida", "mumbai"
]


def _poll_himalayas(client: httpx.Client) -> List[JobPosting]:
    postings: List[JobPosting] = []
    queries = ["AI Engineer", "Machine Learning", "GenAI", "LLM", "Data Scientist"]

    for q in queries:
        url = "https://himalayas.app/jobs/api/search"
        params = {"q": q, "seniority": "Entry-level,Mid-level"}
        try:
            resp = client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(f"[Himalayas] HTTP {resp.status_code} for query: {q}")
                continue
            data = resp.json()
            jobs = data.get("jobs", [])
            for j in jobs:
                title = j.get("title", "").strip()
                company = j.get("companyName", "").strip()
                raw_desc = j.get("description", "")
                jd_text = clean_html_to_text(raw_desc)
                app_link = j.get("applicationLink") or j.get("guid") or ""
                pub_date = j.get("pubDate")
                loc_restrictions = j.get("locationRestrictions", [])

                # Check location restrictions (keep if empty, India, or Worldwide)
                if loc_restrictions:
                    allowed = False
                    for loc in loc_restrictions:
                        loc_str = str(loc).lower()
                        if "india" in loc_str or "worldwide" in loc_str or "anywhere" in loc_str:
                            allowed = True
                            break
                    if not allowed:
                        continue

                location = ", ".join(loc_restrictions) if loc_restrictions else "Worldwide / Remote"
                job_id = generate_job_id(company, title, app_link)
                postings.append(
                    JobPosting(
                        job_id=job_id,
                        company=company,
                        role=title,
                        location=location,
                        jd_text=jd_text,
                        job_url=app_link,
                        source="himalayas",
                        posted_date=str(pub_date) if pub_date else None,
                    )
                )
        except Exception as e:
            logger.error(f"[Himalayas] Error querying {q}: {e}")

    return postings


def _poll_greenhouse(client: httpx.Client) -> List[JobPosting]:
    postings: List[JobPosting] = []
    for slug in GREENHOUSE_SLUGS:
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        try:
            resp = client.get(url)
            if resp.status_code == 404:
                continue
            if resp.status_code != 200:
                logger.warning(f"[Greenhouse] HTTP {resp.status_code} for {slug}")
                continue

            data = resp.json()
            jobs = data.get("jobs", [])
            for j in jobs:
                title = j.get("title", "").strip()
                title_lower = title.lower()

                # Must match AI/ML/Data/Software keywords
                if not any(kw in title_lower for kw in TECH_TITLE_KEYWORDS):
                    continue

                loc_obj = j.get("location", {})
                loc_name = loc_obj.get("name", "") if isinstance(loc_obj, dict) else str(loc_obj)
                loc_lower = loc_name.lower()

                # Must match India/Remote targets
                if not any(target in loc_lower for target in INDIA_REMOTE_LOCATIONS):
                    continue

                raw_content = j.get("content", "")
                jd_text = clean_html_to_text(raw_content)
                job_url = j.get("absolute_url", "")
                posted_date = j.get("updated_at")

                job_id = str(j.get("id")) if j.get("id") else generate_job_id(slug, title, job_url)
                postings.append(
                    JobPosting(
                        job_id=job_id,
                        company=slug.capitalize(),
                        role=title,
                        location=loc_name or "Remote",
                        jd_text=jd_text,
                        job_url=job_url,
                        source="greenhouse",
                        posted_date=str(posted_date) if posted_date else None,
                    )
                )
        except Exception as e:
            logger.error(f"[Greenhouse] Error fetching slug {slug}: {e}")

    return postings


def _poll_ashby_and_lever(client: httpx.Client) -> List[JobPosting]:
    postings: List[JobPosting] = []

    # Ashby
    for slug in ASHBY_SLUGS:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        try:
            resp = client.get(url)
            if resp.status_code != 200:
                continue
            data = resp.json()
            jobs = data.get("jobs", [])
            for j in jobs:
                title = j.get("title", "").strip()
                title_lower = title.lower()
                if not any(kw in title_lower for kw in TECH_TITLE_KEYWORDS):
                    continue

                loc = j.get("location", "")
                secondary_locs = [s.get("location", "") for s in j.get("secondaryLocations", []) if isinstance(s, dict)]
                all_locs = " ".join([loc] + secondary_locs).lower()
                is_remote = j.get("isRemote", False)

                if not (is_remote or any(target in all_locs for target in INDIA_REMOTE_LOCATIONS)):
                    continue

                raw_desc = j.get("descriptionHtml", "") or j.get("descriptionPlain", "")
                jd_text = clean_html_to_text(raw_desc)
                job_url = j.get("jobUrl", "") or f"https://jobs.ashbyhq.com/{slug}/{j.get('id', '')}"
                posted_date = j.get("publishedAt")

                job_id = str(j.get("id")) if j.get("id") else generate_job_id(slug, title, job_url)
                postings.append(
                    JobPosting(
                        job_id=job_id,
                        company=slug.capitalize(),
                        role=title,
                        location=loc or ("Remote" if is_remote else "Worldwide"),
                        jd_text=jd_text,
                        job_url=job_url,
                        source="ashby",
                        posted_date=str(posted_date) if posted_date else None,
                    )
                )
        except Exception as e:
            logger.debug(f"[Ashby] Graceful catch for {slug}: {e}")

    # Lever
    for slug in LEVER_SLUGS:
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        try:
            resp = client.get(url)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if not isinstance(data, list):
                continue
            for j in data:
                title = j.get("text", "").strip()
                title_lower = title.lower()
                if not any(kw in title_lower for kw in TECH_TITLE_KEYWORDS):
                    continue

                categories = j.get("categories", {})
                loc = categories.get("location", "")
                all_loc_str = f"{loc} {categories.get('allLocations', '')}".lower()

                if not any(target in all_loc_str for target in INDIA_REMOTE_LOCATIONS):
                    continue

                raw_desc = j.get("descriptionHtml", "") or j.get("descriptionPlain", "")
                jd_text = clean_html_to_text(raw_desc)
                job_url = j.get("hostedUrl", "") or j.get("applyUrl", "")
                posted_date = j.get("createdAt")

                job_id = str(j.get("id")) if j.get("id") else generate_job_id(slug, title, job_url)
                postings.append(
                    JobPosting(
                        job_id=job_id,
                        company=slug.capitalize(),
                        role=title,
                        location=loc or "Remote",
                        jd_text=jd_text,
                        job_url=job_url,
                        source="lever",
                        posted_date=str(posted_date) if posted_date else None,
                    )
                )
        except Exception as e:
            logger.debug(f"[Lever] Graceful catch for {slug}: {e}")

    return postings


def scrape_public_json_apis() -> List[JobPosting]:
    """Channel 2: Scrapes native public JSON APIs (Himalayas, Greenhouse, Ashby, Lever)."""
    headers = {"User-Agent": "JobHuntBot/1.0 (+https://github.com/)"}
    with httpx.Client(timeout=15.0, headers=headers, follow_redirects=True) as client:
        himalayas_jobs = _poll_himalayas(client)
        greenhouse_jobs = _poll_greenhouse(client)
        ashby_lever_jobs = _poll_ashby_and_lever(client)

    combined = himalayas_jobs + greenhouse_jobs + ashby_lever_jobs
    logger.info(
        f"[Public APIs] Total: {len(combined)} "
        f"(Himalayas: {len(himalayas_jobs)}, Greenhouse: {len(greenhouse_jobs)}, Ashby/Lever: {len(ashby_lever_jobs)})"
    )
    return combined


# =====================================================================
# Channel 3: Search Dorking + Jina Reader Full-Text Hydration
# =====================================================================

DORK_QUERIES = [
    ('site:welcometothejungle.com/en/companies/*/jobs ("AI Engineer" OR "Machine Learning" OR "LLM") ("India" OR "Remote")', "otta"),
    ('site:otta.com/jobs ("AI Engineer" OR "Machine Learning" OR "GenAI")', "otta"),
    ('site:wellfound.com/jobs ("AI Engineer" OR "Machine Learning" OR "GenAI") ("India" OR "Bangalore" OR "Hyderabad" OR "Remote")', "wellfound"),
    ('site:ycombinator.com/companies/*/jobs ("AI" OR "Machine Learning" OR "LLM") ("India" OR "Remote")', "ycombinator"),
    ('site:workatastartup.com/jobs ("AI" OR "Machine Learning" OR "GenAI")', "ycombinator"),
    ('site:instahyre.com/job- ("AI" OR "Machine Learning" OR "Data Scientist")', "instahyre"),
    ('site:jobs.ashbyhq.com ("AI Engineer" OR "Machine Learning" OR "LLM") ("India" OR "Remote")', "ashby"),
    ('site:boards.greenhouse.io ("AI Engineer" OR "Machine Learning" OR "GenAI") ("India" OR "Remote" OR "Bengaluru")', "greenhouse"),
    ('site:jobs.lever.co ("AI Engineer" OR "Machine Learning" OR "Deep Learning") ("India" OR "Remote" OR "Bengaluru")', "lever"),
]


def hydrate_full_jd_via_jina(url: str, fallback_snippet: str) -> str:
    """
    Hydrate full JD text using Jina Reader (r.jina.ai).
    Falls back cleanly to the search snippet if Jina fails or returns <200 chars.
    Truncates full text to 8,000 characters.
    """
    jina_url = f"https://r.jina.ai/{url}"
    headers = {"User-Agent": "JobHuntBot/1.0"}
    try:
        with httpx.Client(timeout=8.0, headers=headers) as client:
            resp = client.get(jina_url)
            if resp.status_code == 200:
                text = resp.text.strip()
                if len(text) > 200:
                    return text[:8000]
    except Exception as e:
        logger.debug(f"[Jina Reader] Could not hydrate {url}: {e}")

    return fallback_snippet[:8000] if fallback_snippet else ""


def _parse_title_company(title: str, url: str) -> tuple[str, str]:
    """Helper to extract (company, role) from a search result title or URL."""
    # Common formats: "Role at Company", "Role - Company", "Company hiring Role"
    clean = re.sub(r"\s*\|\s*.*$", "", title)  # remove trailing site branding
    clean = re.sub(r"\s*-\s*(Wellfound|Y Combinator|Instahyre|Otta|Welcome to the Jungle).*$", "", clean, flags=re.I)

    if " at " in clean:
        parts = clean.split(" at ", 1)
        return parts[1].strip(), parts[0].strip()
    elif " - " in clean:
        parts = clean.split(" - ", 1)
        return parts[1].strip(), parts[0].strip()
    elif " hiring " in clean:
        parts = clean.split(" hiring ", 1)
        return parts[0].strip(), parts[1].strip()

    # Fallback to extracting from domain/url
    return "Startup", clean.strip()


def search_dork_engine(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Dual-Engine Search implementation:
    1. Attempts TavilyClient.search() first if TAVILY_API_KEY is available.
    2. If key is missing or Tavily fails/throws an exception, falls back to DDGS().text().
       Includes a random jitter sleep (1.5 - 2.5s) before DDGS call to prevent rate limiting.
    3. Normalizes both outputs into: [{"url": ..., "title": ..., "content": ...}].
    """
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()

    # Engine 1: Tavily Search
    if tavily_key:
        try:
            from tavily import TavilyClient
            tavily = TavilyClient(api_key=tavily_key)
            response = tavily.search(query=query, max_results=max_results, search_depth="basic")
            results = response.get("results", []) if isinstance(response, dict) else []

            normalized = []
            for r in results:
                url = (r.get("url") or "").strip()
                title = (r.get("title") or "").strip()
                content = (r.get("content") or "").strip()
                if url:
                    normalized.append({"url": url, "title": title, "content": content})

            if normalized:
                logger.debug(f"[Search Engine] Tavily returned {len(normalized)} results for query: {query}")
                return normalized
        except Exception as e:
            logger.warning(f"[Search Engine] Tavily error for query '{query}': {e}. Falling back to DuckDuckGo.")

    # Engine 2: DuckDuckGo Fallback
    try:
        from duckduckgo_search import DDGS
        # Jitter delay to prevent aggressive rate limits
        delay = random.uniform(1.5, 2.5)
        time.sleep(delay)

        ddg_results = list(DDGS().text(query, max_results=max_results))
        normalized = []
        for r in ddg_results:
            url = (r.get("href") or "").strip()
            title = (r.get("title") or "").strip()
            content = (r.get("body") or "").strip()
            if url:
                normalized.append({"url": url, "title": title, "content": content})

        logger.debug(f"[Search Engine] DDGS fallback returned {len(normalized)} results for query: {query}")
        return normalized
    except Exception as e:
        logger.error(f"[Search Engine] DuckDuckGo search failed for query '{query}': {e}")
        return []


def _is_valid_dork_job_url(url: str) -> bool:
    """Rejects non-job directory/aggregation URLs from search results."""
    u = url.strip().lower()
    if not u or not u.startswith("http"):
        return False
    # Reject category, directory, or search index pages
    if any(bad in u for bad in [
        "/companies/industry/", "/companies/location/", "/directory/",
        "/topics/", "/tags/", "/search", "/collections/"
    ]):
        return False
    # Reject URLs ending in /jobs or /jobs/ without a job slug
    if re.search(r"/jobs/?$", u):
        return False
    return True


def scrape_dorked_boards() -> List[JobPosting]:
    """
    Channel 3: Uses Dual-Engine Search (Tavily with DDGS fallback) to dork anti-bot job boards
    (Wellfound, YC, Otta, Instahyre) and hydrates full JDs concurrently via Jina Reader.
    """
    discovered_items: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()

    # Step 1: Collect valid job URLs from search dork queries
    for query, source_tag in DORK_QUERIES:
        try:
            logger.info(f"[Search Dorking] Executing query for {source_tag} via Dual-Engine...")
            results = search_dork_engine(query=query, max_results=5)

            for r in results:
                url = r.get("url", "").strip()
                if not url or url in seen_urls:
                    continue
                if not _is_valid_dork_job_url(url):
                    logger.debug(f"[Search Dorking] Skipping non-job URL: {url}")
                    continue

                seen_urls.add(url)
                raw_title = r.get("title", "")
                snippet = r.get("content", "")
                company, role = _parse_title_company(raw_title, url)

                discovered_items.append({
                    "url": url,
                    "company": company,
                    "role": role,
                    "snippet": snippet,
                    "source_tag": source_tag,
                })
        except Exception as e:
            logger.error(f"[Search Dorking] Error processing query '{query}': {e}")

    logger.info(f"[Search Dorking] Discovered {len(discovered_items)} valid job URLs. Hydrating JDs in parallel via Jina...")

    # Step 2: Hydrate full JDs in parallel across workers
    hydrated_jds: Dict[str, str] = {}
    if discovered_items:
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_url = {
                executor.submit(hydrate_full_jd_via_jina, item["url"], item["snippet"]): item["url"]
                for item in discovered_items
            }
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    hydrated_jds[url] = future.result()
                except Exception as e:
                    logger.debug(f"[Jina Parallel] Failed to hydrate {url}: {e}")
                    hydrated_jds[url] = ""

    # Step 3: Construct normalized JobPosting records
    postings: List[JobPosting] = []
    for item in discovered_items:
        url = item["url"]
        company = item["company"]
        role = item["role"]
        full_jd = hydrated_jds.get(url) or item["snippet"] or "No JD content available."

        job_id = generate_job_id(company, role, url)
        postings.append(
            JobPosting(
                job_id=job_id,
                company=company,
                role=role,
                location="India / Remote",
                jd_text=full_jd,
                job_url=url,
                source=item["source_tag"],
                posted_date=None,
            )
        )

    logger.info(f"[Search Dorking] Scraped and hydrated {len(postings)} jobs.")
    return postings


# =====================================================================
# Channel 4: JobSpy Scraper
# =====================================================================

def scrape_linkedin_glassdoor() -> List[JobPosting]:
    """
    Channel 4: Uses python-jobspy to scrape LinkedIn and Glassdoor (strictly excluding Naukri).
    Wraps each search term in try/except so 429 rate-limits don't halt ingestion.
    """
    postings: List[JobPosting] = []
    try:
        from jobspy import scrape_jobs
    except ImportError:
        logger.error("[JobSpy] python-jobspy is not installed. Skipping Channel 4.")
        return []

    search_terms = [
        "AI Engineer",
        "Machine Learning Engineer",
        "GenAI Engineer",
        "Junior AI Engineer",
        "Associate AI Engineer",
        "LLM Engineer",
        "Applied AI Engineer",
    ]

    for term in search_terms:
        try:
            logger.info(f"[JobSpy] Scraping term: '{term}' (LinkedIn, Glassdoor in India)...")
            jobs_df = scrape_jobs(
                site_name=["linkedin", "glassdoor"],
                search_term=term,
                location="India",
                results_wanted=15,
                hours_old=48,
                fetch_description=True,
            )

            if jobs_df is None or jobs_df.empty:
                continue

            for _, row in jobs_df.iterrows():
                company = str(row.get("company", "") or "Unknown Company").strip()
                title = str(row.get("title", "") or term).strip()
                loc = str(row.get("location", "") or "India").strip()
                desc = str(row.get("description", "") or "").strip()
                job_url = str(row.get("job_url", "") or "").strip()
                site = str(row.get("site", "") or "jobspy").lower()
                date_posted = str(row.get("date_posted", "") or "")

                if not job_url:
                    continue

                clean_jd = clean_html_to_text(desc)
                job_id = generate_job_id(company, title, job_url)

                postings.append(
                    JobPosting(
                        job_id=job_id,
                        company=company,
                        role=title,
                        location=loc,
                        jd_text=clean_jd,
                        job_url=job_url,
                        source=site,
                        posted_date=date_posted if date_posted else None,
                    )
                )
        except Exception as e:
            logger.warning(f"[JobSpy] Caught error/rate-limit scraping '{term}': {e}")

    logger.info(f"[JobSpy] Scraped {len(postings)} jobs across LinkedIn and Glassdoor.")
    return postings


# =====================================================================
# Master Orchestrator
# =====================================================================

def run_all_scrapers() -> List[JobPosting]:
    """
    Executes all 4 channels, logs counts per channel, deduplicates in-memory by
    job_id and normalized (company, role), and returns the unified List[JobPosting].
    """
    logger.info("=== Starting Master Ingestion Orchestrator (4 Channels) ===")

    wwr_jobs = scrape_wwr_rss()
    api_jobs = scrape_public_json_apis()
    dork_jobs = scrape_dorked_boards()
    jobspy_jobs = scrape_linkedin_glassdoor()

    all_raw = wwr_jobs + api_jobs + dork_jobs + jobspy_jobs
    logger.info(
        f"[Summary] Raw gathered: {len(all_raw)} "
        f"(WWR: {len(wwr_jobs)}, APIs: {len(api_jobs)}, Dorks: {len(dork_jobs)}, JobSpy: {len(jobspy_jobs)})"
    )

    seen_ids: Set[str] = set()
    seen_tuples: Set[tuple] = set()
    deduped: List[JobPosting] = []

    for job in all_raw:
        norm_key = (job.company.strip().lower(), job.role.strip().lower())
        if job.job_id in seen_ids or norm_key in seen_tuples:
            continue
        seen_ids.add(job.job_id)
        seen_tuples.add(norm_key)
        deduped.append(job)

    logger.info(f"[Summary] Deduplicated in-memory: {len(deduped)} unique jobs.")
    return deduped
