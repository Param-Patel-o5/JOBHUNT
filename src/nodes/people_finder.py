"""
Compatibility wrapper for people_finder.py -> forwards to enrich.py.
"""

from src.nodes.enrich import (
    find_contacts_for_company,
    find_hr_email_for_company,
    parse_linkedin_search_result,
    clear_contacts_cache,
)

__all__ = [
    "find_contacts_for_company",
    "find_hr_email_for_company",
    "parse_linkedin_search_result",
    "clear_contacts_cache",
]
