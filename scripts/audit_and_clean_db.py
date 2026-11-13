"""
Database Audit & Cleanup Script for JobHunt OS.
Re-verifies all contacts against strict BITS alumni criteria and sanitizes drafted outreach messages.
"""

import sqlite3
import json
import re
from pathlib import Path
from src.utils.bits_alumni_verifier import verify_bits_alumni
from src.utils.company_matcher import normalize_company_name

DB_PATH = Path("data/job_hunt.db")

RECRUITER_PATTERN = re.compile(
    r"\b(?:recruiter|talent|sourcer|talent\s+acquisition|hr|people\s+partner)\b",
    re.IGNORECASE
)

def clean_non_alumni_note(note: str, contact_name: str, company: str) -> str:
    """Removes false BITSian claims from outreach notes for non-alumni."""
    first_name = contact_name.split()[0] if contact_name else "there"
    
    # Remove 'fellow bitsian here (2027 batch).' or similar variations
    cleaned = re.sub(r"(?i)\bfellow\s+bitsian\s+here\s*(\([^\)]*\))?[,\.\-—\s]*", "", note)
    cleaned = re.sub(r"(?i)\bbitsian\b", "engineer", cleaned)
    cleaned = re.sub(r"(?i)\bbits\s+pilani\b", "", cleaned)
    cleaned = cleaned.strip()
    
    if not cleaned.lower().startswith("hi") and not cleaned.lower().startswith("hello"):
        cleaned = f"Hi {first_name}, {cleaned.lstrip(',.- ')}"
        
    # If the note became awkward or too short, provide a polished fallback
    if len(cleaned) < 30 or "came across" not in cleaned.lower() and "following" not in cleaned.lower():
        cleaned = f"Hi {first_name}, came across your work in tech at {company}—would love to connect and follow what your team is building!"
        
    return cleaned[:189]

def audit_and_clean_database():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT job_id, company, role, contacts_json, outreach_drafts_json FROM jobs")
    rows = cursor.fetchall()

    print(f"Total jobs to inspect: {len(rows)}")

    verified_alumni_count = 0
    demoted_engineer_count = 0
    demoted_recruiter_count = 0
    drafts_cleaned_count = 0
    jobs_updated_count = 0

    for job_id, company, role, c_json, d_json in rows:
        if not c_json:
            continue

        try:
            contacts = json.loads(c_json)
        except Exception:
            continue

        drafts = []
        if d_json:
            try:
                drafts = json.loads(d_json)
            except Exception:
                pass

        contacts_modified = False
        drafts_modified = False

        for idx, contact in enumerate(contacts):
            name = contact.get("name", "")
            headline = contact.get("headline", "")
            tier = contact.get("tier", "")
            
            is_genuine_alum, reason = verify_bits_alumni(headline, headline)

            if is_genuine_alum:
                verified_alumni_count += 1
                if tier != "1_ALUMNI":
                    contact["tier"] = "1_ALUMNI"
                    contact["relevance_note"] = f"BITS Pilani alum at {company} ({headline[:80]})"
                    contacts_modified = True
                print(f"  [ALUMNI CONFIRMED] {company} | {name}: {reason}")
            else:
                if tier == "1_ALUMNI":
                    # Demote to engineer or recruiter
                    contacts_modified = True
                    if RECRUITER_PATTERN.search(headline):
                        contact["tier"] = "3_RECRUITER"
                        contact["relevance_note"] = f"Technical recruiter at {company} ({headline[:80]})"
                        demoted_recruiter_count += 1
                        print(f"  [DEMOTED TO RECRUITER] {company} | {name}: {reason}")
                    else:
                        contact["tier"] = "2_TEAM_ENGINEER_OR_HM"
                        contact["relevance_note"] = f"Team engineer / hiring manager at {company} ({headline[:80]})"
                        demoted_engineer_count += 1
                        print(f"  [DEMOTED TO ENGINEER] {company} | {name}: {reason}")

            # Check matching draft note
            if idx < len(drafts):
                d = drafts[idx]
                note = d.get("connection_note_300_chars", "")
                if contact["tier"] != "1_ALUMNI" and ("bitsian" in note.lower() or "bits" in note.lower()):
                    cleaned_note = clean_non_alumni_note(note, name, company)
                    d["connection_note_300_chars"] = cleaned_note
                    d["contact_tier"] = contact["tier"]
                    drafts_modified = True
                    drafts_cleaned_count += 1

        if contacts_modified or drafts_modified:
            cursor.execute(
                "UPDATE jobs SET contacts_json = ?, outreach_drafts_json = ? WHERE job_id = ?",
                (json.dumps(contacts), json.dumps(drafts) if drafts else d_json, job_id)
            )
            jobs_updated_count += 1

    conn.commit()
    conn.close()

    print("\n" + "=" * 50)
    print("AUDIT & CLEANUP COMPLETE:")
    print(f"  Verified Genuine BITS Alumni: {verified_alumni_count}")
    print(f"  Demoted to Team Engineer:     {demoted_engineer_count}")
    print(f"  Demoted to Recruiter:         {demoted_recruiter_count}")
    print(f"  Draft Notes Cleaned:          {drafts_cleaned_count}")
    print(f"  Jobs Updated in DB:           {jobs_updated_count}")
    print("=" * 50)

if __name__ == "__main__":
    audit_and_clean_database()

