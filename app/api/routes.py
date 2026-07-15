import uuid
import logfire
from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.dependencies import verify_csrf
from app.services.semantic_cache import check_semantic_cache, save_to_semantic_cache
from app.services.guardrails import check_input_guardrails, check_output_guardrails
from app.services.rag_pipeline import run_advanced_rag
from app.services.evaluator import run_llm_as_judge
from app.database import log_interaction, update_feedback, get_admin_logs, get_admin_stats

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
        output_safe, fallback_response = await check_output_guardrails(bot_response, context_used)
        final_response = bot_response if output_safe else fallback_response
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

@router.get("/admin/api/stats")
async def admin_stats():
    stats = await get_admin_stats()
    return stats

@router.get("/admin/api/logs")
async def admin_logs(limit: int = 50, skip: int = 0):
    logs = await get_admin_logs(limit=limit, skip=skip)
    for log in logs:
        if "_id" in log:
            log["_id"] = str(log["_id"])
        if "timestamp" in log and log["timestamp"]:
            log["timestamp"] = log["timestamp"].isoformat()
        if "metrics" in log and log["metrics"] and "evaluated_at" in log["metrics"] and log["metrics"]["evaluated_at"]:
            log["metrics"]["evaluated_at"] = log["metrics"]["evaluated_at"].isoformat()
        if "feedback" in log and log["feedback"] and "updated_at" in log["feedback"] and log["feedback"]["updated_at"]:
            log["feedback"]["updated_at"] = log["feedback"]["updated_at"].isoformat()
    return logs
