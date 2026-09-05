import asyncio
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.evaluation_lab import load_evaluation_lab


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
CURRENT_ANSWER_RUN = Path(
    "docs/evaluation/runs/answer-v3-golden50-expanded14962-rrf-dbsf-20260903"
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
