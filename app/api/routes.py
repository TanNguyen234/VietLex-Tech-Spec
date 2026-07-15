import uuid
import logfire
from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.dependencies import verify_csrf
from app.services.semantic_cache import check_semantic_cache, save_to_semantic_cache
from app.services.guardrails import check_input_guardrails, check_output_guardrails, redact_pii
from app.services.rag_pipeline import run_advanced_rag
from app.services.evaluator import run_llm_as_judge
from app.database import log_interaction, update_feedback, get_admin_logs, get_admin_stats, get_interaction

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.post("/chat", response_class=HTMLResponse)
async def chat(
    request: Request,
    background_tasks: BackgroundTasks,
    message: str = Form(...),
    csrf_token: str = Form(...),
    csrf_valid: str = Depends(verify_csrf)
):
    message = redact_pii(message)
    trace_id = str(uuid.uuid4())
    
    with logfire.span("Xử lý Chat Request: {message}", message=message) as span:
        # Step 2: Check Semantic Cache
        cached_response = await check_semantic_cache(message)
        if cached_response:
            span.set_attribute("cache_hit", True)
            # Log cached interaction
            await log_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=cached_response,
                contexts=[],
                cached=True
            )
            return templates.TemplateResponse(
                request,
                "chat_message.html", 
                {"user_msg": message, "bot_msg": cached_response, "trace_id": trace_id, "cached": True}
            )
        
        span.set_attribute("cache_hit", False)
        
        # Step 3: Apply NeMo Guardrails (Input Check)
        input_safe, rejection_message = await check_input_guardrails(message)
        if not input_safe:
            span.set_attribute("guardrails_blocked_input", True)
            # Log blocked input interaction
            await log_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=rejection_message,
                contexts=[],
                cached=False,
                input_safe=False,
                rejection_reason="Jailbreak or off-topic input blocked by guardrails"
            )
            return templates.TemplateResponse(
                request,
                "chat_message.html",
                {"user_msg": message, "bot_msg": rejection_message, "trace_id": trace_id}
            )
            
        # Step 4: Run Advanced Retrieval Pipeline (RAG)
        bot_response, context_used = await run_advanced_rag(message)
        
        # Step 5: Apply NeMo Guardrails (Output Check)
        output_safe, fallback_response = await check_output_guardrails(bot_response, context_used, message)
        final_response = bot_response if output_safe else fallback_response
        final_response = redact_pii(final_response)
        rejection_reason = None if output_safe else "Hallucination or unsafe output detected"
        
        # Save log to database
        await log_interaction(
            trace_id=trace_id,
            user_query=message,
            bot_response=final_response,
            contexts=context_used,
            cached=False,
            input_safe=True,
            output_safe=output_safe,
            rejection_reason=rejection_reason
        )
        
        # Step 6: Save interaction to Semantic Cache
        background_tasks.add_task(save_to_semantic_cache, message, final_response)
        
        # Step 8: Trigger Background task: Evaluator
        background_tasks.add_task(run_llm_as_judge, message, context_used, final_response, trace_id)
        
        # Step 9: Return HTML partial response
        return templates.TemplateResponse(
            request,
            "chat_message.html",
            {"user_msg": message, "bot_msg": final_response, "trace_id": trace_id}
        )

@router.post("/api/feedback")
async def feedback(
    trace_id: str = Form(...),
    rating: str = Form(...)
):
    with logfire.span("Xử lý Feedback", trace_id=trace_id, rating=rating):
        await update_feedback(trace_id, rating)
        return {"status": "success", "message": "Thank you for your feedback!"}

@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    stats = await get_admin_stats()
    logs = await get_admin_logs(limit=15, skip=0)
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"stats": stats, "logs": logs, "search": "", "skip": 0, "limit": 15}
    )

@router.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats_partial(request: Request):
    stats = await get_admin_stats()
    return templates.TemplateResponse(
        request,
        "admin_stats.html",
        {"stats": stats}
    )

@router.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs_partial(
    request: Request,
    search: str = "",
    skip: int = 0,
    limit: int = 15
):
    logs = await get_admin_logs(limit=limit, skip=skip, search_query=search)
    return templates.TemplateResponse(
        request,
        "admin_logs.html",
        {"logs": logs, "search": search, "skip": skip, "limit": limit}
    )

@router.get("/admin/details/{trace_id}", response_class=HTMLResponse)
async def admin_details_partial(request: Request, trace_id: str):
    log = await get_interaction(trace_id)
    return templates.TemplateResponse(
        request,
        "admin_details.html",
        {"log": log}
    )
