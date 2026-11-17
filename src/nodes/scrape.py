"""
Node 1: Balanced 4-Channel OSINT Job Scraper (scrape.py).

Architecture:
  - Channel 1: LinkedIn Jobs (JobSpy + Dual-Engine search fallback with negative constraints: -Intern -Senior).
  - Channel 2: Y Combinator Work at a Startup (Dual-Engine dorking + Jina Reader hydration).
  - Channel 3: Wellfound / AngelList (Dual-Engine dorking + Jina Reader hydration).
  - Channel 4: BuiltInBengaluru / Instahyre / Himalayas (India-focused tech discovery + India ATS boards).
  - Clean Job ID Extraction: Extracts clean platform Job ID (e.g. LinkedIn numeric ID, Greenhouse ID, slug).
  - Company Flood Cap & Deduplication: Deduplicates normalized (company, title) and limits to max 2 roles
    per company per scrape run.
"""

import os
import re
import html
import time
import random
import hashlib
import logging
from typing import List, Optional, Set, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import httpx

from src.models import JobPosting
from src.utils.company_matcher import normalize_company_name

load_dotenv()

logger = logging.getLogger("ingestion.scrape")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


# =====================================================================
# Utilities: Clean Text & Job ID Extraction
# =====================================================================

def clean_html_to_text(raw_html: str) -> str:
    """Cleanly strip HTML tags and decode HTML entities using standard library html and re."""
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<(?:br\s*/?|p|div|li|tr|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join([line for line in lines if line]).strip()


def extract_clean_job_id(url: str, company: str = "", role: str = "") -> str:
    """
    Extracts a human-usable platform Job ID or clean slug from job URL.
    This enables the candidate to provide the exact numeric or slug Job ID
    when asking contacts for referrals.

    Examples:
      - LinkedIn: https://www.linkedin.com/jobs/view/4487742567/ -> "4487742567"
      - Greenhouse: https://boards.greenhouse.io/swiggy/jobs/6543210 -> "6543210"
      - Lever: https://jobs.lever.co/palantir/5c23a7bb-1e42... -> "5c23a7bb"
      - Ashby: https://jobs.ashbyhq.com/company/a7b8c9d0-1234... -> "a7b8c9d0"
      - Wellfound: https://wellfound.com/jobs/3456789-ai-engineer -> "3456789"
      - Work at a Startup: https://www.workatastartup.com/jobs/56789 -> "56789"
      - Instahyre: https://www.instahyre.com/job-123456-ai-engineer/ -> "123456"
      - Himalayas: https://himalayas.app/companies/acme/jobs/ml-eng-123 -> "ml-eng-123"
    Fallback:
      - 10-character deterministic MD5 hash.
    """
    if not url:
        raw = f"{company.strip().lower()}|{role.strip().lower()}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]

    u = url.strip()

    # 1. LinkedIn numeric job ID (typically 9-11 digits)
    m_li = re.search(r"(?:linkedin\.com/jobs/view/(?:[a-zA-Z0-9_%-]+-)?|currentJobId=)([0-9]{8,12})", u)
    if m_li:
        return m_li.group(1)

    # 2. Greenhouse numeric job ID
    m_gh = re.search(r"greenhouse\.io/(?:[^/]+/)?jobs/([0-9]+)", u)
    if m_gh:
        return m_gh.group(1)

    # 3. Lever 8-char hex slug / UUID
    m_lev = re.search(r"jobs\.lever\.co/[^/]+/([a-f0-9]{8})(?:-[a-f0-9-]+)?", u)
    if m_lev:
        return m_lev.group(1)

    # 4. Ashby slug / UUID
    m_ash = re.search(r"jobs\.ashbyhq\.com/[^/]+/([a-zA-Z0-9_-]{6,36})", u)
    if m_ash:
        return m_ash.group(1)[:8]

    # 5. Y Combinator (Work at a Startup) numeric job ID
    m_yc = re.search(r"workatastartup\.com/(?:companies/[^/]+/)?jobs/([0-9]+)", u)
    if m_yc:
        return m_yc.group(1)

    # 6. Wellfound (AngelList) numeric job ID
    m_wf = re.search(r"wellfound\.com/jobs/([0-9]+)", u)
    if m_wf:
        return m_wf.group(1)

    # 7. Instahyre numeric job ID
    m_insta = re.search(r"instahyre\.com/job-([0-9]+)", u)
    if m_insta:
        return m_insta.group(1)

    # 8. Himalayas slug
    m_him = re.search(r"himalayas\.app/companies/[^/]+/jobs/([a-zA-Z0-9_-]+)", u)
    if m_him:
        return m_him.group(1)[:12]

    # Fallback: deterministic 10-char MD5
    raw = f"{company.strip().lower()}|{role.strip().lower()}|{u.lower()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]


def generate_job_id(company: str, role: str, url: str) -> str:
    """Backward-compatible alias for extract_clean_job_id."""
    return extract_clean_job_id(url, company, role)


def _parse_title_company(title: str, url: str) -> Tuple[str, str]:
    """Helper to extract clean (company, role) from a search result title or URL."""
    clean = title.strip()
    # Remove trailing site branding
    clean = re.sub(
        r"\s*[|·•]\s*(?:LinkedIn|Wellfound|Work at a Startup|Y Combinator|Instahyre|Built In Bengaluru|Himalayas|Glassdoor).*$",
        "", clean, flags=re.I
    )
    clean = re.sub(
        r"\s*-\s*(?:LinkedIn|Wellfound|Work at a Startup|Y Combinator|Instahyre|Built In Bengaluru|Himalayas|Glassdoor).*$",
        "", clean, flags=re.I
    )
    # Remove trailing location
    clean = re.sub(
        r"\s+in\s+(?:Bengaluru|Bangalore|Hyderabad|Pune|Mumbai|Gurugram|Gurgaon|Noida|Chennai|Delhi|India)(?:[,\s]+[a-zA-Z\s]+)*$",
        "", clean, flags=re.I
    )

    # Format: "Company hiring Role" or "Company is hiring a Role"
    m_hiring = re.search(r"^(.*?)\s+(?:is\s+)?hiring\s+(?:a\s+|an\s+)?(.*)$", clean, re.IGNORECASE)
    if m_hiring:
        comp = m_hiring.group(1).strip()
        role = m_hiring.group(2).strip()
        return comp, role

    # Format: "Role at Company"
    if " at " in clean:
        parts = clean.split(" at ", 1)
        role = re.sub(r"\s+Job\b", "", parts[0], flags=re.I).strip()
        comp = parts[1].strip()
        return comp, role

    # Format: "Role - Company" or "Company - Role"
    if " - " in clean:
        parts = clean.split(" - ", 1)
        first_lower = parts[0].lower()
        if any(kw in first_lower for kw in ["engineer", "developer", "scientist", "analyst", "ai", "ml", "specialist"]):
            return parts[1].strip(), parts[0].strip()
        else:
            return parts[0].strip(), parts[1].strip()

    if ":" in clean:
        parts = clean.split(":", 1)
        return parts[0].strip(), parts[1].strip()

    # Fallback to URL hints
    comp_guess = "Tech Startup"
    if "instahyre.com" in url:
        m = re.search(r"-at-([a-zA-Z0-9_-]+)", url)
        if m:
            comp_guess = m.group(1).replace("-", " ").title()
    elif "workatastartup.com/companies/" in url:
        m = re.search(r"workatastartup\.com/companies/([a-zA-Z0-9_-]+)", url)
        if m:
            comp_guess = m.group(1).replace("-", " ").title()
    elif "wellfound.com/company/" in url:
        m = re.search(r"wellfound\.com/company/([a-zA-Z0-9_-]+)", url)
        if m:
            comp_guess = m.group(1).replace("-", " ").title()

    return comp_guess, clean.strip()


# =====================================================================
# Search & Hydration Infrastructure
# =====================================================================

def search_dork_engine(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Dual-Engine Search implementation:
    1. Attempts TavilyClient.search() first if TAVILY_API_KEY is available.
    2. Falls back to DDGS().text() with random jitter (1.2 - 2.0s).
    3. Normalizes both outputs into: [{"url": ..., "title": ..., "content": ...}].
    """
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()

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
            logger.warning(f"[Search Engine] Tavily query '{query}' failed: {e}. Falling back to DuckDuckGo.")

    try:
        from duckduckgo_search import DDGS
        time.sleep(random.uniform(1.2, 2.0))
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
        logger.error(f"[Search Engine] DDGS search failed for query '{query}': {e}")
        return []


def hydrate_full_jd_via_jina(url: str, fallback_snippet: str) -> str:
    """
    Hydrates full JD text using Jina Reader (https://r.jina.ai/).
    Bypasses Cloudflare on Wellfound / Work at a Startup and returns markdown content.
    Falls back cleanly to the search snippet if Jina fails or returns <200 chars.
    """
    jina_url = f"https://r.jina.ai/{url}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
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


def _is_valid_dork_job_url(url: str) -> bool:
    """Rejects category, tag, or directory index URLs from search results."""
    u = url.strip().lower()
    if not u or not u.startswith("http"):
        return False
    if any(bad in u for bad in [
        "/companies/industry/", "/companies/location/", "/directory/",
        "/topics/", "/tags/", "/search", "/collections/", "/categories/"
    ]):
        return False
    if re.search(r"/(?:jobs|careers)/?$", u):
        return False
    return True


# =====================================================================
# Channel 1: LinkedIn Jobs (JobSpy + Targeted Search Dork Fallback)
# =====================================================================

def scrape_channel_linkedin() -> List[JobPosting]:
    """
    Channel 1: Scrapes LinkedIn jobs using python-jobspy with targeted queries,
    exact quotes, India location constraints, and senior/intern exclusions.
    Includes a search dorking fallback if JobSpy encounters 429 rate limits.
    """
    postings: List[JobPosting] = []

    # 1. JobSpy Engine
    try:
        from jobspy import scrape_jobs
        search_terms = [
            '"AI Engineer" -Senior -Intern -Staff -Principal',
            '"Machine Learning Engineer" -Senior -Intern -Staff -Principal',
            '"Data Scientist" -Senior -Intern -Staff -Principal',
            '"GenAI Engineer" -Senior -Intern -Staff -Principal',
            '"LLM Engineer" -Senior -Intern -Staff -Principal',
        ]
        locations = ["India", "Bengaluru", "Hyderabad", "Pune"]

        for term in search_terms:
            for loc in locations[:2]:  # focus on India & Bengaluru
                try:
                    logger.info(f"[Channel 1: LinkedIn] Scraping term '{term}' in '{loc}' via JobSpy...")
                    jobs_df = scrape_jobs(
                        site_name=["linkedin"],
                        search_term=term,
                        location=loc,
                        results_wanted=10,
                        hours_old=72,
                        fetch_description=True,
                    )
                    if jobs_df is None or jobs_df.empty:
                        continue

                    for _, row in jobs_df.iterrows():
                        company = str(row.get("company", "") or "Tech Company").strip()
                        title = str(row.get("title", "") or term).strip()
                        location = str(row.get("location", "") or loc).strip()
                        desc = str(row.get("description", "") or "").strip()
                        job_url = str(row.get("job_url", "") or "").strip()
                        date_posted = str(row.get("date_posted", "") or "")

                        if not job_url:
                            continue

                        clean_jd = clean_html_to_text(desc)
                        job_id = extract_clean_job_id(job_url, company, title)

                        postings.append(
                            JobPosting(
                                job_id=job_id,
                                company=company,
                                role=title,
                                location=location,
                                jd_text=clean_jd,
                                job_url=job_url,
                                source="linkedin",
                                posted_date=date_posted if date_posted else None,
                            )
                        )
                except Exception as e:
                    logger.warning(f"[Channel 1: LinkedIn] JobSpy error for '{term}': {e}")
    except ImportError:
        logger.warning("[Channel 1: LinkedIn] python-jobspy not available. Relying on dork fallback.")

    # 2. LinkedIn Search Dork Fallback (Guarantees fresh results if JobSpy hits 429 rate-limits)
    if len(postings) < 5:
        dork_query = (
            'site:linkedin.com/jobs/view ("AI Engineer" OR "Machine Learning Engineer" OR "Data Scientist" OR "GenAI Engineer" OR "LLM Engineer") '
            '("India" OR "Bengaluru" OR "Hyderabad" OR "Pune") -Intern -Internship -Senior -Staff -Principal'
        )
        logger.info("[Channel 1: LinkedIn] Running targeted search dork fallback for LinkedIn...")
        try:
            dork_results = search_dork_engine(dork_query, max_results=6)
            for r in dork_results:
                url = r.get("url", "").strip()
                if not url or "linkedin.com/jobs/view" not in url:
                    continue
                comp, role = _parse_title_company(r.get("title", ""), url)
                snippet = r.get("content", "")
                job_id = extract_clean_job_id(url, comp, role)
                postings.append(
                    JobPosting(
                        job_id=job_id,
                        company=comp,
                        role=role,
                        location="India / Bengaluru",
                        jd_text=snippet,
                        job_url=url,
                        source="linkedin",
                        posted_date=None,
                    )
                )
        except Exception as e:
            logger.error(f"[Channel 1: LinkedIn] Dork fallback failed: {e}")

    logger.info(f"[Channel 1: LinkedIn] Gathered {len(postings)} jobs.")
    return postings


# =====================================================================
# Channel 2: Y Combinator (Work at a Startup)
# =====================================================================

def scrape_channel_ycombinator() -> List[JobPosting]:
    """
    Channel 2: Scrapes Y Combinator's official startup hiring portal (workatastartup.com)
    using targeted India queries and Jina Reader hydration.
    """
    queries = [
        'site:workatastartup.com ("AI" OR "Machine Learning" OR "LLM") ("India" OR "Bengaluru" OR "Bangalore" OR "Hyderabad")',
        'site:workatastartup.com/jobs ("AI Engineer" OR "Machine Learning" OR "Data Scientist") ("India" OR "Remote")',
    ]
    discovered_items: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()

    for q in queries:
        try:
            logger.info(f"[Channel 2: YC] Executing query: {q}")
            results = search_dork_engine(q, max_results=6)
            for r in results:
                url = r.get("url", "").strip()
                if not url or url in seen_urls:
                    continue
                if not _is_valid_dork_job_url(url):
                    continue
                seen_urls.add(url)
                comp, role = _parse_title_company(r.get("title", ""), url)
                discovered_items.append({
                    "url": url,
                    "company": comp,
                    "role": role,
                    "snippet": r.get("content", ""),
                })
        except Exception as e:
            logger.error(f"[Channel 2: YC] Error querying '{q}': {e}")

    # Hydrate in parallel via Jina
    hydrated: Dict[str, str] = {}
    if discovered_items:
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_url = {
                executor.submit(hydrate_full_jd_via_jina, item["url"], item["snippet"]): item["url"]
                for item in discovered_items
            }
            for future in as_completed(future_to_url):
                u = future_to_url[future]
                try:
                    hydrated[u] = future.result()
                except Exception:
                    hydrated[u] = ""

    postings: List[JobPosting] = []
    for item in discovered_items:
        url = item["url"]
        comp = item["company"]
        role = item["role"]
        full_jd = hydrated.get(url) or item["snippet"] or "YC Startup AI role."
        job_id = extract_clean_job_id(url, comp, role)

        postings.append(
            JobPosting(
                job_id=job_id,
                company=comp,
                role=role,
                location="Bengaluru / India (YC)",
                jd_text=full_jd,
                job_url=url,
                source="ycombinator",
                posted_date=None,
            )
        )

    logger.info(f"[Channel 2: YC] Gathered {len(postings)} jobs.")
    return postings


# =====================================================================
# Channel 3: Wellfound (formerly AngelList)
# =====================================================================

def scrape_channel_wellfound() -> List[JobPosting]:
    """
    Channel 3: Scrapes Wellfound startup job postings using dual-engine search dorking
    and Jina Reader hydration.
    """
    queries = [
        'site:wellfound.com/jobs ("AI Engineer" OR "Machine Learning" OR "Data Scientist") ("India" OR "Bangalore" OR "Hyderabad" OR "Bengaluru")',
        'site:wellfound.com/jobs ("LLM" OR "GenAI" OR "Artificial Intelligence") ("India" OR "Bengaluru")',
    ]
    discovered_items: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()

    for q in queries:
        try:
            logger.info(f"[Channel 3: Wellfound] Executing query: {q}")
            results = search_dork_engine(q, max_results=6)
            for r in results:
                url = r.get("url", "").strip()
                if not url or url in seen_urls:
                    continue
                if not _is_valid_dork_job_url(url):
                    continue
                seen_urls.add(url)
                comp, role = _parse_title_company(r.get("title", ""), url)
                discovered_items.append({
                    "url": url,
                    "company": comp,
                    "role": role,
                    "snippet": r.get("content", ""),
                })
        except Exception as e:
            logger.error(f"[Channel 3: Wellfound] Error querying '{q}': {e}")

    # Hydrate in parallel via Jina
    hydrated: Dict[str, str] = {}
    if discovered_items:
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_url = {
                executor.submit(hydrate_full_jd_via_jina, item["url"], item["snippet"]): item["url"]
                for item in discovered_items
            }
            for future in as_completed(future_to_url):
                u = future_to_url[future]
                try:
                    hydrated[u] = future.result()
                except Exception:
                    hydrated[u] = ""

    postings: List[JobPosting] = []
    for item in discovered_items:
        url = item["url"]
        comp = item["company"]
        role = item["role"]
        full_jd = hydrated.get(url) or item["snippet"] or "Wellfound Startup AI role."
        job_id = extract_clean_job_id(url, comp, role)

        postings.append(
            JobPosting(
                job_id=job_id,
                company=comp,
                role=role,
                location="Bengaluru / India",
                jd_text=full_jd,
                job_url=url,
                source="wellfound",
                posted_date=None,
            )
        )

    logger.info(f"[Channel 3: Wellfound] Gathered {len(postings)} jobs.")
    return postings


# =====================================================================
# Channel 4: BuiltInBengaluru / Instahyre / Himalayas (India Tech)
# =====================================================================

def scrape_channel_india_tech() -> List[JobPosting]:
    """
    Channel 4: India-focused startup and tech boards:
    1. Instahyre & BuiltInBengaluru search dorking.
    2. Himalayas API filtered strictly for India.
    3. Curated top India ATS boards (Greenhouse/Ashby/Lever for India tech).
    """
    postings: List[JobPosting] = []

    # 1. Instahyre & BuiltInBengaluru Search Dorks
    queries = [
        '(site:instahyre.com OR site:builtinbengaluru.com OR site:himalayas.app) ("AI Engineer" OR "Machine Learning" OR "LLM" OR "Data Scientist") ("Bengaluru" OR "Hyderabad" OR "India")',
        'site:instahyre.com/job ("AI Engineer" OR "Machine Learning" OR "LLM") ("Bengaluru" OR "India")',
        'site:builtinbengaluru.com ("AI Engineer" OR "Machine Learning" OR "Data Scientist")',
    ]
    discovered_items: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()

    for q in queries:
        try:
            logger.info(f"[Channel 4: India Tech] Executing query: {q}")
            results = search_dork_engine(q, max_results=6)
            for r in results:
                url = r.get("url", "").strip()
                if not url or url in seen_urls:
                    continue
                if not _is_valid_dork_job_url(url):
                    continue
                seen_urls.add(url)
                comp, role = _parse_title_company(r.get("title", ""), url)
                discovered_items.append({
                    "url": url,
                    "company": comp,
                    "role": role,
                    "snippet": r.get("content", ""),
                })
        except Exception as e:
            logger.error(f"[Channel 4: India Tech] Dork failed for '{q}': {e}")

    # Hydrate in parallel via Jina
    hydrated: Dict[str, str] = {}
    if discovered_items:
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_url = {
                executor.submit(hydrate_full_jd_via_jina, item["url"], item["snippet"]): item["url"]
                for item in discovered_items
            }
            for future in as_completed(future_to_url):
                u = future_to_url[future]
                try:
                    hydrated[u] = future.result()
                except Exception:
                    hydrated[u] = ""

    for item in discovered_items:
        url = item["url"]
        comp = item["company"]
        role = item["role"]
        full_jd = hydrated.get(url) or item["snippet"] or "India tech AI role."
        job_id = extract_clean_job_id(url, comp, role)
        src = "instahyre" if "instahyre.com" in url else ("builtinbengaluru" if "builtinbengaluru.com" in url else "india_tech")

        postings.append(
            JobPosting(
                job_id=job_id,
                company=comp,
                role=role,
                location="Bengaluru / India",
                jd_text=full_jd,
                job_url=url,
                source=src,
                posted_date=None,
            )
        )

    # 2. Himalayas Direct API (strictly requiring India eligibility)
    try:
        with httpx.Client(timeout=10.0) as client:
            h_url = "https://himalayas.app/jobs/api/search"
            for q_term in ["AI Engineer", "Machine Learning", "GenAI"]:
                resp = client.get(h_url, params={"q": q_term, "seniority": "Entry-level,Mid-level"})
                if resp.status_code == 200:
                    data = resp.json().get("jobs", [])
                    for j in data:
                        loc_res = [str(x).lower() for x in j.get("locationRestrictions", [])]
                        # Only keep if India is explicitly in location restrictions
                        if not any("india" in x for x in loc_res):
                            continue
                        comp = j.get("companyName", "").strip()
                        title = j.get("title", "").strip()
                        app_link = j.get("applicationLink") or j.get("guid") or ""
                        if not app_link:
                            continue
                        clean_jd = clean_html_to_text(j.get("description", ""))
                        job_id = extract_clean_job_id(app_link, comp, title)
                        postings.append(
                            JobPosting(
                                job_id=job_id,
                                company=comp,
                                role=title,
                                location="Remote - India",
                                jd_text=clean_jd,
                                job_url=app_link,
                                source="himalayas",
                                posted_date=str(j.get("pubDate") or ""),
                            )
                        )
    except Exception as e:
        logger.debug(f"[Channel 4: India Tech] Himalayas API skipped: {e}")

    # 3. Targeted India ATS Boards (Greenhouse/Ashby for high-growth tech firms in India)
    india_ats_slugs = [
        ("swiggy", "greenhouse"),
        ("cred", "greenhouse"),
        ("groww", "greenhouse"),
        ("meesho", "greenhouse"),
        ("postman", "greenhouse"),
        ("razorpay", "greenhouse"),
        ("urbancompany", "greenhouse"),
        ("mistral", "ashby"),
        ("anysphere", "ashby"),
        ("baseten", "ashby"),
    ]
    with httpx.Client(timeout=8.0) as client:
        for slug, board_type in india_ats_slugs:
            try:
                if board_type == "greenhouse":
                    api_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
                    r_ats = client.get(api_url)
                    if r_ats.status_code == 200:
                        jobs = r_ats.json().get("jobs", [])
                        for j in jobs:
                            title = j.get("title", "").strip()
                            t_lower = title.lower()
                            if not any(k in t_lower for k in ["ai", "machine learning", "ml", "llm", "data scientist", "deep learning"]):
                                continue
                            app_url = j.get("absolute_url", "")
                            if not app_url:
                                continue
                            loc_name = str(j.get("location", {}).get("name", ""))
                            # Filter for India locations
                            if not any(c in loc_name.lower() for c in ["india", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "gurugram", "remote"]):
                                continue
                            clean_jd = clean_html_to_text(j.get("content", ""))
                            job_id = extract_clean_job_id(app_url, slug.title(), title)
                            postings.append(
                                JobPosting(
                                    job_id=job_id,
                                    company=slug.title(),
                                    role=title,
                                    location=loc_name or "Bengaluru, India",
                                    jd_text=clean_jd,
                                    job_url=app_url,
                                    source="greenhouse",
                                    posted_date=None,
                                )
                            )
            except Exception:
                pass

    logger.info(f"[Channel 4: India Tech] Gathered {len(postings)} jobs.")
    return postings


# =====================================================================
# Per-Company Flood Cap & In-Memory Deduplication
# =====================================================================

def deduplicate_and_cap_jobs(raw_jobs: List[JobPosting], max_per_company: int = 2) -> List[JobPosting]:
    """
    Deduplicates raw postings across all 4 channels and applies a strict per-company flood cap.
    - Normalizes company_name (strips Inc/Ltd/Pvt/Technologies/etc.) and normalized role title.
    - Limits to a maximum of `max_per_company` (default 2) open roles per company per scrape run.
    """
    seen_ids: Set[str] = set()
    seen_company_role: Set[Tuple[str, str]] = set()
    company_counts: Dict[str, int] = {}
    deduped: List[JobPosting] = []

    for job in raw_jobs:
        if not job or not job.job_url:
            continue

        # Canonical normalization of company name
        norm_company, _ = normalize_company_name(job.company)
        norm_company = norm_company.strip().lower() or job.company.strip().lower()

        # Normalized role title
        norm_role = re.sub(r"[^a-z0-9]+", " ", job.role.strip().lower()).strip()

        # Deduplication check
        dedup_tuple = (norm_company, norm_role)
        if job.job_id in seen_ids or dedup_tuple in seen_company_role:
            logger.debug(f"[Scraper Dedup] Skipping duplicate: {job.company} - {job.role}")
            continue

        # Company Flood Cap: max 2 roles per company per run
        current_count = company_counts.get(norm_company, 0)
        if current_count >= max_per_company:
            logger.info(
                f"[Company Flood Cap] Dropping extra role for '{job.company}' "
                f"(already reached cap of {max_per_company} roles): '{job.role}'"
            )
            continue

        seen_ids.add(job.job_id)
        seen_company_role.add(dedup_tuple)
        company_counts[norm_company] = current_count + 1
        deduped.append(job)

    logger.info(
        f"[Scraper Orchestrator] Processed {len(raw_jobs)} raw jobs -> {len(deduped)} deduplicated jobs "
        f"(max {max_per_company} roles/company enforced across {len(company_counts)} unique companies)."
    )
    return deduped


# =====================================================================
# Master Ingestion Orchestrator
# =====================================================================

def run_all_scrapers(max_per_company: int = 2) -> List[JobPosting]:
    """
    Executes all 4 balanced channels:
      Channel 1: LinkedIn Jobs (India targeted + negative filters)
      Channel 2: Y Combinator Work at a Startup
      Channel 3: Wellfound (AngelList)
      Channel 4: BuiltInBengaluru / Instahyre / Himalayas (India Tech)

    Applies clean Job ID extraction and enforces max 2 roles per company.
    """
    logger.info("=== Starting Balanced 4-Channel Ingestion Orchestrator ===")

    linkedin_jobs = scrape_channel_linkedin()
    yc_jobs = scrape_channel_ycombinator()
    wellfound_jobs = scrape_channel_wellfound()
    india_tech_jobs = scrape_channel_india_tech()

    all_raw = linkedin_jobs + yc_jobs + wellfound_jobs + india_tech_jobs
    logger.info(
        f"[Channel Breakdown] Total Raw Gathered: {len(all_raw)} | "
        f"LinkedIn: {len(linkedin_jobs)}, YC: {len(yc_jobs)}, "
        f"Wellfound: {len(wellfound_jobs)}, India Tech: {len(india_tech_jobs)}"
    )

    final_jobs = deduplicate_and_cap_jobs(all_raw, max_per_company=max_per_company)
    return final_jobs
