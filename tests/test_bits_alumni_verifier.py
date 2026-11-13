"""
Unit tests for BITS Pilani Alumni Verifier.
Validates strict distinction between genuine campus alumni, WILP/certifications, and BIT Mesra.
"""

import pytest
from src.utils.bits_alumni_verifier import verify_bits_alumni


def test_genuine_campus_alumni():
    # Pilani campus
    is_alum, reason = verify_bits_alumni(
        "Software Engineer 3 at Comcast | BITS Pilani CS '22",
        "Experience: Comcast · Education: BITS Pilani · Location: Bengaluru"
    )
    assert is_alum is True
    assert "Verified" in reason

    # Goa campus
    is_alum, reason = verify_bits_alumni(
        "AI Engineer @ NetApp | BITS Goa '21",
        "Graduated from BITS Pilani, K K Birla Goa Campus with B.E. Computer Science"
    )
    assert is_alum is True
    assert "Verified" in reason

    # Hyderabad / BPHC campus
    is_alum, reason = verify_bits_alumni(
        "MTS at Salesforce | BPHC '23",
        "Education: Birla Institute of Technology and Science, Pilani - Hyderabad Campus"
    )
    assert is_alum is True
    assert "Verified" in reason


def test_rejects_bit_mesra():
    # BIT Mesra (Birla Institute of Technology) - NOT BITS Pilani
    is_alum, reason = verify_bits_alumni(
        "Engineer at Cencora | Birla Institute of Technology",
        "Education: Birla Institute of Technology, Mesra · Ranchi, Jharkhand"
    )
    assert is_alum is False
    assert "Rejected" in reason


def test_rejects_wilp_and_certifications():
    # Corporate WILP off-campus MTech
    is_alum, reason = verify_bits_alumni(
        "Associate Software Engineer at Optum || MTech in Software Engineering from BITS Pilani",
        "MTech from BITS Pilani Work Integrated Learning Programmes (WILP)"
    )
    assert is_alum is False
    assert "Rejected" in reason

    # Post Graduate Certificate / Executive
    is_alum, reason = verify_bits_alumni(
        "Data Scientist | BITS Pilani Post Graduate Certificate in AI/ML",
        "Completed 11-month executive certificate programme from BITS Pilani"
    )
    assert is_alum is False
    assert "Rejected" in reason

    # Databricks Certified / only cert context
    is_alum, reason = verify_bits_alumni(
        "Senior Cloud Architect | AWS Certified | BITS Pilani Certified",
        "Experience: Solutions Architect at Wipro"
    )
    assert is_alum is False
    assert "Rejected" in reason


def test_rejects_unrelated_profiles():
    is_alum, reason = verify_bits_alumni(
        "Software Engineer at Google | IIT Bombay",
        "Education: Indian Institute of Technology Bombay"
    )
    assert is_alum is False
    assert "Rejected" in reason

