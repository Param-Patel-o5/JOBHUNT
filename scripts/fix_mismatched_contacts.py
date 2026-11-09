"""
Retroactive Database Audit & Cleanup Script.

Audits all stored contacts in data/job_hunt.db using the 3-Stage Deterministic
Entity Verification Pipeline (src/utils/company_matcher.py).

Purges mismatched/erroneous contacts, automatically re-runs strict discovery
for affected jobs, regenerates outreach packages, and commits the clean records.
"""

import os
import sys
import json
import sqlite3
import logging
from pathlib import Path

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.models import (
    JobPosting,
    CompanyIntel,
    MatchAndTailorResult,
    ContactPerson,
    OutreachPackage,
)
from src.utils.company_matcher import verify_contact_company
from src.nodes.people_finder import find_contacts_for_company, clear_contacts_cache
from src.nodes.drafter import generate_outreach_for_job
from src.db import DB_PATH, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fix_mismatched_contacts")


def audit_and_cleanup_database(db_path: Path = DB_PATH):
    print("=" * 80)
    print("  JobHunt OS: Retroactive Contact Verification & Database Audit")
    print("=" * 80)

    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return

    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        rows = cur.fetchall()

    total_jobs = len(rows)
    print(f"Found {total_jobs} total jobs in database to audit.\n")

    purged_contact_count = 0
    updated_jobs_count = 0

    for idx, row in enumerate(rows, 1):
        company = (row["company"] or "").strip()
        role = (row["role"] or "").strip()
        job_url = row["job_url"]

        contacts_raw = row["contacts_json"]
        contacts_list = json.loads(contacts_raw) if contacts_raw else []

        if not contacts_list:
            continue

        valid_contacts: list[dict] = []
        purged_for_this_job: list[dict] = []

        for c in contacts_list:
            c_name = c.get("name", "")
            c_headline = c.get("headline", "")
            c_note = c.get("relevance_note", "")

            # Formulate simulated title and snippet for verification
            simulated_title = f"{c_name} - {c_headline} | LinkedIn"
            simulated_snippet = c_note

            is_valid, confidence, reason = verify_contact_company(
                company_name=company,
                linkedin_title=simulated_title,
                linkedin_snippet=simulated_snippet
            )

            if is_valid and confidence >= 0.85:
                valid_contacts.append(c)
            else:
                purged_for_this_job.append(c)
                purged_contact_count += 1
                print(f"  [PURGED] Job: {company} | Bad Contact: {c_name} ({c_headline}) | Reason: {reason} (conf={confidence:.2f})")

        # If any contact was purged from this job
        if purged_for_this_job:
            print(f"[{idx}/{total_jobs}] Job '{company}' lost {len(purged_for_this_job)} invalid contact(s).")
            
            # If the job lost contacts and has fewer than 2 valid contacts left, try re-discovering with strict dorking
            final_contact_objs: list[ContactPerson] = [ContactPerson(**vc) for vc in valid_contacts]

            if len(final_contact_objs) < 2:
                print(f"  -> Re-running strict discovery for '{company}' ({role})...")
                clear_contacts_cache()
                try:
                    discovered = find_contacts_for_company(company, role)
                    # Merge discovered while avoiding duplicates
                    existing_urls = {co.linkedin_url for co in final_contact_objs}
                    for disc in discovered:
                        if disc.linkedin_url not in existing_urls:
                            final_contact_objs.append(disc)
                            existing_urls.add(disc.linkedin_url)
                    final_contact_objs = final_contact_objs[:2]
                    print(f"  -> Re-discovery yielded {len(final_contact_objs)} valid contacts.")
                except Exception as e:
                    logger.warning(f"Re-discovery failed for '{company}': {e}")

            # Reconstruct models for outreach generation
            job_id = row["job_id"]
            source = row["source"] or "Direct"
            job_obj = JobPosting(
                job_id=job_id,
                company=company,
                role=role,
                location=row["location"] or "Remote",
                job_url=job_url,
                jd_text=row["jd_text"] or "",
                source=source,
            )
            intel_obj = CompanyIntel(
                company_name=company,
                funding_or_stage=row["company_stage"] or "Growth",
                estimated_size="1000+",
                est_entry_ai_ctc_lpa=float(row["est_ctc_lpa"] or 18.0),
                passes_quality_bar=True,
                summary_2_lines=row["company_summary"] or f"{company} engineering.",
                hr_email=row["hr_email"] or "",
            )
            match_obj = MatchAndTailorResult(
                match_score=int(row["match_score"] or 85),
                selected_project_id=row["selected_project"] or "agent_diagnostician",
                winning_hook_sentence=row["winning_hook"] or f"Built scalable AI systems aligned with {company}'s stack.",
                missing_keywords=json.loads(row["missing_keywords_json"] or "[]"),
                resume_bullet_tweaks=json.loads(row["resume_tweaks_json"] or "[]"),
                jd_core_requirements=json.loads(row["jd_summary_json"] or "[]"),
            )

            print(f"  -> Regenerating outreach packages for '{company}' ({len(final_contact_objs)} contacts)...")
            try:
                new_packages, new_fallback = generate_outreach_for_job(
                    job=job_obj,
                    company_intel=intel_obj,
                    match_result=match_obj,
                    contacts=final_contact_objs,
                )
            except Exception as e:
                logger.error(f"Outreach regeneration failed for '{company}': {e}")
                new_packages, new_fallback = [], None

            # Serialize and update database row
            new_contacts_json = json.dumps([c.model_dump() for c in final_contact_objs])
            new_outreach_json = json.dumps([p.model_dump() for p in new_packages])
            referrer_names = ", ".join(c.name for c in final_contact_objs) if final_contact_objs else ""

            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    UPDATE jobs
                    SET contacts_json = ?,
                        outreach_drafts_json = ?,
                        fallback_note = ?,
                        referrer_name = ?
                    WHERE job_id = ?
                    """,
                    (
                        new_contacts_json,
                        new_outreach_json,
                        new_fallback,
                        referrer_names,
                        job_id,
                    )
                )
                conn.commit()

            updated_jobs_count += 1
            print(f"  [UPDATED] Job '{company}' successfully updated in SQLite.\n")
        else:
            print(f"[{idx}/{total_jobs}] [VERIFIED] Job '{company}' contacts are 100% verified.")

    print("=" * 80)
    print(f"Audit Complete! Purged {purged_contact_count} mismatched contact(s) across {updated_jobs_count} job(s).")
    print("=" * 80)


if __name__ == "__main__":
    audit_and_cleanup_database()
