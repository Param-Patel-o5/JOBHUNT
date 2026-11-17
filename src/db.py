import sqlite3
import json
from pathlib import Path
from typing import List, Any, Optional, Dict
from datetime import datetime
import pandas as pd
from src.models import CompanyIntel

# Root database path: JOBHUNT/data/job_hunt.db
DB_PATH = Path("data/job_hunt.db")

VALID_STATUSES = [
    "NEW",
    "CONNECT_SENT",
    "ASKED_REFERRAL",
    "APPLIED_VIA_REFERRAL",
    "APPLIED_DIRECT",
    "OA_RECEIVED",
    "INTERVIEW",
    "OFFER",
    "REJECTED",
    "SKIPPED",
]


def init_db(db_path: Path = DB_PATH) -> None:
    """Initializes the SQLite database and ensures the schema and migrations are applied."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                role TEXT NOT NULL,
                location TEXT,
                job_url TEXT NOT NULL,
                source TEXT,
                match_score INTEGER,
                est_ctc_lpa REAL,
                company_stage TEXT,
                company_summary TEXT,
                winning_hook TEXT,
                selected_project TEXT,
                missing_keywords_json TEXT,
                resume_tweaks_json TEXT,
                contacts_json TEXT,
                outreach_drafts_json TEXT,
                fallback_note TEXT,
                notes TEXT DEFAULT '',
                status TEXT DEFAULT 'NEW',
                outreach_sent_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS company_cache (
                company_key TEXT PRIMARY KEY,
                intel_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Migrations for existing databases
        for col, col_type in [
            ("fallback_note", "TEXT"),
            ("notes", "TEXT DEFAULT ''"),
            ("selected_project", "TEXT"),
            ("jd_summary_json", "TEXT DEFAULT '[]'"),
            ("hr_email", "TEXT DEFAULT ''"),
            ("referrer_name", "TEXT DEFAULT ''"),
            ("jd_text", "TEXT DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass

        # Migrate legacy status 'REFERRAL_SENT' to 'ASKED_REFERRAL'
        conn.execute("UPDATE jobs SET status = 'ASKED_REFERRAL' WHERE status = 'REFERRAL_SENT'")
        conn.commit()


def is_job_seen(job_id: str, company: str, role: str, db_path: Path = DB_PATH) -> bool:
    """Checks if exact job_id OR (company + role) already exists in the database."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT 1 FROM jobs 
            WHERE job_id = ? 
               OR (LOWER(TRIM(company)) = LOWER(TRIM(?)) AND LOWER(TRIM(role)) = LOWER(TRIM(?)))
            LIMIT 1
            """,
            (job_id, company, role),
        )
        return cur.fetchone() is not None


def save_enriched_jobs(records: List[Any], db_path: Path = DB_PATH) -> int:
    """Saves EnrichedJobRecord instances to SQLite, preserving existing user notes, status, and edits."""
    init_db(db_path)
    saved = 0
    with sqlite3.connect(db_path) as conn:
        for r in records:
            # Check for existing user status, notes, hr_email, and referrer_name
            cur = conn.execute(
                "SELECT status, notes, outreach_sent_at, hr_email, referrer_name FROM jobs WHERE job_id = ?",
                (r.job.job_id,),
            )
            existing = cur.fetchone()
            status = existing[0] if existing and existing[0] else (getattr(r, "status", None) or "NEW")
            notes = existing[1] if existing and existing[1] is not None else ""
            outreach_sent_at = existing[2] if existing else None

            default_hr = getattr(r, "hr_email", "") or getattr(r.company_intel, "hr_email", "") or ""
            hr_email = existing[3] if existing and existing[3] else default_hr

            default_referrer = getattr(r, "referrer_name", "") or (", ".join(c.name for c in r.contacts) if r.contacts else "")
            referrer_name = existing[4] if existing and existing[4] else default_referrer

            jd_summary = getattr(r.match_result, "jd_core_requirements", [])

            conn.execute(
                """
                INSERT OR REPLACE INTO jobs (
                    job_id, company, role, location, job_url, source,
                    match_score, est_ctc_lpa, company_stage, company_summary,
                    winning_hook, selected_project, missing_keywords_json, resume_tweaks_json,
                    contacts_json, outreach_drafts_json, fallback_note, notes,
                    status, outreach_sent_at, jd_summary_json, hr_email, referrer_name, jd_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.job.job_id,
                    r.job.company,
                    r.job.role,
                    r.job.location,
                    r.job.job_url,
                    r.job.source,
                    r.match_result.match_score,
                    r.company_intel.est_entry_ai_ctc_lpa,
                    r.company_intel.funding_or_stage,
                    r.company_intel.summary_2_lines,
                    r.match_result.winning_hook_sentence,
                    getattr(r.match_result, "selected_project_id", ""),
                    json.dumps(r.match_result.missing_keywords),
                    json.dumps(r.match_result.resume_bullet_tweaks),
                    json.dumps([c.model_dump() for c in r.contacts]),
                    json.dumps([d.model_dump() for d in r.outreach_drafts]),
                    getattr(r, "fallback_direct_apply_note", None),
                    notes,
                    status,
                    outreach_sent_at,
                    json.dumps(jd_summary),
                    hr_email,
                    referrer_name,
                    getattr(r.job, "jd_text", ""),
                ),
            )
            saved += 1
        conn.commit()
    return saved


def save_rejected_evaluated_job(
    job: Any,
    intel: Any,
    match_result: Any,
    rejection_reason: str = "Match score below 75% floor",
    db_path: Path = DB_PATH,
) -> None:
    """Saves a low-scoring evaluated job as REJECTED in SQLite to keep active queue clean and prevent re-evaluation."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job.job_id,))
        existing = cur.fetchone()
        if existing and existing[0] != "NEW":
            return  # Do not overwrite if user has already modified status

        conn.execute(
            """
            INSERT OR REPLACE INTO jobs (
                job_id, company, role, location, job_url, source,
                match_score, est_ctc_lpa, company_stage, company_summary,
                winning_hook, selected_project, missing_keywords_json, resume_tweaks_json,
                contacts_json, outreach_drafts_json, fallback_note, notes,
                status, outreach_sent_at, jd_summary_json, hr_email, referrer_name, jd_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.company,
                job.role,
                job.location,
                job.job_url,
                job.source,
                match_result.match_score,
                getattr(intel, "est_entry_ai_ctc_lpa", 0.0),
                getattr(intel, "funding_or_stage", ""),
                getattr(intel, "summary_2_lines", ""),
                getattr(match_result, "winning_hook_sentence", ""),
                getattr(match_result, "selected_project_id", ""),
                json.dumps(getattr(match_result, "missing_keywords", [])),
                json.dumps(getattr(match_result, "resume_bullet_tweaks", [])),
                "[]",
                "[]",
                None,
                f"[AUTO-REJECT] {rejection_reason} (Score: {match_result.match_score}%)",
                "REJECTED",
                None,
                json.dumps(getattr(match_result, "jd_core_requirements", [])),
                getattr(intel, "hr_email", ""),
                "",
                getattr(job, "jd_text", ""),
            ),
        )
        conn.commit()


def get_cached_company_intel(company: str, db_path: Path = DB_PATH) -> Optional[CompanyIntel]:
    """Retrieves cached CompanyIntel for a company. Returns None if not cached."""
    init_db(db_path)
    company_key = company.strip().lower()
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT intel_json FROM company_cache WHERE company_key = ?",
            (company_key,),
        )
        row = cur.fetchone()
        if row:
            return CompanyIntel.model_validate_json(row[0])
    return None


def save_cached_company_intel(company: str, intel: CompanyIntel, db_path: Path = DB_PATH) -> None:
    """Saves or updates cached CompanyIntel for a company."""
    init_db(db_path)
    company_key = company.strip().lower()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO company_cache (company_key, intel_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
            (company_key, intel.model_dump_json()),
        )
        conn.commit()


# =========================================================================
# Streamlit Dashboard Query Helpers
# =========================================================================

def get_dashboard_stats(db_path: Path = DB_PATH) -> Dict[str, int]:
    """Returns top-level metric counters for modern dashboard header."""
    init_db(db_path)
    stats = {
        "total_discovered": 0,
        "total_new": 0,
        "pipeline_active": 0,
        "referrals_asked": 0,
        "interviews": 0,
    }
    with sqlite3.connect(db_path) as conn:
        # Total Discovered
        cur = conn.execute("SELECT COUNT(*) FROM jobs")
        stats["total_discovered"] = cur.fetchone()[0]
        stats["total_jobs"] = stats["total_discovered"]

        # Total New for Triage
        cur = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'NEW'")
        stats["total_new"] = cur.fetchone()[0]

        # Pipeline Active (in motion: connect sent, asked referral, applied via referral, direct apply, OA, interview, offer)
        cur = conn.execute(
            """
            SELECT COUNT(*) FROM jobs 
            WHERE status IN ('CONNECT_SENT', 'ASKED_REFERRAL', 'APPLIED_VIA_REFERRAL', 'APPLIED_DIRECT', 'OA_RECEIVED', 'INTERVIEW', 'OFFER')
            """
        )
        stats["pipeline_active"] = cur.fetchone()[0]

        # Referrals Asked
        cur = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('ASKED_REFERRAL', 'APPLIED_VIA_REFERRAL')")
        stats["referrals_asked"] = cur.fetchone()[0]
        stats["referrals_sent"] = stats["referrals_asked"]

        # Active Interviews / Offers
        cur = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('INTERVIEW', 'OFFER')")
        stats["interviews"] = cur.fetchone()[0]

        # New Today (backward compatibility)
        cur = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE DATE(created_at, 'localtime') = DATE('now', 'localtime')"
        )
        stats["new_today"] = cur.fetchone()[0]

    return stats


def get_overdue_followups(db_path: Path = DB_PATH, days: int = 2) -> List[Dict[str, Any]]:
    """
    Returns jobs where referral was asked >= 48 hours ago
    and follow-up is due.
    """
    init_db(db_path)
    results = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            f"""
            SELECT * FROM jobs 
            WHERE status = 'ASKED_REFERRAL' 
              AND outreach_sent_at IS NOT NULL
              AND datetime(outreach_sent_at) <= datetime('now', '-{days} days')
            ORDER BY outreach_sent_at ASC
            """
        )
        for row in cur.fetchall():
            d = dict(row)
            d["contacts"] = json.loads(d.get("contacts_json") or "[]")
            d["outreach_drafts"] = json.loads(d.get("outreach_drafts_json") or "[]")
            results.append(d)
    return results


def load_jobs_dataframe(status_filter: Optional[str] = None, db_path: Path = DB_PATH) -> pd.DataFrame:
    """Loads jobs table as a Pandas DataFrame for the st.data_editor spreadsheet."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        query = """
            SELECT 
                job_id,
                company,
                role,
                est_ctc_lpa,
                hr_email,
                job_url,
                referrer_name,
                status,
                notes,
                match_score,
                source,
                location,
                company_stage,
                company_summary,
                winning_hook,
                selected_project,
                missing_keywords_json,
                resume_tweaks_json,
                contacts_json,
                outreach_drafts_json,
                fallback_note,
                jd_summary_json,
                jd_text,
                outreach_sent_at,
                created_at
            FROM jobs
        """
        params = []
        if status_filter and status_filter.upper() != "ALL":
            query += " WHERE UPPER(status) = ?"
            params.append(status_filter.upper())

        query += " ORDER BY match_score DESC, created_at DESC"
        df = pd.read_sql_query(query, conn, params=params)

    # Ensure text columns are non-null string
    for col in ["notes", "hr_email", "referrer_name", "company", "role", "status"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)

    return df


def update_job_status_and_notes(updates_df: pd.DataFrame, db_path: Path = DB_PATH) -> int:
    """
    Persists user edits from st.data_editor back to SQLite.
    Persists status, notes, hr_email, and referrer_name.
    If status transitions to 'ASKED_REFERRAL' or 'CONNECT_SENT', updates outreach_sent_at if null.
    """
    init_db(db_path)
    if updates_df.empty or "job_id" not in updates_df.columns:
        return 0

    updated_count = 0
    with sqlite3.connect(db_path) as conn:
        for _, row in updates_df.iterrows():
            job_id = str(row["job_id"])
            new_status = str(row.get("status", "NEW")).strip().upper()
            notes = str(row.get("notes", "") or "").strip()
            hr_email = str(row.get("hr_email", "") or "").strip()
            referrer_name = str(row.get("referrer_name", "") or "").strip()

            if new_status not in VALID_STATUSES:
                new_status = "NEW"

            # Check previous status to detect transitions to ASKED_REFERRAL
            cur = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,))
            prev_row = cur.fetchone()
            prev_status = prev_row[0] if prev_row else "NEW"

            if new_status == "ASKED_REFERRAL" and prev_status != "ASKED_REFERRAL":
                conn.execute(
                    """
                    UPDATE jobs 
                    SET status = ?, 
                        notes = ?, 
                        hr_email = ?,
                        referrer_name = ?,
                        outreach_sent_at = CURRENT_TIMESTAMP
                    WHERE job_id = ?
                    """,
                    (new_status, notes, hr_email, referrer_name, job_id),
                )
            elif new_status in ("ASKED_REFERRAL", "CONNECT_SENT"):
                conn.execute(
                    """
                    UPDATE jobs 
                    SET status = ?, 
                        notes = ?, 
                        hr_email = ?,
                        referrer_name = ?,
                        outreach_sent_at = COALESCE(outreach_sent_at, CURRENT_TIMESTAMP)
                    WHERE job_id = ?
                    """,
                    (new_status, notes, hr_email, referrer_name, job_id),
                )
            elif new_status == "NEW":
                conn.execute(
                    """
                    UPDATE jobs 
                    SET status = ?, 
                        notes = ?, 
                        hr_email = ?,
                        referrer_name = ?,
                        outreach_sent_at = NULL
                    WHERE job_id = ?
                    """,
                    (new_status, notes, hr_email, referrer_name, job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE jobs 
                    SET status = ?, 
                        notes = ?, 
                        hr_email = ?,
                        referrer_name = ?
                    WHERE job_id = ?
                    """,
                    (new_status, notes, hr_email, referrer_name, job_id),
                )
            updated_count += 1
        conn.commit()

    return updated_count


def update_single_job(
    job_id: str,
    new_status: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> None:
    """Updates a single job record directly from UI action buttons."""
    init_db(db_path)
    if new_status is not None:
        update_single_job_status(job_id=job_id, new_status=new_status, notes=notes, db_path=db_path)
    elif notes is not None:
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE jobs SET notes = ? WHERE job_id = ?", (notes, job_id))
            conn.commit()


def update_single_job_status(
    job_id: str,
    new_status: str,
    notes: Optional[str] = None,
    referrer_name: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> None:
    """Updates status and optionally notes & referrer_name for a single job.
    If new_status is 'ASKED_REFERRAL' or 'CONNECT_SENT', sets outreach_sent_at to CURRENT_TIMESTAMP.
    If new_status is 'NEW', clears outreach_sent_at to NULL.
    """
    init_db(db_path)
    st = new_status.strip().upper()
    with sqlite3.connect(db_path) as conn:
        updates = ["status = ?"]
        params: List[Any] = [st]

        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        if referrer_name is not None:
            updates.append("referrer_name = ?")
            params.append(referrer_name)

        if st in ("ASKED_REFERRAL", "CONNECT_SENT"):
            updates.append("outreach_sent_at = CURRENT_TIMESTAMP")
        elif st == "NEW":
            updates.append("outreach_sent_at = NULL")

        params.append(job_id)
        sql = f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?"
        conn.execute(sql, params)
        conn.commit()


def purge_mock_and_invalid_jobs(db_path: Path = DB_PATH) -> int:
    """Deletes any row from jobs where job_url contains fake test URLs or job_id matches test prefixes,
    or lowercase trimmed company name is in ('startup', 'unknown', 'askable'). Returns count of purged rows."""
    init_db(db_path)
    fake_url_patterns = [
        "%razorpay.com/jobs/ai-risk-compliance%",
        "%razorpay.com/jobs/ai-risk%",
        "%databricks.com/company/careers/mosaic-ai%",
        "%databricks.com/jobs/ml%",
        "%cohere.com/careers%",
        "%perplexity.ai/hub/careers%",
        "%example.com%",
        "%localhost%",
    ]
    fake_id_patterns = [
        "test_m5_%",
        "trap%",
    ]
    invalid_companies = ["startup", "unknown", "askable"]

    deleted = 0
    with sqlite3.connect(db_path) as conn:
        for pattern in fake_url_patterns:
            cur = conn.execute("DELETE FROM jobs WHERE job_url LIKE ?", (pattern,))
            deleted += cur.rowcount
        for pattern in fake_id_patterns:
            cur = conn.execute("DELETE FROM jobs WHERE job_id LIKE ?", (pattern,))
            deleted += cur.rowcount
        placeholders = ",".join("?" for _ in invalid_companies)
        cur = conn.execute(
            f"DELETE FROM jobs WHERE LOWER(TRIM(company)) IN ({placeholders})",
            invalid_companies,
        )
        deleted += cur.rowcount
        conn.commit()
    return deleted


def reset_all_statuses_to_new(db_path: Path = DB_PATH) -> int:
    """Resets all non-NEW jobs back to 'NEW' and clears outreach_sent_at to NULL. Returns updated count."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("UPDATE jobs SET status = 'NEW', outreach_sent_at = NULL WHERE status != 'NEW'")
        updated = cur.rowcount
        conn.commit()
    return updated


# Backward compatibility aliases
def get_all_jobs(status_filter: Optional[str] = None, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """Returns all jobs as dictionaries (for backward compatibility)."""
    df = load_jobs_dataframe(status_filter=status_filter, db_path=db_path)
    records = []
    for _, row in df.iterrows():
        d = row.to_dict()
        d["missing_keywords"] = json.loads(d.get("missing_keywords_json") or "[]")
        d["resume_tweaks"] = json.loads(d.get("resume_tweaks_json") or "[]")
        d["contacts"] = json.loads(d.get("contacts_json") or "[]")
        d["outreach_drafts"] = json.loads(d.get("outreach_drafts_json") or "[]")
        records.append(d)
    return records


def update_job_status(job_id: str, new_status: str, db_path: Path = DB_PATH) -> None:
    """Updates status for a job (backward compatibility)."""
    update_single_job(job_id=job_id, new_status=new_status, db_path=db_path)
