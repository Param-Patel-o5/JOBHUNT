from typing import List, Optional, Literal, Annotated, Tuple
from pydantic import BaseModel, Field
from typing_extensions import TypedDict
import operator


class JobPosting(BaseModel):
    job_id: str = Field(description="Deterministic hash or platform ID")
    company: str
    role: str
    location: str
    jd_text: str
    job_url: str
    source: str = Field(description="linkedin, wellfound, greenhouse, lever, ashby, etc.")
    posted_date: Optional[str] = None
    extracted_max_yoe: Optional[int] = None
    required_yoe: Optional[int] = Field(default=0, description="Minimum required years of experience extracted from JD")


class CompanyIntel(BaseModel):
    company_name: str
    funding_or_stage: str = Field(description="e.g., Series B ($35M), Public MNC, Bootstrapped")
    estimated_size: str = Field(description="e.g., 50-200, 1000+")
    est_entry_ai_ctc_lpa: float = Field(description="Estimated CTC in LPA for entry-level AI roles in India")
    passes_quality_bar: bool = Field(description="True if established/well-funded and likely >= 15 LPA")
    summary_2_lines: str = Field(description="3 to 4 sentence plain-English paragraph explaining what product they build, who customers are, funding/scale, and engineering focus")
    rejection_reason: Optional[str] = None
    hr_email: Optional[str] = Field(default="", description="Discovered or patterned HR/recruiting email")


class MatchAndTailorResult(BaseModel):
    match_score: int = Field(ge=0, le=100)
    selected_project_id: str = Field(description="ID of the best matching project from profile_context.yaml")
    winning_hook_sentence: str = Field(description="1-2 plain-English sentences explaining specifically which component of candidate's project directly aligns with which specific requirement in this company's JD")
    missing_keywords: List[str] = Field(description="Important JD keywords missing or weak in standard profile")
    resume_bullet_tweaks: List[str] = Field(default_factory=list, description="2 copy-pasteable resume bullet lines written in first-person action format")
    jd_core_requirements: List[str] = Field(default_factory=list, description="4 to 5 concise plain-English bullet points summarizing what this role builds and the exact skills/stack required by the JD")


class ContactPerson(BaseModel):
    name: str
    headline: str
    linkedin_url: str
    tier: Literal["1_ALUMNI", "2_TEAM_ENGINEER_OR_HM", "3_RECRUITER"]
    relevance_note: str = Field(description="Why this person was picked, e.g., 'BITS Pilani 2023 alum working on ML infra'")


class OutreachPackage(BaseModel):
    contact_name: str
    contact_tier: str
    linkedin_url: str
    connection_note_300_chars: str = Field(description="Strict <=190 char note for LinkedIn free-tier 'Add a note' modal (Mentor/Advice frame, zero referral ask)")
    full_dm_under_95_words: str = Field(description="Full message once connected (<=85 words, plain-English proof, low-hassle referral ask + advice)")


class EnrichedJobRecord(BaseModel):
    job: JobPosting
    company_intel: CompanyIntel
    match_result: MatchAndTailorResult
    contacts: List[ContactPerson] = Field(default_factory=list)
    outreach_drafts: List[OutreachPackage] = Field(default_factory=list)
    fallback_direct_apply_note: Optional[str] = None
    hr_email: Optional[str] = Field(default="", description="HR or recruiting email for the company")
    referrer_name: Optional[str] = Field(default="", description="Comma-separated names of discovered contacts")
    status: Optional[str] = Field(default=None, description="Pipeline stage, defaults to NEW or REJECTED")


# LangGraph Shared State
class JobHuntGraphState(TypedDict, total=False):
    raw_jobs: Annotated[List[JobPosting], operator.add]
    filtered_jobs: List[JobPosting]
    company_intel_pairs: List[Tuple[JobPosting, CompanyIntel]]
    enriched_jobs: Annotated[List[EnrichedJobRecord], operator.add]
