"""
Direct Human Email Discovery via Hunter.io API & Deterministic Permutations.
"""

import os
import re
import logging
from typing import Dict, Any, Optional
from urllib.parse import urlparse
from dotenv import load_dotenv
import httpx

load_dotenv()

logger = logging.getLogger("utils.email_hunter")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def clean_domain_from_company(company: str, job_url: str = "") -> str:
    """
    Extracts or normalizes a domain for a company.
    If job_url points to a company website, extracts domain.
    Otherwise derives clean domain from company name (e.g. Swiggy -> swiggy.com, Cred -> cred.club).
    """
    if job_url:
        parsed = urlparse(job_url)
        netloc = parsed.netloc.lower()
        # Exclude general job boards
        if not any(b in netloc for b in [
            "linkedin.com", "greenhouse.io", "lever.co", "ashbyhq.com",
            "wellfound.com", "workatastartup.com", "instahyre.com",
            "himalayas.app", "glassdoor.com", "naukri.com"
        ]):
            # Strip www.
            clean = re.sub(r"^www\.", "", netloc)
            if clean and "." in clean:
                return clean

    # Known startup domain overrides
    clean_comp = re.sub(r"[^a-zA-Z0-9]+", "", company.lower())
    domain_overrides = {
        "cred": "cred.club",
        "swiggy": "swiggy.in",
        "zomato": "zomato.com",
        "urbancompany": "urbancompany.com",
        "meesho": "meesho.com",
        "groww": "groww.in",
        "razorpay": "razorpay.com",
        "postman": "postman.com",
        "zepto": "zeptonow.com",
        "blinkit": "blinkit.com",
        "ola": "olacabs.com",
        "paytm": "paytm.com",
    }
    if clean_comp in domain_overrides:
        return domain_overrides[clean_comp]

    return f"{clean_comp}.com"


def find_direct_email(first_name: str, last_name: str, company_domain: str) -> Dict[str, Any]:
    """
    Discovers direct human email address for a verified employee:
    1. If HUNTER_API_KEY is configured in .env, calls Hunter.io Email Finder API.
       If confidence score >= 70, returns {"email": email, "score": score, "status": "VERIFIED"}.
    2. If no key or API miss / score < 70, falls back to deterministic human permutations:
       {"email": "{first}.{last}@{domain}", "alt_email": "{first}@{domain}", "status": "PATTERN_GUESS"}.

    Never outputs generic careers@, info@, or hr@ emails.
    """
    first = (first_name or "").strip().lower()
    last = (last_name or "").strip().lower()
    domain = (company_domain or "").strip().lower()

    # Sanitize names (alphanumeric only)
    first = re.sub(r"[^a-z0-9]", "", first)
    last = re.sub(r"[^a-z0-9]", "", last)

    if not first:
        first = "team"
    if not domain:
        domain = "company.com"

    # Default pattern guess permutations
    if last:
        primary_pattern = f"{first}.{last}@{domain}"
        alt_pattern = f"{first}@{domain}"
    else:
        primary_pattern = f"{first}@{domain}"
        alt_pattern = f"{first}.work@{domain}"

    hunter_key = os.getenv("HUNTER_API_KEY", "").strip()

    if hunter_key:
        try:
            api_url = "https://api.hunter.io/v2/email-finder"
            params = {
                "domain": domain,
                "first_name": first,
                "last_name": last,
                "api_key": hunter_key,
            }
            logger.info(f"[Hunter.io] Querying direct email for {first} {last} @ {domain}...")
            with httpx.Client(timeout=6.0) as client:
                resp = client.get(api_url, params=params)
                if resp.status_code == 200:
                    payload = resp.json().get("data", {})
                    found_email = payload.get("email")
                    score = payload.get("score", 0)

                    if found_email and score >= 70:
                        logger.info(f"[Hunter.io] VERIFIED email found: {found_email} (score: {score})")
                        return {
                            "email": found_email,
                            "score": score,
                            "status": "VERIFIED",
                        }
                    else:
                        logger.debug(f"[Hunter.io] Email score {score} < 70 for {first} {last} @ {domain}")
                else:
                    logger.debug(f"[Hunter.io] HTTP {resp.status_code} from Hunter.io")
        except Exception as e:
            logger.warning(f"[Hunter.io] API call failed: {e}. Falling back to pattern guess.")

    logger.debug(f"[Email Discovery] Generated pattern guess: {primary_pattern}")
    return {
        "email": primary_pattern,
        "alt_email": alt_pattern,
        "score": 50,
        "status": "PATTERN_GUESS",
    }
