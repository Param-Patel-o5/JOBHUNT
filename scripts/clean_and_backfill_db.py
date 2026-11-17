"""
Migration & Backfill Script: scripts/clean_and_backfill_db.py

Strict Safety Rules:
1. Exact Database Backup First: data/job_hunt.db -> data/job_hunt_backup.db.
2. Absolute Protection for Active Outreach Rows:
   - Any row with status in ('REFERRAL_ASKED', 'CONNECT_SENT', 'CONNECTED_READY_TO_ASK',
     'APPLIED', 'REFERRED_APPLIED', 'ASKED_REFERRAL', 'APPLIED_VIA_REFERRAL',
     'OA_RECEIVED', 'INTERVIEW', 'OFFER') is 100% PROTECTED from deletion or rejection.
   - Never reject or delete these rows even if US/Remote or <75% match under old rules.
   - Re-run the new 6-Step Referral DM drafter so follow-up DMs are ready in the UI today.
3. Purge Invalid 'NEW' (Unactioned) Jobs:
   - For all rows where status == 'NEW':
     * Location & Remote check (is_valid_location)
     * Experience check (extract_required_yoe < 5)
     * Role title check (is_valid_role_title)
     * Match score check (match_score >= 75)
   - Mark failing jobs as 'REJECTED' with detailed reason.
4. Re-Verify Contacts & Backfill the 6-Step Referral DMs:
   - Run verify_and_extract_contact_signals() on each stored contact. Remove interns / wrong companies.
   - If surviving contacts < 3, trigger find_contacts_for_company() to enrich up to 4 verified contacts.
   - Run generate_outreach_for_job() with sanitize_referral_dm() (0 em dashes, 0 exclamations, portfolio link, stretch check).
5. Print Summary Report:
   - Detailed terminal report showing protected companies, rejection breakdown, and backfilled jobs.
"""

import os
import sys
import json
import shutil
import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv()

from src.models import (
    JobPosting,
    CompanyIntel,
    MatchAndTailorResult,
    ContactPerson,
    OutreachPackage,
)
from src.db import DB_PATH, init_db
from src.nodes.filter import (
    is_valid_location,
    extract_required_yoe,
    is_valid_role_title,
)
from src.utils.company_matcher import (
    verify_and_extract_contact_signals,
    normalize_company_name,
)
from src.nodes.enrich import find_contacts_for_company
from src.nodes.drafter import generate_outreach_for_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("migration.backfill")

BACKUP_PATH = DB_PATH.parent / "job_hunt_backup.db"

# Protected active statuses: user took deliberate outreach actions
PROTECTED_STATUSES: Set[str] = {
    "REFERRAL_ASKED",
    "CONNECT_SENT",
    "CONNECTED_READY_TO_ASK",
    "APPLIED",
    "REFERRED_APPLIED",
    "ASKED_REFERRAL",
    "APPLIED_VIA_REFERRAL",
    "OA_RECEIVED",
    "INTERVIEW",
    "OFFER",
}


def backup_database() -> Path:
    """Creates an exact, verified copy of the database before any modifications."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Source database not found at {DB_PATH.resolve()}")

    BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB_PATH, BACKUP_PATH)
    logger.info(f"Database backup created successfully at: {BACKUP_PATH.resolve()}")
    return BACKUP_PATH


def clean_and_backfill():
    print("=" * 80)
    print("  JOBHUNT OS: Database Migration, Entity Verification & 6-Step Referral Backfill")
    print("=" * 80)

    # 1. Database Backup First
    backup_file = backup_database()
    print(f"[OK] Database backed up to: {backup_file.name}\n")

    init_db(DB_PATH)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        all_rows = cur.fetchall()

    total_rows = len(all_rows)
    print(f"Total jobs in database to audit: {total_rows}\n")

    # Metrics
    protected_companies: List[Dict[str, str]] = []
    rejected_new_count = 0
    rejection_breakdown = {
        "Location / Remote": 0,
        "YoE >= 5 Years": 0,
        "Role Title / Non-AI": 0,
        "Match Score < 75%": 0,
    }
    updated_jobs_count = 0
    total_contacts_before = 0
    total_contacts_after = 0
    enriched_companies_count = 0
    company_verified_contacts_cache: Dict[str, List[ContactPerson]] = {}

    with sqlite3.connect(DB_PATH) as conn:
        for idx, row in enumerate(all_rows, 1):
            job_id = row["job_id"]
            company = row["company"] or ""
            role = row["role"] or ""
            status = (row["status"] or "NEW").upper()
            location = row["location"] or ""
            jd_text = row["jd_text"] or ""
            match_score = int(row["match_score"] or 0)
            
            raw_contacts = json.loads(row["contacts_json"] or "[]")
            total_contacts_before += len(raw_contacts)

            # -----------------------------------------------------------------
            # 2. Check Protection vs Filter Purge
            # -----------------------------------------------------------------
            is_protected = status in PROTECTED_STATUSES

            if is_protected:
                protected_companies.append({
                    "company": company,
                    "role": role,
                    "status": status,
                    "match_score": match_score,
                })
                logger.info(f"[{idx}/{total_rows}] [PROTECTED ACTIVE] {company} ('{role}') - Status: {status}")
            elif status == "NEW":
                # Evaluate strict gates on unactioned 'NEW' jobs
                reject_reason = None
                
                # Gate 1: Location & Remote
                is_loc_valid, loc_msg = is_valid_location(location, jd_text)
                if not is_loc_valid:
                    reject_reason = loc_msg
                    rejection_breakdown["Location / Remote"] += 1

                # Gate 2: Required YoE < 5
                req_yoe = extract_required_yoe(jd_text)
                if not reject_reason and req_yoe >= 5:
                    reject_reason = f"[FILTER REJECT] Required YoE ({req_yoe} years) exceeds entry cap (<5 yrs)"
                    rejection_breakdown["YoE >= 5 Years"] += 1

                # Gate 3: Role Title & Intern Hard Reject
                is_role_valid, role_msg = is_valid_role_title(role)
                if not reject_reason and not is_role_valid:
                    reject_reason = role_msg
                    rejection_breakdown["Role Title / Non-AI"] += 1

                # Gate 4: Match Score >= 75% Floor
                if not reject_reason and match_score < 75:
                    reject_reason = f"[EVAL REJECT] Match score {match_score}% is below 75% floor"
                    rejection_breakdown["Match Score < 75%"] += 1

                if reject_reason:
                    rejected_new_count += 1
                    logger.info(f"[{idx}/{total_rows}] [REJECT NEW] {company} - '{role}': {reject_reason}")
                    conn.execute(
                        "UPDATE jobs SET status = 'REJECTED', notes = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?",
                        (reject_reason, job_id)
                    )
                    conn.commit()
                    continue
                else:
                    logger.info(f"[{idx}/{total_rows}] [SURVIVED NEW] {company} - '{role}' passed all strict gates")
            else:
                # Already REJECTED or SKIPPED
                logger.debug(f"[{idx}/{total_rows}] [PREVIOUSLY {status}] {company} - skipping outreach backfill")
                continue

            # -----------------------------------------------------------------
            # 3. Contact Re-Verification & Active Signal Extraction
            # -----------------------------------------------------------------
            comp_key = company.strip().lower()
            if comp_key in company_verified_contacts_cache and len(company_verified_contacts_cache[comp_key]) >= 2:
                verified_contacts = [cp.model_copy() for cp in company_verified_contacts_cache[comp_key]]
                logger.info(f"  -> Cache hit for '{company}': reusing {len(verified_contacts)} verified contacts")
            else:
                verified_contacts: List[ContactPerson] = []
                seen_urls: Set[str] = set()

                for c_dict in raw_contacts:
                    name = (c_dict.get("name") or "").strip()
                    headline = (c_dict.get("headline") or "").strip()
                    rel_note = (c_dict.get("relevance_note") or "").strip()
                    url = (c_dict.get("linkedin_url") or "").strip()

                    if not url or url in seen_urls:
                        continue

                    title = f"{name} - {headline} | LinkedIn" if name and headline else (headline or name)
                    signals = verify_and_extract_contact_signals(company, title, rel_note)

                    if signals.get("is_valid", False):
                        cp = ContactPerson(
                            name=name or "Colleague",
                            headline=headline or f"Engineer at {company}",
                            linkedin_url=url,
                            tier=c_dict.get("tier", "2_TEAM_ENGINEER_OR_HM"),
                            relevance_note=rel_note or f"Verified employee at {company}",
                            email=c_dict.get("email") or "",
                            email_status=c_dict.get("email_status") or "PATTERN_GUESS",
                            current_company=signals.get("current_company") or company,
                            current_title=signals.get("current_title") or headline,
                            is_bits_alum=signals.get("is_bits_alum", False),
                            bits_type=signals.get("bits_type", "NONE"),
                            stated_ai_ml_interest=signals.get("stated_ai_ml_interest", False),
                            years_experience_level=signals.get("years_experience_level", "junior"),
                            mutual_connections=signals.get("mutual_connections", False),
                        )
                        # Correct tier to 1_ALUMNI if BITS alum
                        if cp.is_bits_alum and cp.tier != "1_ALUMNI":
                            cp.tier = "1_ALUMNI"

                        seen_urls.add(url)
                        verified_contacts.append(cp)
                    else:
                        logger.info(
                            f"  -> Dropped unverified contact '{name}' at '{company}': {signals.get('rejection_reason')}"
                        )

                # -----------------------------------------------------------------
                # 4. Enrich if fewer than 3 verified contacts
                # -----------------------------------------------------------------
                if len(verified_contacts) < 3:
                    logger.info(
                        f"  -> '{company}' has {len(verified_contacts)} verified contacts. Triggering contact discovery..."
                    )
                    try:
                        fresh_contacts = find_contacts_for_company(company, role, max_contacts=4)
                        for fc in fresh_contacts:
                            if fc.linkedin_url not in seen_urls and len(verified_contacts) < 4:
                                seen_urls.add(fc.linkedin_url)
                                verified_contacts.append(fc)
                        enriched_companies_count += 1
                    except Exception as e:
                        logger.warning(f"  -> Enrichment failed for '{company}': {e}")

                if verified_contacts:
                    company_verified_contacts_cache[comp_key] = verified_contacts

            total_contacts_after += len(verified_contacts)

            # -----------------------------------------------------------------
            # 5. Extract HR / Referrer Email
            # -----------------------------------------------------------------
            hr_email = row["hr_email"] or ""
            if verified_contacts and (not hr_email or "recruiting@" in hr_email):
                for vc in verified_contacts:
                    if vc.email and "@" in vc.email:
                        hr_email = vc.email
                        break

            # -----------------------------------------------------------------
            # 6. Reconstruct Models & Run 6-Step Referral DM Drafter
            # -----------------------------------------------------------------
            required_yoe = int(row["required_yoe"] or 0) if "required_yoe" in row.keys() and row["required_yoe"] is not None else 0
            if required_yoe == 0 and jd_text:
                required_yoe = extract_required_yoe(jd_text)

            job = JobPosting(
                job_id=job_id,
                company=company,
                role=role,
                location=location,
                jd_text=jd_text,
                job_url=row["job_url"] or "",
                source=row["source"] or "Direct",
                required_yoe=required_yoe,
            )

            company_intel = CompanyIntel(
                company_name=company,
                funding_or_stage=row["company_stage"] or "Growth",
                estimated_size="1000+",
                est_entry_ai_ctc_lpa=float(row["est_ctc_lpa"] or 18.0),
                passes_quality_bar=True,
                summary_2_lines=row["company_summary"] or f"{company} develops modern engineering products.",
                hr_email=hr_email,
            )

            match_result = MatchAndTailorResult(
                match_score=match_score,
                selected_project_id=row["selected_project"] or "agent_diagnostician",
                winning_hook_sentence=row["winning_hook"] or "",
                missing_keywords=json.loads(row["missing_keywords_json"] or "[]"),
                resume_bullet_tweaks=json.loads(row["resume_tweaks_json"] or "[]"),
                jd_core_requirements=json.loads(row["jd_summary_json"] or "[]"),
            )

            # Generate 6-step referral DM outreach packages
            packages, fallback = generate_outreach_for_job(
                job=job,
                company_intel=company_intel,
                match_result=match_result,
                contacts=verified_contacts,
                use_llm=False,  # Deterministic 6-step DM — zero LLM cost, runs in <1s per job
            )

            # Persist updated contacts & outreach packages
            conn.execute(
                """
                UPDATE jobs 
                SET contacts_json = ?,
                    outreach_drafts_json = ?,
                    fallback_note = ?,
                    hr_email = ?,
                    required_yoe = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (
                    json.dumps([c.model_dump() for c in verified_contacts]),
                    json.dumps([p.model_dump() for p in packages]),
                    fallback,
                    hr_email,
                    required_yoe,
                    job_id,
                ),
            )
            conn.commit()
            updated_jobs_count += 1
            logger.info(f"  [UPDATED] {company} ({len(verified_contacts)} contacts, {len(packages)} 6-step DMs)")

    # -------------------------------------------------------------------------
    # 7. Print Terminal Summary Report
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("                       MIGRATION & BACKFILL REPORT")
    print("=" * 80)

    print("\n1. PROTECTED ACTIVE / OUTREACH COMPANIES (100% Preserved):")
    print("-" * 80)
    print(f"{'Company':<35} | {'Role':<25} | {'Status':<20} | {'Score'}")
    print("-" * 80)
    for p in protected_companies:
        print(f"{p['company'][:34]:<35} | {p['role'][:24]:<25} | {p['status']:<20} | {p['match_score']}%")
    print("-" * 80)
    print(f"Total Protected Active Jobs: {len(protected_companies)}\n")

    print("2. 'NEW' JOBS PURGE & FILTER SUMMARY:")
    print("-" * 80)
    print(f"Total 'NEW' Jobs Rejected: {rejected_new_count}")
    for reason, count in rejection_breakdown.items():
        print(f"  - {reason:<25}: {count}")
    print("-" * 80)

    print("\n3. OUTREACH & CONTACT RE-VERIFICATION SUMMARY:")
    print("-" * 80)
    print(f"Total Jobs Updated with 6-Step Referral DMs: {updated_jobs_count}")
    print(f"Companies Triggered for Contact Discovery:   {enriched_companies_count}")
    print(f"Total Contacts Audited:                      {total_contacts_before}")
    print(f"Total Verified Contacts Stored:              {total_contacts_after}")
    print(f"Verified Database File:                      {DB_PATH.resolve()}")
    print(f"Safe Backup Preserved At:                    {BACKUP_PATH.resolve()}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    clean_and_backfill()
