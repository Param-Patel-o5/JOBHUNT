"""
Compatibility wrapper for gatekeeper.py -> forwards to filter.py.
"""

from src.nodes.filter import (
    filter_jobs,
    load_profile_context,
    is_valid_location,
    extract_required_yoe,
    extract_min_yoe,
    is_valid_role_title,
    PROFILE_PATH,
    DEFAULT_SCAM_BODY_SHOPS,
    RLHF_PLATFORMS,
    CONTRACT_RLHF_REGEX,
    SENIOR_LEADERSHIP_REGEX,
    AI_CORE_REGEX,
    GEO_RESTRICTION_REGEX,
)

__all__ = [
    "filter_jobs",
    "load_profile_context",
    "is_valid_location",
    "extract_required_yoe",
    "extract_min_yoe",
    "is_valid_role_title",
    "PROFILE_PATH",
    "DEFAULT_SCAM_BODY_SHOPS",
    "RLHF_PLATFORMS",
    "CONTRACT_RLHF_REGEX",
    "SENIOR_LEADERSHIP_REGEX",
    "AI_CORE_REGEX",
    "GEO_RESTRICTION_REGEX",
]
