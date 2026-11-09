"""
Backfill Utility Script: Regenerate Outreach Packages with Seniority Detection & <= 190 Char Limit.

Fetches all jobs in data/job_hunt.db with status 'NEW' or 'CONNECT_SENT',
deserializes their company, match, and contact data, and regenerates
hyper-personalized, seniority-tailored outreach drafts.
"""

import os
import sys
import json
import sqlite3
from pathlib import Path

# Ensure project root is in path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.models import (
    JobPosting,
    CompanyIntel,
    MatchAndTailorResult,
    ContactPerson,
)
from src.nodes.drafter import generate_outreach_for_job, detect_seniority
from src.db import DB_PATH, init_db


def backfill_outreach():
    print("=" * 75)
    print("  JobHunt OS: Backfilling Seniority-Aware Outreach Packages (<= 190 chars)")
    print("=" * 75)

    init_db(DB_PATH)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT * FROM jobs 
            WHERE status IN ('NEW', 'CONNECT_SENT')
            ORDER BY created_at DESC
            """
        )
        rows = cur.fetchall()

    total_jobs = len(rows)
    print(f"Found {total_jobs} jobs with status in ('NEW', 'CONNECT_SENT').\n")

    if total_jobs == 0:
        print("No jobs found matching criteria. Exiting.")
        return

    updated_count = 0
    skipped_count = 0

    with sqlite3.connect(DB_PATH) as conn:
        for idx, row in enumerate(rows, 1):
            job_id = row["job_id"]
            company = row["company"]
            role = row["role"]

            raw_contacts = json.loads(row["contacts_json"] or "[]")
            if not raw_contacts:
                print(f"[{idx}/{total_jobs}] [SKIP] {company} - '{role}': No contacts found.")
                skipped_count += 1
                continue

            # Reconstruct models
            job = JobPosting(
                job_id=job_id,
                company=company,
                role=role,
                location=row["location"] or "",
                jd_text=row["jd_text"] or "",
                job_url=row["job_url"],
                source=row["source"] or "Direct",
            )

            company_intel = CompanyIntel(
                company_name=company,
                funding_or_stage=row["company_stage"] or "Growth",
                estimated_size="1000+",
                est_entry_ai_ctc_lpa=float(row["est_ctc_lpa"] or 18.0),
                passes_quality_bar=True,
                summary_2_lines=row["company_summary"] or f"{company} develops modern software and engineering products.",
                hr_email=row["hr_email"] or "",
            )

            match_result = MatchAndTailorResult(
                match_score=int(row["match_score"] or 80),
                selected_project_id=row["selected_project"] or "agent_diagnostician",
                winning_hook_sentence=row["winning_hook"] or "",
                missing_keywords=json.loads(row["missing_keywords_json"] or "[]"),
                resume_bullet_tweaks=json.loads(row["resume_tweaks_json"] or "[]"),
                jd_core_requirements=json.loads(row["jd_summary_json"] or "[]"),
            )

            contacts = [ContactPerson.model_validate(c) for c in raw_contacts]

            # Generate new seniority-aware outreach
            try:
                packages, fallback = generate_outreach_for_job(job, company_intel, match_result, contacts)
                
                # Persist to database
                conn.execute(
                    "UPDATE jobs SET outreach_drafts_json = ? WHERE job_id = ?",
                    (json.dumps([p.model_dump() for p in packages]), job_id),
                )
                conn.commit()

                # Print summary
                contact_summaries = []
                for p, c in zip(packages, contacts):
                    sen = detect_seniority(c.headline)
                    c_len = len(p.connection_note_300_chars)
                    dm_words = len(p.full_dm_under_95_words.split())
                    contact_summaries.append(f"{p.contact_name} ({sen}): Note {c_len} chars, DM {dm_words} words")

                print(f"[{idx}/{total_jobs}] [OK] {company} - '{role}'")
                for s in contact_summaries:
                    print(f"       -> {s}")

                updated_count += 1
            except Exception as e:
                print(f"[{idx}/{total_jobs}] [ERROR] {company} - '{role}': {e}")

    print("\n" + "=" * 75)
    print(f"Backfill Complete! Successfully updated {updated_count}/{total_jobs} jobs ({skipped_count} skipped).")
    print("=" * 75)


if __name__ == "__main__":
    backfill_outreach()

