"""
Re-run strict contact discovery for specific jobs by job_id.
Clears the in-memory cache first, then re-queries with the new BITS Alumni verifier active.
"""

import sys
import json
import sqlite3
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from src.db import DB_PATH, init_db
from src.models import JobPosting, CompanyIntel, MatchAndTailorResult, ContactPerson
from src.nodes.people_finder import find_contacts_for_company, clear_contacts_cache
from src.nodes.drafter import generate_outreach_for_job

# -----------------------------------------------------------------------
# Target job IDs to re-process (from the DB dump above)
# -----------------------------------------------------------------------
TARGET_JOB_IDS = [
    "1dd59c25bff1",         # Cencora - AI Developer 2
    "e9645d8e1cf0",         # Comcast - Engineer 3 - Machine Learning
    "f92d5a39ba49",         # Kotak Mahindra Bank - Data Scientist - AI / ML job
]

def rerun_discovery_for_jobs(job_ids: list[str]):
    init_db(DB_PATH)
    clear_contacts_cache()  # Wipe the in-memory cache so stale data doesn't return

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM jobs WHERE job_id IN ({','.join(['?']*len(job_ids))})",
            job_ids
        ).fetchall()

    print(f"\nFound {len(rows)} matching jobs to re-process.\n")

    for row in rows:
        job_id    = row["job_id"]
        company   = row["company"]
        role      = row["role"]
        job_url   = row["job_url"]

        print(f"{'='*70}")
        print(f"  Job: {company} - {role}")
        print(f"  ID:  {job_id}")
        old_contacts = json.loads(row["contacts_json"] or "[]")
        print(f"  Old contacts: {[(c['name'], c['tier']) for c in old_contacts]}")
        print()

        # Re-run discovery with strict gates active
        new_contacts = find_contacts_for_company(company, role)

        print(f"\n  New contacts discovered: {len(new_contacts)}")
        for c in new_contacts:
            print(f"    -> {c.name} | {c.headline} | tier={c.tier}")

        # Reconstruct minimal model objects for outreach generation
        job_obj = JobPosting(
            job_id=job_id,
            company=company,
            role=role,
            location=row["location"] or "Remote",
            job_url=job_url,
            jd_text=row["jd_text"] or "",
            source=row["source"] or "Direct",
        )
        intel_obj = CompanyIntel(
            company_name=company,
            funding_or_stage=row["company_stage"] or "Growth",
            estimated_size="1000+",
            est_entry_ai_ctc_lpa=float(row["est_ctc_lpa"] or 18.0),
            passes_quality_bar=True,
            summary_2_lines=row["company_summary"] or f"{company} builds modern software products.",
            hr_email=row["hr_email"] or "",
        )
        match_obj = MatchAndTailorResult(
            match_score=int(row["match_score"] or 80),
            selected_project_id=row["selected_project"] or "agent_diagnostician",
            winning_hook_sentence=row["winning_hook"] or f"Built scalable AI systems aligned with {company}'s stack.",
            missing_keywords=json.loads(row["missing_keywords_json"] or "[]"),
            resume_bullet_tweaks=json.loads(row["resume_tweaks_json"] or "[]"),
            jd_core_requirements=json.loads(row["jd_summary_json"] or "[]"),
        )

        # Regenerate outreach if any contacts found
        new_packages, new_fallback = [], None
        if new_contacts:
            try:
                new_packages, new_fallback = generate_outreach_for_job(
                    job=job_obj,
                    company_intel=intel_obj,
                    match_result=match_obj,
                    contacts=new_contacts,
                )
                print(f"  Generated {len(new_packages)} outreach package(s).")
            except Exception as e:
                print(f"  [WARN] Outreach generation failed: {e}")

        # Write back to DB
        new_contacts_json = json.dumps([c.model_dump() for c in new_contacts])
        new_outreach_json = json.dumps([p.model_dump() for p in new_packages])
        referrer_names = ", ".join(c.name for c in new_contacts) if new_contacts else ""

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                UPDATE jobs
                SET contacts_json = ?,
                    outreach_drafts_json = ?,
                    fallback_note = ?,
                    referrer_name = ?
                WHERE job_id = ?
                """,
                (new_contacts_json, new_outreach_json, new_fallback, referrer_names, job_id)
            )
            conn.commit()

        print(f"  [SAVED] DB updated for '{company}'.\n")

    print("=" * 70)
    print(f"Done. Reprocessed {len(rows)} job(s).")
    print("=" * 70)


if __name__ == "__main__":
    rerun_discovery_for_jobs(TARGET_JOB_IDS)

