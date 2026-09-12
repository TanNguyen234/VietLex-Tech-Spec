import asyncio
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.paths import APP_ROOT

from app.services.evaluation_lab import load_evaluation_lab
from app.api.dependencies import require_admin


router = APIRouter()
templates = Jinja2Templates(directory=APP_ROOT / "templates")
CURRENT_ANSWER_RUN = APP_ROOT.parent / Path(
    "docs/evaluation/runs/answer-v3-golden50-expanded14962-rrf-dbsf-20260903"
)
RUNS_ROOT = APP_ROOT.parent / "docs/evaluation/runs"


def _available_runs() -> list[str]:
    root = RUNS_ROOT.resolve()
    if not root.is_dir():
        return []
    return sorted(
        [
            path.name
            for path in root.iterdir()
            if re.fullmatch(r"[A-Za-z0-9_-]{1,160}", path.name)
            and path.is_dir()
            and path.resolve().parent == root
            and (path / "manifest.json").is_file()
            and any(
                (path / f"{kind}_results.json").is_file()
                for kind in ("answer", "retrieval")
            )
        ],
        reverse=True,
    )


@router.get("/admin/evaluations", response_class=HTMLResponse)
async def admin_evaluations(
    request: Request,
    run: str = Query(default="", max_length=160),
    case: str = Query(default="", max_length=100),
    _admin: dict = Depends(require_admin),
):
    try:
        runs = await asyncio.to_thread(_available_runs)
    except (OSError, RuntimeError):
        return templates.TemplateResponse(
            request,
            "evaluation_lab.html",
            {
                "lab": {
                    "status": "unavailable",
                    "error_kind": "run_catalog_unavailable",
                },
                "admin_view": True,
                "page_title": "Chất lượng và kiểm chứng",
                "runs": [],
                "selected_run": "",
                "selected_case_id": "",
            },
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    selected = run or (
        CURRENT_ANSWER_RUN.name
        if CURRENT_ANSWER_RUN.name in runs
        else next(iter(runs), "")
    )
    if selected and selected not in runs:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    lab = await asyncio.to_thread(
        load_evaluation_lab, RUNS_ROOT / selected, case_id=case or None
    )
    return templates.TemplateResponse(
        request,
        "evaluation_lab.html",
        {
            "lab": lab,
            "selected_case_id": case,
            "admin_view": True,
            "page_title": "Chất lượng và kiểm chứng",
            "runs": runs,
            "selected_run": selected,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/evaluation-lab", response_class=HTMLResponse)
async def evaluation_lab(
    request: Request, case: str = Query(default="", max_length=100)
):
    lab = await asyncio.to_thread(
        load_evaluation_lab, CURRENT_ANSWER_RUN, case_id=case or None
    )
    return templates.TemplateResponse(
        request, "evaluation_lab.html", {"lab": lab, "selected_case_id": case}
    )
