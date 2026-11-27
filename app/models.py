from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


FactStatus = Literal["confirmed", "partial", "denied"]
ProviderType = Literal["local", "gemini", "openai", "anthropic", "ollama"]


class CVProfileUpdate(BaseModel):
    full_name: str = ""
    headline: str = ""
    raw_text: str = Field(..., min_length=10)
    filename: Optional[str] = None


class KnowledgeFactCreate(BaseModel):
    topic: str = Field(..., min_length=1, max_length=200)
    category: str = "Habilidad técnica"
    status: FactStatus = "confirmed"
    details: str = ""
    source: str = "manual"


class KnowledgeFactUpdate(BaseModel):
    topic: Optional[str] = None
    category: Optional[str] = None
    status: Optional[FactStatus] = None
    details: Optional[str] = None


class FetchUrlRequest(BaseModel):
    url: str = Field(..., min_length=5)


class AnalyzeJobRequest(BaseModel):
    source_url: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    job_description: Optional[str] = None
    target_language: str = "auto"  # auto, es, en


class QuestionAnswerItem(BaseModel):
    question_id: str
    topic: str
    category: str = "Habilidad técnica"
    status: FactStatus  # confirmed, partial, denied
    details: str = ""
    save_to_knowledge: bool = True


class SubmitAnswersRequest(BaseModel):
    answers: list[QuestionAnswerItem] = Field(default_factory=list)
    extra_instructions: str = ""
    target_language: str = "auto"


class AdaptCVRequest(BaseModel):
    extra_instructions: str = ""
    target_language: str = "auto"


class UpdateAdaptedCVRequest(BaseModel):
    adapted_cv_markdown: str = Field(..., min_length=10)


class SettingsUpdate(BaseModel):
    provider: ProviderType = "local"
    api_key: Optional[str] = None  # None = keep existing, "" = clear
    model: str = ""
    base_url: str = ""
    default_language: str = "auto"
    tone: str = "profesional y directo"


class TestAIRequest(BaseModel):
    provider: Optional[ProviderType] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None


class SearchPreferencesUpdate(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    location: str = "España"
    country: str = "España"
    modality: str = "all"  # all, remote, hybrid, onsite
    experience_level: str = "mid"  # junior, mid, senior, lead, all
    keywords_include: list[str] = Field(default_factory=list)
    keywords_exclude: list[str] = Field(default_factory=list)
    min_salary: Optional[int] = None
    preferred_sources: list[str] = Field(default_factory=lambda: ["linkedin", "infojobs", "remotive", "arbeitnow", "jobicy", "wwr"])


class JobSearchQuery(BaseModel):
    query: Optional[str] = None
    location: Optional[str] = None
    country: Optional[str] = "España"
    modality: Optional[str] = None
    source: Optional[str] = None
    from_cv: bool = False
    min_score: int = 0
    limit: int = 40


class DiscoveredJobStatusUpdate(BaseModel):
    status: Literal["new", "saved", "dismissed", "applied"]


class ConvertToAnalysisRequest(BaseModel):
    target_language: str = "auto"
    extra_instructions: str = ""


# --- Multi-Profile Models ---

class CVProfileCreate(BaseModel):
    profile_name: str = Field(..., min_length=1, max_length=120)
    full_name: str = ""
    headline: str = ""
    raw_text: str = ""
    filename: Optional[str] = None
    set_active: bool = True


class CVProfileUpdateModel(BaseModel):
    profile_name: Optional[str] = None
    full_name: Optional[str] = None
    headline: Optional[str] = None
    raw_text: Optional[str] = None
    filename: Optional[str] = None


# --- Cover Letter, Pitch & Interview Simulator Models ---

class GenerateCoverLetterRequest(BaseModel):
    tone: str = "profesional y convincente"
    target_language: str = "auto"
    extra_instructions: str = ""


class GenerateRecruiterPitchRequest(BaseModel):
    channel: Literal["linkedin", "email"] = "linkedin"
    recipient_name: Optional[str] = None
    target_language: str = "auto"


class GenerateInterviewPrepRequest(BaseModel):
    target_language: str = "auto"


# --- Application Tracker Models ---

ApplicationTrackerStage = Literal["saved", "adapted", "applied", "interviewing", "offered", "rejected"]


class ApplicationTrackerCreate(BaseModel):
    job_title: str = Field(..., min_length=1)
    company: str = Field(..., min_length=1)
    location: str = ""
    source_url: str = ""
    stage: ApplicationTrackerStage = "saved"
    salary_discussed: str = ""
    contact_name: str = ""
    contact_email: str = ""
    notes: str = ""
    applied_at: Optional[str] = None
    next_followup_at: Optional[str] = None
    job_analysis_id: Optional[int] = None
    discovered_job_id: Optional[int] = None


class ApplicationTrackerUpdate(BaseModel):
    job_title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    source_url: Optional[str] = None
    stage: Optional[ApplicationTrackerStage] = None
    salary_discussed: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    applied_at: Optional[str] = None
    next_followup_at: Optional[str] = None


# --- Daily Digest Models ---

class RunDigestRequest(BaseModel):
    profile_id: Optional[int] = None
    min_score: int = 70
    limit: int = 10


# --- Bookmarklet Ingestion ---

class BookmarkletCaptureRequest(BaseModel):
    url: str
    title: str = ""
    company: str = ""
    text: str = ""
    html: Optional[str] = None


