"""
Pydantic schemas for Talent Search System
Defines all data models used in the system
"""
try:
    from typing import List, Dict, Any, Optional
    from pydantic import BaseModel, Field, ConfigDict, field_validator
    from pathlib import Path
    import sys

    # Use pathlib for robust path handling
    current_dir = Path(__file__).parent
    backend_dir = current_dir.parent
    sys.path.insert(0, str(backend_dir))

    from backend import config
    import utils
    from utils import normalize_whitespace, normalize_url
except Exception as e:
    print(f"Schemas ImportError: {e}")

# ============================ PROGRESS TRACKING SCHEMAS ============================

class ProgressDetail(BaseModel):
    """Detailed progress information for real-time updates"""
    event: str  # Current event/stage name
    progress: float  # Progress percentage (0.0 - 1.0)
    current_action: Optional[str] = None  # What is currently being done
    items_processed: Optional[int] = None  # Number of items processed
    items_total: Optional[int] = None  # Total items to process
    found_candidates: Optional[int] = None  # Current number of candidates found
    target_candidates: Optional[int] = None  # Target number of candidates
    current_candidate: Optional[str] = None  # Name of candidate being processed
    search_terms_batch: Optional[int] = None  # Current batch of search terms
    search_terms_total: Optional[int] = None  # Total number of search term batches
    papers_found: Optional[int] = None  # Number of papers found
    extra_info: Optional[Dict[str, Any]] = None  # Any additional information

# ============================ QUERY AND PLANNING SCHEMAS ============================

class QuerySpec(BaseModel):
    """Structured intent parsed from user query"""
    top_n: int = config.DEFAULT_TOP_N
    years: List[int] = Field(default_factory=lambda: config.DEFAULT_YEARS)
    venues: List[str] = Field(default_factory=lambda: ["ICLR","ICML","NeurIPS"])     # e.g., ["ICLR","ICML","NeurIPS",...]
    keywords: List[str] = Field(default_factory=lambda: ["social simulation","multi-agent"])   # e.g., ["social simulation","multi-agent",...]
    research_field: str = Field(default="Machine Learning", description="Primary research field/direction")  # e.g., "Robotics", "Natural Language Processing"
    must_be_current_student: bool = True
    degree_levels: List[str] = Field(default_factory=lambda: ["PhD","Master"])
    author_priority: List[str] = Field(default_factory=lambda: ["first"])
    extra_constraints: List[str] = Field(default_factory=list)  # Other constraints (region/domain etc.)

    @field_validator("years")
    @classmethod
    def keep_ints(cls, v):
        out = []
        for x in v:
            try:
                out.append(int(x))
            except:
                pass
        return out[:5]

    @field_validator("keywords", "venues", "degree_levels", "author_priority", "extra_constraints")
    @classmethod
    def trim_list(cls, v):
        # Deduplicate while preserving order + limit length
        seen = set()
        out = []
        for s in v:
            s = utils.normalize_whitespace(s)
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out[:32]


# ============================ CLASSIFICATION SCHEMAS ============================

class UserAdjustmentClassification(BaseModel):
    """LLM classification result for user adjustment detection"""
    is_adjustment: bool = Field(..., description="Whether the user input is requesting a change to search parameters")
    help_instruction: str = Field(..., description="Help instruction for the user if not an adjustment")

class SearchValidationResult(BaseModel):
    """LLM validation result for search request"""
    is_valid_search: bool = Field(..., description="Whether the user input contains valid searchable content")
    search_terms_found: List[str] = Field(default_factory=list, description="Search terms extracted from the input")
    missing_elements: List[str] = Field(default_factory=list, description="Missing elements needed for a good search")
    suggestion: str = Field(..., description="Suggestion for improving the search request")


class QuerySpecDiff(BaseModel):
    """Partial update to QuerySpec. Omit fields that are unchanged."""
    top_n: Optional[int] = None
    years: Optional[List[int]] = None
    venues: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    research_field: Optional[str] = None
    must_be_current_student: Optional[bool] = None
    degree_levels: Optional[List[str]] = None
    author_priority: Optional[List[str]] = None
    extra_constraints: Optional[List[str]] = None

    @field_validator("years")
    @classmethod
    def keep_ints(cls, v):
        if v is None:
            return v
        out = []
        for x in v:
            try:
                out.append(int(x))
            except:
                pass
        return out[:5]

    @field_validator("keywords", "venues", "degree_levels", "author_priority", "extra_constraints")
    @classmethod
    def trim_list(cls, v):
        if v is None:
            return v
        seen = set()
        out = []
        for s in v:
            s = utils.normalize_whitespace(s)
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out[:32]

class PlanSpec(BaseModel):
    """Search plan specification"""
    search_terms: List[str] = Field(..., description="Initial search queries.")
    selection_hint: str = Field(..., description="Preferred sources to select.")

    @field_validator("search_terms")
    @classmethod
    def non_empty(cls, v):
        if not v:
            raise ValueError("search_terms cannot be empty")
        return v[:config.MAX_SEARCH_TERMS]

# ============================ SEARCH AND SELECTION SCHEMAS ============================

class LLMSelectSpec(BaseModel):
    """LLM decision for single URL selection"""
    should_fetch: bool = Field(..., description="Whether this URL should be fetched")

class LLMSelectSpecWithValue(BaseModel):
    """LLM decision for single URL selection with value score"""
    should_fetch: bool = Field(..., description="Whether this URL should be fetched")
    value_score: float = Field(..., description="Value score for this URL")
    reason: str = Field(..., description="Reason for the value score")

class LLMSelectSpecHasAuthorInfo(BaseModel):
    """LLM decision for single URL selection with author info"""
    has_author_info: bool = Field(..., description="Whether this URL contains author info")
    confidence: float = Field(..., description="Confidence score for the author info")
    reason: str = Field(..., description="Reason for the author info")

class LLMSelectSpecVerifyIdentity(BaseModel):
    """LLM decision for profile identity verification"""
    is_target_author: bool = Field(..., description="Whether this profile belongs to the target author")
    confidence: float = Field(..., description="Confidence score for identity verification")
    reason: str = Field(..., description="Specific reason for the decision")

class LLMHomepageIdentitySpecSimple(BaseModel):
    """LLM decision for homepage identity verification before content extraction"""
    is_personal_homepage: bool = Field(..., description="Whether this homepage belongs to the target author")
    confidence: float = Field(..., description="Confidence score for homepage identity verification")
    reason: str = Field(..., description="Detailed reason for the verification decision")


class LLMHomepageIdentitySpec(BaseModel):
    """LLM decision for homepage identity verification before content extraction"""
    is_target_author_homepage: bool = Field(..., description="Whether this homepage belongs to the target author")
    confidence: float = Field(..., description="Confidence score for homepage identity verification")
    author_name_found: str = Field(default="", description="Author name found on the homepage")
    research_area_match: bool = Field(default=False, description="Whether research areas match expectations")
    reason: str = Field(..., description="Detailed reason for the verification decision")

class SelectSpec(BaseModel):
    """URL selection specification - keeping existing structure"""
    urls: List[str] = Field(..., description="Up to N URLs worth fetching (http/https).")

    @field_validator("urls")
    @classmethod
    def limit_len(cls, v):
        seen = set()
        out = []
        for u in v:
            nu = utils.normalize_whitespace(u)
            if nu.startswith("http") and nu not in seen:
                seen.add(nu)
                out.append(nu)
        return out[:config.MAX_URLS]
    
class LLMPaperNameSpec(BaseModel):
    """Specification for paper name extraction"""
    have_paper_name: bool = Field(..., description="Whether the paper name is extracted")
    paper_name: str = Field(..., description="The name of the paper")
    
    
# ============================ CONTENT ANALYSIS SCHEMAS ============================

# Removed complex content analysis - keeping it simple for now

# ============================ AUTHOR AND CANDIDATE SCHEMAS ============================

class CandidateCard(BaseModel):
    """Individual candidate information card"""
    name: str = Field(..., alias="Name")
    current_role_affiliation: str = Field(..., alias="Current Role & Affiliation")
    research_focus: List[str] = Field(default_factory=list, alias="Research Focus")
    profiles: Dict[str, str] = Field(default_factory=dict, alias="Profiles")
    notable: Optional[str] = Field(default=None, alias="Notable")
    evidence_notes: Optional[str] = Field(default=None, alias="Evidence Notes")
    model_config = ConfigDict(populate_by_name=True)

class CandidatesSpec(BaseModel):
    """Specification for candidate extraction results"""
    candidates: List[CandidateCard] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    need_more: bool = False
    followups: List[str] = Field(default_factory=list)

class AuthorListSpec(BaseModel):
    """Specification for author list extraction"""
    authors: List[str] = Field(default_factory=list)

    @field_validator("authors")
    @classmethod
    def limit_authors(cls, v):
        seen = set()
        out = []
        for name in v:
            name = normalize_whitespace(name)
            if config.MIN_AUTHOR_NAME_LENGTH <= len(name) <= config.MAX_AUTHOR_NAME_LENGTH and name not in seen:
                seen.add(name)
                out.append(name)
        return out[:config.MAX_AUTHORS]

# ============================ PAPER AND AUTHOR SCHEMAS ============================

class PaperInfo(BaseModel):
    """Information about a paper with deduplication support"""
    paper_name: str = Field(..., description="The extracted paper name")
    urls: List[str] = Field(default_factory=list, description="List of URLs where this paper was found")
    primary_url: Optional[str] = Field(default=None, description="The primary/best URL for this paper")

    @field_validator("paper_name")
    @classmethod
    def normalize_paper_name(cls, v):
        return normalize_whitespace(v)

    @field_validator("urls")
    @classmethod
    def deduplicate_urls(cls, v):
        seen = set()
        out = []
        for url in v:
            if url and url not in seen:
                seen.add(url)
                out.append(url)
        return out

class AuthorWithId(BaseModel):
    """Author information with Semantic Scholar ID"""
    name: str = Field(..., description="Author name")
    author_id: Optional[str] = Field(default=None, description="Semantic Scholar author ID")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v):
        return normalize_whitespace(v)

class PaperAuthorsResult(BaseModel):
    """Result from Semantic Scholar paper search with authors"""
    url: str = Field(..., description="Original URL where paper was found")
    paper_name: str = Field(..., description="Paper title used for search")
    paper_id: Optional[str] = Field(default=None, description="Semantic Scholar paper ID")
    match_score: Optional[float] = Field(default=None, description="Semantic Scholar match score")
    year: Optional[int] = Field(default=None, description="Publication year")
    venue: Optional[str] = Field(default=None, description="Publication venue")
    paper_url: Optional[str] = Field(default=None, description="Semantic Scholar paper URL")
    authors: List[AuthorWithId] = Field(default_factory=list, description="List of authors with IDs")
    found: bool = Field(default=False, description="Whether the paper was found in Semantic Scholar")

class PaperCollection(BaseModel):
    """Collection of unique papers with deduplication"""
    papers: Dict[str, PaperInfo] = Field(default_factory=dict, description="Paper name -> PaperInfo mapping")

    def add_paper(self, paper_name: str, url: str) -> bool:
        """
        Add a paper URL. Returns True if added, False if paper already exists.
        If paper exists, adds URL to existing list if not already present.
        """
        paper_name = normalize_whitespace(paper_name)

        if not paper_name or not url:
            return False

        if paper_name in self.papers:
            # Paper already exists, add URL if not present
            if url not in self.papers[paper_name].urls:
                self.papers[paper_name].urls.append(url)
            return False  # Not newly added

        # New paper
        self.papers[paper_name] = PaperInfo(
            paper_name=paper_name,
            urls=[url],
            primary_url=url
        )
        return True

    def get_all_papers(self) -> List[PaperInfo]:
        """Get all papers as a list"""
        return list(self.papers.values())

    def get_paper_names(self) -> List[str]:
        """Get all paper names"""
        return list(self.papers.keys())

    def get_urls_for_paper(self, paper_name: str) -> List[str]:
        """Get all URLs for a specific paper"""
        paper_name = normalize_whitespace(paper_name)
        if paper_name in self.papers:
            return self.papers[paper_name].urls
        return []

# ============================ AUTHOR PROFILE SCHEMAS ============================

class LLMAuthorProfileSpec(BaseModel):
    """LLM specification for author profile extraction"""
    name: str = Field(default="", description="Author name as written")
    aliases: List[str] = Field(default_factory=list, description="Name variants/aliases of THIS AUTHOR ONLY")
    affiliation_current: str = Field(default="", description="Current affiliation")
    emails: List[str] = Field(default_factory=list, description="Professional emails")
    personal_homepage: str = Field(default="", description="Personal website URL (not current page)")
    homepage_url: str = Field(default="", description="Personal or lab/university page (legacy field)")
    interests: List[str] = Field(default_factory=list, description="Research interests")
    selected_publications: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Selected publications with title/year/venue/url"
    )
    notable_achievements: List[str] = Field(
        default_factory=list,
        description="Awards, honors, fellowships, recognitions"
    )
    social_impact: str = Field(default="", description="H-index, citations, influence metrics")
    career_stage: str = Field(default="", description="Career stage: student/postdoc/assistant_prof/etc")
    social_links: Dict[str, str] = Field(
        default_factory=dict,
        description="Social media and platform links extracted from page"
    )

class HomepageInsightsSpec(BaseModel):
    """Insights extracted specifically from personal website/homepage"""
    current_status: str = Field(default="", description="Concise current status/position as written on homepage")
    role_affiliation_detailed: str = Field(default="", description="Detailed current role and affiliation from homepage")
    research_focus: List[str] = Field(default_factory=list, description="Research focus/themes bullets")
    research_keywords: List[str] = Field(default_factory=list, description="Research keywords/tags")
    highlights: List[str] = Field(default_factory=list, description="News/highlights/awards as listed on homepage")

    @field_validator("research_focus", "research_keywords", "highlights")
    @classmethod
    def _dedup_trim(cls, v):
        seen = set()
        out = []
        for s in v or []:
            s = normalize_whitespace(s)
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out[:16]


class HomepageHighlightsSpec(BaseModel):
    """LLM-curated homepage highlights with brief summary"""
    curated_highlights: List[str] = Field(default_factory=list, description="Curated and summarized highlights from homepage")
    summary: str = Field(default="", description="1–2 sentence summary of highlights")

    @field_validator("curated_highlights")
    @classmethod
    def _dedup_trim_highlights(cls, v):
        seen = set()
        out = []
        for s in v or []:
            s = normalize_whitespace(s)
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out[:16]


class OpenSourceItem(BaseModel):
    """Single open-source project/dataset entry"""
    name: str = Field(default="", description="Project or dataset name")
    type: str = Field(default="", description="project | dataset | library | code")
    url: str = Field(default="", description="URL if present on homepage")
    description: str = Field(default="", description="1-line description as written")


class OpenSourceProjectsSpec(BaseModel):
    """LLM output for open-source projects/datasets"""
    items: List[OpenSourceItem] = Field(default_factory=list)


class AcademicServiceSpec(BaseModel):
    """LLM output for academic service and invited talks"""
    service_roles: List[str] = Field(default_factory=list, description="Committees, editorial roles, organizing")
    invited_talks: List[str] = Field(default_factory=list, description="Invited/keynote talks as listed")

    @field_validator("service_roles", "invited_talks")
    @classmethod
    def _dedup_trim_lists(cls, v):
        seen = set()
        out = []
        for s in v or []:
            s = normalize_whitespace(s)
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out[:24]

# ============================ STATE AND RESEARCH SCHEMAS ============================

class ResearchState(BaseModel):
    """Main state object for the research process"""
    query: str
    round: int = 0
    query_spec: QuerySpec = Field(default_factory=QuerySpec)
    plan: Dict[str, Any] = Field(default_factory=dict)
    serp: List[Dict[str, str]] = Field(default_factory=list)
    selected_urls: List[str] = Field(default_factory=list)
    selected_serp: List[Dict[str, str]] = Field(default_factory=list)
    sources: Dict[str, str] = Field(default_factory=dict)   # url -> text
    report: Optional[str] = None
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    need_more: bool = False
    followups: List[str] = Field(default_factory=list)
    expanded_authors: bool = False

# ============================ UTILITY FUNCTIONS ============================

# Removed create_selection_prompt - now handled directly in graph.py

# ============================ PAPER SCORING SCHEMAS ============================

class PaperScoreSpec(BaseModel):
    """LLM output for paper relevance scoring"""
    score: int = Field(..., ge=1, le=10, description="Relevance score from 1-10, where 10 is most relevant")

class PaperWithScore(BaseModel):
    """Paper with its relevance score"""
    url: str = Field(..., description="URL of the paper")
    title: str = Field(..., description="Title of the paper")
    abstract: str = Field(default="", description="Abstract or snippet of the paper")
    score: int = Field(..., ge=1, le=10, description="Relevance score from 1-10")
    relevant_tier: int = Field(default=0, description="Relevance tier: 1 for highly relevant (>=9), 0 for moderately relevant (6<score<9)")
    completeness_score: float = Field(default=0.0, description="Information completeness score based on metadata availability")
    associated_candidates: List[str] = Field(default_factory=list, description="Names of candidates associated with this paper")
    
    @field_validator("url")
    @classmethod
    def normalize_url_field(cls, v):
        return normalize_url(v)

class SearchResults(BaseModel):
    """Complete search results including candidates and reference papers"""
    recommended_candidates: List['CandidateOverview'] = Field(default_factory=list, description="Top recommended candidates based on score")
    additional_candidates: List['CandidateOverview'] = Field(default_factory=list, description="Additional candidates that may be of interest")
    reference_papers: List[PaperWithScore] = Field(default_factory=list, description="All scored papers with associated candidates")
    total_candidates_found: int = Field(default=0, description="Total number of candidates found")
    search_query: str = Field(default="", description="Original search query")
    
    model_config = ConfigDict(arbitrary_types_allowed=True)

# ============================ EVALUATION & OVERVIEW SCHEMAS ============================

class EvaluationItem(BaseModel):
    """Single evaluation item for one dimension with score and justification"""
    dimension: str = Field(..., description="Dimension name (1–7 in order)")
    score: int = Field(..., ge=1, le=5, description="Score 1–5")
    justification: str = Field(..., description="1–2 sentence justification")

class EvaluationResult(BaseModel):
    """Structured evaluation across seven dimensions"""
    items: List[EvaluationItem] = Field(default_factory=list)
    radar: Dict[str, int] = Field(default_factory=dict, description="Dimension -> score mapping for radar plot")
    total_score: int = Field(default=0, description="Sum of seven dimension scores (max 35)")
    details: Dict[str, str] = Field(default_factory=dict, description="Dimension -> 'x/5 - justification'")

class LLMEvaluationItemSpec(BaseModel):
    """LLM output spec: one evaluation entry"""
    dimension: str = Field(...)
    score: int = Field(..., ge=1, le=5)
    justification: str = Field(...)

class LLMEvaluationResultSpec(BaseModel):
    """LLM output spec: list of seven evaluation entries"""
    items: List[LLMEvaluationItemSpec] = Field(default_factory=list)

class RepresentativePaper(BaseModel):
    """Simplified representative paper entry for demo output"""
    title: str = Field(..., alias="Title")
    venue: str = Field(default="", alias="Venue")
    year: Optional[int] = Field(default=None, alias="Year")
    type: str = Field(default="", alias="Type")
    links: str = Field(default="", alias="Links")
    model_config = ConfigDict(populate_by_name=True)


class LLMRepresentativePapersSpec(BaseModel):
    """LLM output: list of representative papers extracted from homepage"""
    papers: List[RepresentativePaper] = Field(default_factory=list)

class CandidateOverview(BaseModel):
    """Demo-style candidate overview for UI/JSON export"""
    name: str = Field(..., alias="Name")
    email: str = Field(default="", alias="Email")
    current_role_affiliation: str = Field(default="", alias="Current Role & Affiliation")
    current_status: str = Field(default="", alias="Current Status")
    research_keywords: List[str] = Field(default_factory=list, alias="Research Keywords")
    research_focus: List[str] = Field(default_factory=list, alias="Research Focus")
    profiles: Dict[str, str] = Field(default_factory=dict, alias="Profiles")
    publication_overview: List[str] = Field(default_factory=list, alias="Publication Overview")
    top_tier_hits: List[str] = Field(default_factory=list, alias="Top-tier Hits (Last 24 Months)")
    honors_grants: List[str] = Field(default_factory=list, alias="Honors/Grants")
    service_talks: List[str] = Field(default_factory=list, alias="Academic Service / Invited Talks")
    open_source_projects: List[str] = Field(default_factory=list, alias="Open-source / Datasets / Projects")
    representative_papers: List[RepresentativePaper] = Field(default_factory=list, alias="Representative Papers")
    trigger_paper_title: str = Field(default="", alias="Trigger Paper Title")
    trigger_paper_url: str = Field(default="", alias="Trigger Paper URL")
    highlights: List[str] = Field(default_factory=list, alias="Highlights")
    radar: Dict[str, int] = Field(default_factory=dict, alias="Radar")
    total_score: int = Field(default=0, alias="Total Score")
    detailed_scores: Dict[str, str] = Field(default_factory=dict, alias="Detailed Scores")
    model_config = ConfigDict(populate_by_name=True)

# ============================ TASK STATE SCHEMAS FOR INCREMENTAL SEARCH ============================

class SearchTaskState(BaseModel):
    """State snapshot for resumable search tasks"""
    task_id: str = Field(..., description="Unique task ID")
    spec: QuerySpec = Field(..., description="Original query specification")
    
    # Search progress state
    pos: int = Field(default=0, description="Current position in search terms")
    terms: List[str] = Field(default_factory=list, description="All search terms")
    rounds_completed: int = Field(default=0, description="Number of candidate pool processing rounds completed")
    
    # Accumulated results
    candidates_accum: Dict[str, 'CandidateOverview'] = Field(
        default_factory=dict, 
        description="Accumulated candidates {name -> CandidateOverview}"
    )
    all_serp: List[Dict[str, Any]] = Field(default_factory=list, description="All SERP results (flexible schema)")
    sources: Dict[str, str] = Field(default_factory=dict, description="Fetched sources {url -> text}")
    all_scored_papers: Dict[str, PaperWithScore] = Field(
        default_factory=dict,
        description="All scored papers {url -> PaperWithScore}"
    )
    search_candidate_set: List[tuple] = Field(
        default_factory=list,
        description="Set of candidates to process: [(name, id, paper_title, paper_url), ...]"
    )
    
    # Tracking sets (for deduplication)
    selected_urls_set: set = Field(default_factory=set, description="Set of selected URLs")
    selected_serp_url_set: set = Field(default_factory=set, description="Set of SERP URLs")
    
    # Metadata
    created_at: float = Field(default_factory=lambda: __import__('time').time())
    updated_at: float = Field(default_factory=lambda: __import__('time').time())
    
    model_config = ConfigDict(arbitrary_types_allowed=True)


class PartialSearchResults(BaseModel):
    """Partial search results returned during incremental search"""
    task_id: str = Field(..., description="Task ID for resuming")
    need_user_decision: bool = Field(default=False, description="Whether user decision is needed")
    rounds_completed: int = Field(default=0, description="Number of rounds completed")
    total_candidates_found: int = Field(default=0, description="Total candidates found so far")
    current_candidates: List['CandidateOverview'] = Field(
        default_factory=list, 
        description="Current candidates found"
    )
    message: str = Field(default="", description="Status message for user")
    
    model_config = ConfigDict(arbitrary_types_allowed=True)


class SearchTaskAction(BaseModel):
    """Action to perform on a search task"""
    action: str = Field(..., description="Action: 'start', 'resume', or 'finish'")
    task_id: Optional[str] = Field(default=None, description="Task ID (required for resume/finish)")
    spec: Optional[QuerySpec] = Field(default=None, description="Query spec (required for start)")


# Rebuild models to resolve forward references
SearchResults.model_rebuild()
PartialSearchResults.model_rebuild()
# 🔥 Critical: SearchTaskState contains forward refs to CandidateOverview / PaperWithScore
# If we don't rebuild it, runtime validation may treat nested models as plain dicts,
# causing errors like "Input should be a valid dictionary or instance of CandidateOverview".
SearchTaskState.model_rebuild()