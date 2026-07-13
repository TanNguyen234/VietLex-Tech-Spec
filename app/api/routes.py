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
            return templates.TemplateResponse(
                "chat_message.html", 
                {"request": request, "user_msg": message, "bot_msg": cached_response, "trace_id": trace_id, "cached": True}
            )
        
        span.set_attribute("cache_hit", False)
        
        # Step 3: Apply NeMo Guardrails (Input Check)
        input_safe, rejection_message = await check_input_guardrails(message)
        if not input_safe:
            span.set_attribute("guardrails_blocked_input", True)
            return templates.TemplateResponse(
                "chat_message.html",
                {"request": request, "user_msg": message, "bot_msg": rejection_message, "trace_id": trace_id}
            )
            
        # Step 4: Run Advanced Retrieval Pipeline (RAG)
        bot_response, context_used = await run_advanced_rag(message)
        
        # Step 5: Apply NeMo Guardrails (Output Check)
        output_safe, fallback_response = await check_output_guardrails(bot_response, context_used)
        final_response = bot_response if output_safe else fallback_response
        
        # Step 6: Save interaction to Semantic Cache
        background_tasks.add_task(save_to_semantic_cache, message, final_response)
        
        # Step 8: Trigger Background task: Evaluator
        background_tasks.add_task(run_llm_as_judge, message, context_used, final_response, trace_id)
        
        # Step 9: Return HTML partial response
        return templates.TemplateResponse(
            "chat_message.html",
            {"request": request, "user_msg": message, "bot_msg": final_response, "trace_id": trace_id}
        )

@router.post("/api/feedback")
async def feedback(
    trace_id: str = Form(...),
    rating: str = Form(...)
):
    # Feedback processing placeholder
    with logfire.span("Xử lý Feedback", trace_id=trace_id, rating=rating):
        return {"status": "success", "message": "Thank you for your feedback!"}
