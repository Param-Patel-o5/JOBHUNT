"""
Evaluation & Match Scoring Node (evaluate.py).

Scores each (JobPosting, CompanyIntel) pair against the candidate's profile,
selects the best matching project, generates a winning hook sentence,
and suggests resume bullet tweaks.

Enforces a strict match score floor (>= 75%):
Jobs scoring < 75% are immediately marked as 'REJECTED' in SQLite and excluded
from the active queue so the candidate only sees high-signal, high-confidence opportunities.
"""

import yaml
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Any

from src.models import JobPosting, CompanyIntel, MatchAndTailorResult
from src.llm_router import invoke_structured_llm
from src.db import save_rejected_evaluated_job

logger = logging.getLogger("intelligence.evaluate")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

PROFILE_PATH = Path("config/profile_context.yaml")
MATCH_SCORE_FLOOR = 75


def _load_profile() -> Dict[str, Any]:
    """Loads the candidate profile context from YAML."""
    if not PROFILE_PATH.exists():
        logger.error(f"Profile config not found at {PROFILE_PATH}")
        return {}
    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _build_project_arsenal_text(profile: Dict[str, Any]) -> str:
    """Formats the project arsenal into a text block for the prompt."""
    projects = profile.get("project_arsenal", [])
    lines = []
    for p in projects:
        pid = p.get("id", "unknown")
        name = p.get("name", "")
        one_liner = p.get("one_liner", "")
        tags = ", ".join(p.get("tags", []))
        best_for = ", ".join(p.get("best_for_jd_keywords", []))
        lines.append(
            f"- ID: {pid}\n"
            f"  Name: {name}\n"
            f"  One-liner: {one_liner}\n"
            f"  Tags: {tags}\n"
            f"  Best for JD keywords: {best_for}"
        )
    return "\n".join(lines)


def _build_match_prompt(
    job: JobPosting,
    intel: CompanyIntel,
    profile: Dict[str, Any],
    arsenal_text: str,
) -> str:
    """Builds the structured prompt for MatchAndTailorResult."""
    candidate = profile.get("candidate", {})
    name = candidate.get("name", "Candidate")
    university = candidate.get("university", "")
    degree = candidate.get("degree", "")
    grad_year = candidate.get("graduation_year", "")

    return f"""You are a career strategist for {name}, a {grad_year} graduate from {university} ({degree}), applying to AI/ML/LLM Engineer roles in India.

COMPANY CONTEXT:
- Company: {intel.company_name}
- Stage: {intel.funding_or_stage} | Size: {intel.estimated_size}
- Summary: {intel.summary_2_lines}
- Est. Entry AI CTC: {intel.est_entry_ai_ctc_lpa} LPA

JOB POSTING:
- Role: {job.role}
- Location: {job.location}
- Source: {job.source}
- Required YoE: {getattr(job, 'required_yoe', 0)}
- JD (first 2000 chars):
{job.jd_text[:2000] if job.jd_text else "No JD available."}

CANDIDATE'S PROJECT ARSENAL:
{arsenal_text}

SCORING & SELECTION RULES:
1. match_score (0-100): Score objectively based on candidate's portfolio alignment with JD requirements.
   - 85-100: Exceptional alignment, hands-on LLM/agentic/RAG overlap with candidate's actual projects
   - 75-84: Strong match, core requirements covered cleanly
   - 50-74: Partial match with noticeable skill or stack gaps (will be filtered out)
   - 0-49: Poor match or non-AI track misalignment

2. selected_project_id: Choose the SINGLE best project from the arsenal. Rules:
   - "agent_diagnostician" for agentic AI, LangGraph, multi-agent, LLM evaluation, observability roles
   - "tempus_rag" for RAG, retrieval, NLP, search, embeddings, knowledge graph, financial AI roles
   - "lidar_parser" for C++, systems engineering, computer vision, robotics, low-latency, inference optimization roles
   - "fairtrace" ONLY for fintech, banking, risk, credit, compliance, governance, tabular ML, fairness roles
   - When in doubt between agent_diagnostician and tempus_rag, prefer agent_diagnostician for general AI/ML/LLM roles.

3. jd_core_requirements: Provide exactly 4 to 5 concise plain-English bullet points summarizing what this role builds and the exact skills/stack required by the JD.

4. winning_hook_sentence: Write 1-2 plain-English sentences. Do NOT just repeat a hardcoded template from YAML! Explain specifically WHICH component/feature of the candidate's selected project directly solves or aligns with WHICH specific requirement in this company's JD (zero academic or robotic jargon).

5. missing_keywords: List 3-6 important JD keywords/skills that are weak or missing in the candidate's standard profile. Focus on specific tools, frameworks, or domain expertise mentioned in JD.

6. resume_bullet_tweaks: Provide exactly 2 actual copy-pasteable resume bullet lines written in first-person action format (e.g., "Engineered X using [JD Keyword] to achieve Y..."), NOT vague meta-instructions like "Add mention of Guardrails".

Return a structured MatchAndTailorResult object."""


def score_and_tailor_jobs(
    job_intel_pairs: List[Tuple[JobPosting, CompanyIntel]],
    max_jobs_to_score: int = 15,
) -> List[Tuple[JobPosting, CompanyIntel, MatchAndTailorResult]]:
    """
    Scores and tailors each job-company pair against the candidate profile.
    Enforces a strict match score floor (>= 75%).

    Args:
        job_intel_pairs: List of (JobPosting, CompanyIntel) that passed company intel gate.
        max_jobs_to_score: Maximum number of jobs to score (budget control).

    Returns:
        List of (JobPosting, CompanyIntel, MatchAndTailorResult) for jobs with match_score >= 75%,
        sorted by match_score descending.
    """
    profile = _load_profile()
    if not profile:
        logger.error("Cannot score jobs: profile_context.yaml not loaded")
        return []

    arsenal_text = _build_project_arsenal_text(profile)
    pairs_to_score = job_intel_pairs[:max_jobs_to_score]

    tier = "smart" if len(pairs_to_score) <= 10 else "lite"
    logger.info(
        f"[Evaluate] Scoring {len(pairs_to_score)} jobs (of {len(job_intel_pairs)} total) "
        f"using '{tier}' tier with {MATCH_SCORE_FLOOR}% match floor"
    )

    passing_results: List[Tuple[JobPosting, CompanyIntel, MatchAndTailorResult]] = []

    for i, (job, intel) in enumerate(pairs_to_score, 1):
        prompt = _build_match_prompt(job, intel, profile, arsenal_text)

        try:
            match_result = invoke_structured_llm(MatchAndTailorResult, prompt, tier=tier)
            score = match_result.match_score

            if score < MATCH_SCORE_FLOOR:
                logger.warning(
                    f"[Evaluate Floor Reject] [{i}/{len(pairs_to_score)}] {job.company} - {job.role}: "
                    f"score={score} < {MATCH_SCORE_FLOOR}%. Marked as REJECTED in DB."
                )
                save_rejected_evaluated_job(
                    job, intel, match_result,
                    rejection_reason=f"Match score below floor ({score}% < {MATCH_SCORE_FLOOR}%)"
                )
            else:
                logger.info(
                    f"[Evaluate Floor Pass] [{i}/{len(pairs_to_score)}] {job.company} - {job.role}: "
                    f"score={score} >= {MATCH_SCORE_FLOOR}%, project={match_result.selected_project_id}"
                )
                passing_results.append((job, intel, match_result))

        except Exception as e:
            logger.error(f"[Evaluate] Failed to score {job.company} - {job.role}: {e}")
            fallback = MatchAndTailorResult(
                match_score=0,
                selected_project_id="agent_diagnostician",
                winning_hook_sentence="LLM scoring failed for this job posting.",
                missing_keywords=["evaluation_failed"],
                resume_bullet_tweaks=["Unable to generate tailored bullets due to LLM error."],
            )
            save_rejected_evaluated_job(
                job, intel, fallback,
                rejection_reason="LLM evaluation error / exception"
            )

    # Sort passing jobs by match_score descending
    passing_results.sort(key=lambda x: x[2].match_score, reverse=True)

    logger.info(
        f"[Evaluate] {len(passing_results)} / {len(pairs_to_score)} jobs passed the >={MATCH_SCORE_FLOOR}% threshold. "
        f"Top score: {passing_results[0][2].match_score if passing_results else 'N/A'}"
    )

    return passing_results
