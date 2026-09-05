from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import get_settings
from app.services.provider_runtime import ProviderEvent, record_provider_event


OFFICIAL_SOURCE_DOMAINS = (
    "vbpl.vn",
    "vbpl.moj.gov.vn",
    "vanban.chinhphu.vn",
    "datafiles.chinhphu.vn",
    "moj.gov.vn",
    "phapdien.moj.gov.vn",
)
_PLAN_VERSION = "official-web-v1"
_SPACE = re.compile(r"\s+")
_QUERY_TOKEN = re.compile(r"[\w/-]+", re.UNICODE)
_QUERY_STOPWORDS = {
    "ai", "bao", "các", "cho", "có", "của", "đang", "điều", "điều kiện",
    "được", "gì", "hiện", "hành", "khi", "là", "một", "nào", "những",
    "phải", "ra", "sao", "theo", "thì", "trong", "và", "về", "với",
}
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

    version: Literal["official-web-v1"] = _PLAN_VERSION
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


def _clean(value: str, limit: int) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()[:limit]


def _plan_id(question: str, steps: list[ResearchPlanStep]) -> str:
    payload = "|".join([_PLAN_VERSION, question, *(step.query for step in steps)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def build_research_plan(question: str) -> ResearchPlan:
    question = _clean(question, 2_000)
    document_number = re.search(
        r"\b\d{1,4}/\d{4}/[A-ZĐ-]{2,30}\b", question.upper()
    )
    tokens = [
        token
        for token in _QUERY_TOKEN.findall(question.casefold())
        if token not in _QUERY_STOPWORDS and len(token) > 1
    ]
    seed = document_number.group(0) if document_number else " ".join(tokens[-4:])
    seed = seed or question
    tail = " ".join(seed.split()[-2:])
    definitions: list[tuple[StepKind, str, str]] = [
        ("legal_basis", "Căn cứ pháp lý trực tiếp", seed),
        ("conditions", "Điều kiện và thủ tục", f"{tail} điều kiện"),
        ("exceptions", "Ngoại lệ và giới hạn", f"{tail} không được"),
        ("amendments", "Sửa đổi và tình trạng hiệu lực", f"{tail} sửa đổi"),
        ("official_verification", "Đối chiếu nguồn chính thức", f"bộ luật {tail}"),
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
    try:
        parsed = urlparse(str(url))
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        return False
    host = parsed.hostname.rstrip(".").casefold()
    declared = str(declared_domain or "").strip().rstrip(".").casefold()

    def allowed(value: str) -> bool:
        return any(
            value == root or value.endswith(f".{root}")
            for root in OFFICIAL_SOURCE_DOMAINS
        )

    if declared and not allowed(declared):
        return False
    return allowed(host)


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

        provider = OfficialPortalClient(settings=settings)

    # User-edited queries receive a new immutable identity at execution time.
    plan_id = _plan_id(plan.question, plan.steps)
    step_results: list[ResearchStepResult] = []
    observed_provider = "chinhphu_official_portal"
    observed_model = "webforms-search-v1"
    for step in plan.steps:
        try:
            result = await provider.search(step.query, limit=3)
        except Exception as error:
            error_kind = str(getattr(error, "kind", type(error).__name__))[:80]
            record_provider_event(
                ProviderEvent(
                    provider="chinhphu_official_portal",
                    model="webforms-search-v1",
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
        record_provider_event(
            ProviderEvent(
                provider=result.provider,
                model="webforms-search-v1",
                use_case="deep_research",
                call_kind="http",
                success=True,
                error_kind=None,
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
        step_results.append(
            ResearchStepResult(
                step_id=step.step_id,
                title=step.title,
                query=step.query,
                status=step_status,
                sources=list(unique_sources.values()),
                executed_queries=[step.query],
            )
        )

    completed = sum(step.status == "results_found" for step in step_results)
    status = "complete" if completed == len(step_results) else ("partial" if completed else "failed")
    return DeepResearchResult(
        status=status,
        question=plan.question,
        plan_id=plan_id,
        steps=step_results,
        provider=observed_provider,
        model=observed_model,
    )
