from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import get_settings
from app.services.provider_runtime import ProviderEvent, record_provider_event
from app.services.web_source_tiers import TIER1_OFFICIAL_DOMAINS, classify_web_source_tier


OFFICIAL_SOURCE_DOMAINS = TIER1_OFFICIAL_DOMAINS
_PLAN_VERSION = "official-web-v3"
_SPACE = re.compile(r"\s+")
_QUERY_TOKEN = re.compile(r"[\w/-]+", re.UNICODE)
_QUERY_STOPWORDS = {
    "ai", "bao", "các", "cho", "có", "của", "đang", "điều", "điều kiện",
    "được", "gì", "hiện", "hành", "khi", "là", "một", "nào", "những",
    "phải", "ra", "sao", "theo", "thì", "trong", "và", "về", "với",
}
_RELEVANCE_STOPWORDS = _QUERY_STOPWORDS | {"xét", "tại", "ngày", "tháng", "năm", "thế", "do", "nhà", "nước", "quản", "lý"}
_TRAILING_INTERROGATIVE_RE = re.compile(
    r"\s*(?:hiện\s+nay\s+|hiện\s+tại\s+|mới\s+nhất\s+)?(?:là\s+)?"
    r"(?:bao\s+nhiêu(?:\s+\w+){0,2}|như\s+thế\s+nào|thế\s+nào|ra\s+sao|"
    r"ở\s+đâu|cơ\s+quan\s+nào|có\s+được\s+không|được\s+không|"
    r"phải\s+không|hay\s+không)\s*[?.!]*$",
    re.IGNORECASE,
)
_TAIL_FILLER_WORDS = frozenset(
    {"nhiêu", "tiền", "nay", "mới", "nhất", "đâu", "sao", "thế", "như", "không", "chưa", "mấy", "lâu"}
)
StepKind = Literal[
    "legal_basis",
    "conditions",
    "exceptions",
    "amendments",
    "official_verification",
]


class DeepResearchDisabled(RuntimeError):
    pass


class ResearchPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: StepKind
    kind: StepKind
    title: str = Field(min_length=1, max_length=160)
    query: str = Field(min_length=1, max_length=500)


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["official-web-v1", "official-web-v2", "official-web-v3"] = _PLAN_VERSION
    query_method: Literal["literal", "model_keywords", "fallback"] = "literal"
    planner_error: str | None = Field(default=None, max_length=100)
    planner_provider: str | None = Field(default=None, max_length=100)
    planner_model: str | None = Field(default=None, max_length=100)
    plan_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    status: Literal["draft"] = "draft"
    question: str = Field(min_length=1, max_length=2_000)
    steps: list[ResearchPlanStep] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_step_contract(self):
        expected = [
            "legal_basis",
            "conditions",
            "exceptions",
            "amendments",
            "official_verification",
        ]
        if [step.step_id for step in self.steps] != expected:
            raise ValueError("research plan steps are incomplete or out of order")
        if any(step.step_id != step.kind for step in self.steps):
            raise ValueError("research plan step identity is inconsistent")
        if not self.question.strip() or any(not step.query.strip() for step in self.steps):
            raise ValueError("research plan question and queries are required")
        return self


class OfficialResearchSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    domain: str
    url: str
    document_number: str = ""
    issued_date: str = ""
    snippet: str = ""
    source_type: Literal["official_government"] = "official_government"


class ResearchStepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    title: str
    query: str
    status: Literal[
        "results_found",
        "partial_results",
        "no_results",
        "provider_error",
    ]
    sources: list[OfficialResearchSource] = Field(default_factory=list, max_length=10)
    executed_queries: list[str] = Field(default_factory=list, max_length=20)
    error_kind: str | None = None


class DeepResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["complete", "partial", "failed"]
    question: str
    plan_id: str
    steps: list[ResearchStepResult] = Field(max_length=5)
    provider: str | None = None
    model: str | None = None


def _title_relevance(question: str, source: OfficialResearchSource) -> float:
    terms = {word for word in _QUERY_TOKEN.findall(question.casefold())
             if len(word) > 1 and not word[0].isdigit() and word not in _RELEVANCE_STOPWORDS}
    if not terms:
        return 0.0
    title = set(_QUERY_TOKEN.findall(source.title.casefold()))
    return len(terms & title) / len(terms)


def _clean(value: str, limit: int) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()[:limit]


def _plan_id(question: str, steps: list[ResearchPlanStep]) -> str:
    payload = "|".join([_PLAN_VERSION, question, *(step.query for step in steps)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _natural_question_seed(issue: str, tokens: list[str]) -> str:
    from app.services.legal_topic_terms import extract_official_topic_phrases
    from app.services.official_search_plan import sanitized_subject

    trailing_slice = tokens[-4:]
    if not _TRAILING_INTERROGATIVE_RE.search(issue) and not (
        set(trailing_slice) & _TAIL_FILLER_WORDS
    ):
        return " ".join(trailing_slice)

    stripped = _TRAILING_INTERROGATIVE_RE.sub(" ", issue)
    stripped = re.sub(r"\b(?:hiện nay|hiện tại|mới nhất)\b", " ", stripped, flags=re.I)
    subj = sanitized_subject(stripped)
    if subj:
        subj_words = [w for w in subj.split() if w not in _TAIL_FILLER_WORDS]
        if len(subj_words) >= 2:
            return " ".join(subj_words[:5])
    topics = extract_official_topic_phrases(stripped, limit=3)
    if topics:
        return " ".join(topics[:2])
    clean_tokens = [t for t in tokens if t not in _TAIL_FILLER_WORDS]
    return " ".join((clean_tokens[:4] or trailing_slice))


def build_research_plan(question: str) -> ResearchPlan:
    question = _clean(question, 2_000)
    document_number = re.search(
        r"\b\d{1,4}/\d{4}/[A-ZĐ][A-ZĐ0-9-]{1,29}\b", question.upper()
    )
    named_law = re.search(r"\b(?:bộ luật|luật)\s+[^?!.;\n]{2,100}?\b(?:19|20)\d{2}\b", question.casefold())
    as_of_pattern = r"\b(?:xét\s+)?tại\s+ngày\s+\d{1,2}[/.-]\d{1,2}[/.-]\d{4}"
    has_as_of = bool(re.search(as_of_pattern, question, flags=re.I))
    without_as_of = re.sub(as_of_pattern, " ", question, flags=re.I).strip(" ,.;?")
    issue = (re.split(r"[?.;]|\bvà\b|\bnhưng\b", without_as_of, maxsplit=1, flags=re.I)[0]
             if has_as_of else question)
    tokens = [
        token
        for token in _QUERY_TOKEN.findall(issue.casefold())
        if token not in _QUERY_STOPWORDS and len(token) > 1
    ]
    seed = (
        document_number.group(0)
        if document_number
        else named_law.group(0)
        if named_law
        else (" ".join(tokens[:4]) if has_as_of else _natural_question_seed(issue, tokens))
    )
    seed = seed or question
    verification = (" ".join(tokens[2:10]) if has_as_of and len(tokens) >= 8
                    and not document_number and not named_law else seed)
    definitions: list[tuple[StepKind, str, str]] = [
        ("legal_basis", "Căn cứ pháp lý trực tiếp", seed),
        ("conditions", "Điều kiện và thủ tục", f"{seed} điều kiện"),
        ("exceptions", "Ngoại lệ và giới hạn", f"{seed} không được"),
        ("amendments", "Sửa đổi và tình trạng hiệu lực", f"{seed} sửa đổi"),
        ("official_verification", "Đối chiếu nguồn chính thức", verification),
    ]
    steps = [
        ResearchPlanStep(
            step_id=kind,
            kind=kind,
            title=title,
            query=_clean(search_query, 500),
        )
        for kind, title, search_query in definitions
    ]
    return ResearchPlan(plan_id=_plan_id(question, steps), question=question, steps=steps)


def is_official_source(url: str, declared_domain: str = "") -> bool:
    return classify_web_source_tier(url, declared_domain or None) == "official_primary"


def _source_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


async def run_deep_research(
    plan: ResearchPlan,
    *,
    provider=None,
    settings=None,
) -> DeepResearchResult:
    settings = settings or get_settings()
    if not settings.OFFICIAL_WEB_RESEARCH_ENABLED:
        raise DeepResearchDisabled("official web research is disabled")
    if provider is None:
        from app.services.official_web_search import OfficialPortalClient
        from app.services.congbao_search import CongBaoClient
        from app.services.federated_official_search import BraveOfficialClient, FederatedOfficialClient
        from app.services.tavily_search import TavilyOfficialClient, is_tavily_search_enabled

        web = None
        if getattr(settings, "OFFICIAL_BRAVE_SEARCH_ENABLED", False):
            if not getattr(settings, "BRAVE_SEARCH_API_KEY", None):
                raise DeepResearchDisabled("brave_search_not_configured")
            web = BraveOfficialClient(settings=settings)
        tavily = TavilyOfficialClient(settings=settings) if is_tavily_search_enabled(settings) else None
        provider = FederatedOfficialClient(
            portal=OfficialPortalClient(settings=settings),
            gazette=CongBaoClient(settings=settings),
            tavily=tavily,
            web=web,
        )

    # User-edited queries receive a new immutable identity at execution time.
    plan_id = _plan_id(plan.question, plan.steps)
    step_results: list[ResearchStepResult] = []
    observed_provider = getattr(provider, "provider", "chinhphu_official_portal")
    observed_model = getattr(provider, "method", "webforms-search-v1")
    for step in plan.steps:
        try:
            result = await provider.search(step.query, limit=3)
        except Exception as error:
            error_kind = str(getattr(error, "kind", type(error).__name__))[:80]
            record_provider_event(
                ProviderEvent(
                    provider=observed_provider,
                    model=observed_model,
                    use_case="deep_research",
                    call_kind="http",
                    success=False,
                    error_kind=error_kind,
                    latency_ms=getattr(error, "latency_ms", None),
                    fallback_used=False,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    request_count=getattr(error, "request_count", None),
                )
            )
            step_results.append(
                ResearchStepResult(
                    step_id=step.step_id,
                    title=step.title,
                    query=step.query,
                    status="provider_error",
                    error_kind=error_kind,
                )
            )
            continue

        observed_provider = result.provider
        observed_model = getattr(result, "method", "webforms-search-v1")
        record_provider_event(
            ProviderEvent(
                provider=result.provider,
                model=observed_model,
                use_case="deep_research",
                call_kind="http",
                success=not bool(getattr(result, "errors", ())),
                error_kind=";".join(getattr(result, "errors", ())) or None,
                latency_ms=result.latency_ms,
                fallback_used=False,
                timestamp=datetime.now(timezone.utc).isoformat(),
                request_count=result.request_count,
            )
        )
        unique_sources: dict[str, OfficialResearchSource] = {}
        for item in result.results:
            url = _clean(getattr(item, "url", ""), 2_000)
            domain = _clean(getattr(item, "domain", ""), 255).casefold()
            if not is_official_source(url, domain):
                continue
            source = OfficialResearchSource(
                source_id=_source_id(url),
                title=_clean(getattr(item, "title", ""), 500) or domain,
                domain=(domain if any(
                    domain == root or domain.endswith(f".{root}")
                    for root in OFFICIAL_SOURCE_DOMAINS
                ) else (urlparse(url).hostname or domain)),
                url=url,
                document_number=_clean(getattr(item, "document_number", ""), 200),
                issued_date=_clean(getattr(item, "issued_date", ""), 50),
                snippet=_clean(getattr(item, "snippet", ""), 1_000),
            )
            unique_sources.setdefault(source.source_id, source)
            if len(unique_sources) >= 10:
                break
        step_status = "results_found" if unique_sources else "no_results"
        if getattr(result, "errors", ()):
            step_status = "partial_results" if unique_sources else "provider_error"
        step_results.append(
            ResearchStepResult(
                step_id=step.step_id,
                title=step.title,
                query=step.query,
                status=step_status,
                error_kind=";".join(getattr(result, "errors", ()))[:80] or None,
                sources=list(unique_sources.values()),
                executed_queries=[step.query],
            )
        )

    if not re.search(r"\b\d{1,4}/\d{4}/[A-ZĐ][A-ZĐ0-9-]{1,29}\b", plan.question.upper()):
        strongest = max((_title_relevance(plan.question, source)
                         for step in step_results for source in step.sources), default=0.0)
        if strongest >= 0.5:
            for step in step_results:
                step.sources = [source for source in step.sources
                                if _title_relevance(plan.question, source) >= strongest * 0.5]
                if not step.sources:
                    step.status = "provider_error" if step.error_kind else "no_results"
    completed = sum(step.status == "results_found" for step in step_results)
    status = "complete" if completed == len(step_results) else ("partial" if any(step.sources for step in step_results) else "failed")
    return DeepResearchResult(
        status=status,
        question=plan.question,
        plan_id=plan_id,
        steps=step_results,
        provider=observed_provider,
        model=observed_model,
    )
