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
from app.database import (
    log_interaction, update_feedback, get_admin_logs, get_admin_stats, get_interaction,
    create_session, get_sessions, get_session_messages, delete_session, rename_session
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.post("/chat", response_class=HTMLResponse)
async def chat(
    request: Request,
    background_tasks: BackgroundTasks,
    message: str = Form(...),
    csrf_token: str = Form(...),
    session_id: str = Form(None),
    csrf_valid: str = Depends(verify_csrf)
):
    message = redact_pii(message)
    trace_id = str(uuid.uuid4())
    is_new_session = False
    
    if not session_id or session_id == "default":
        session_id = str(uuid.uuid4())
        words = message.split()
        title = " ".join(words[:5]) + ("..." if len(words) > 5 else "")
        await create_session(session_id, title)
        is_new_session = True
        
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
                cached=True,
                session_id=session_id
            )
            response = templates.TemplateResponse(
                request,
                "chat_message.html", 
                {"user_msg": message, "bot_msg": cached_response, "trace_id": trace_id, "cached": True, "session_id": session_id}
            )
            if is_new_session:
                response.headers["HX-Trigger"] = "load-sessions"
            return response
        
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
                rejection_reason="Jailbreak or off-topic input blocked by guardrails",
                session_id=session_id
            )
            response = templates.TemplateResponse(
                request,
                "chat_message.html",
                {"user_msg": message, "bot_msg": rejection_message, "trace_id": trace_id, "session_id": session_id}
            )
            if is_new_session:
                response.headers["HX-Trigger"] = "load-sessions"
            return response
            
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
            rejection_reason=rejection_reason,
            session_id=session_id
        )
        
        # Step 6: Save interaction to Semantic Cache
        background_tasks.add_task(save_to_semantic_cache, message, final_response)
        
        # Step 8: Trigger Background task: Evaluator
        background_tasks.add_task(run_llm_as_judge, message, context_used, final_response, trace_id)
        
        # Step 9: Return HTML partial response
        response = templates.TemplateResponse(
            request,
            "chat_message.html",
            {"user_msg": message, "bot_msg": final_response, "trace_id": trace_id, "session_id": session_id, "contexts": context_used}
        )
        if is_new_session:
            response.headers["HX-Trigger"] = "load-sessions"
        return response

@router.post("/api/feedback")
async def feedback(
    trace_id: str = Form(...),
    rating: str = Form(...)
):
    with logfire.span("Xử lý Feedback", trace_id=trace_id, rating=rating):
        await update_feedback(trace_id, rating)
        return {"status": "success", "message": "Thank you for your feedback!"}

@router.get("/sessions", response_class=HTMLResponse)
async def list_sessions(request: Request):
    sessions = await get_sessions()
    return templates.TemplateResponse(
        request,
        "sidebar_sessions.html",
        {"sessions": sessions}
    )

@router.post("/sessions", response_class=HTMLResponse)
async def new_session(request: Request):
    session_id = str(uuid.uuid4())
    await create_session(session_id, "Hội thoại mới")
    response = HTMLResponse(
        content=f'<div class="flex items-start space-x-3 max-w-[85%]"><div class="w-8 h-8 rounded-lg bg-slate-900 border border-slate-800 flex items-center justify-center font-semibold text-xs text-amber-400 flex-shrink-0"><i class="ph ph-robot text-base"></i></div><div class="bg-slate-900/60 rounded-2xl rounded-tl-none p-4 text-sm text-slate-300 border border-slate-900 leading-relaxed shadow-sm">Xin chào! Tôi là Trợ lý Pháp luật **VietLex**. Tôi có thể giúp gì cho bạn hôm nay?</div></div><input type="hidden" name="session_id" value="{session_id}" id="session-id-input" hx-swap-oob="true">'
    )
    response.headers["HX-Trigger"] = "load-sessions"
    return response

@router.get("/sessions/{session_id}", response_class=HTMLResponse)
async def get_session_history(request: Request, session_id: str):
    messages = await get_session_messages(session_id)
    return templates.TemplateResponse(
        request,
        "chat_history_messages.html",
        {"messages": messages, "session_id": session_id}
    )

@router.delete("/sessions/{session_id}")
async def remove_session(session_id: str):
    await delete_session(session_id)
    response = HTMLResponse(content="")
    response.headers["HX-Trigger"] = "load-sessions"
    return response

@router.post("/sessions/{session_id}/rename", response_class=HTMLResponse)
async def rename_sess(request: Request, session_id: str):
    new_title = request.headers.get("HX-Prompt")
    if new_title:
        await rename_session(session_id, new_title.strip())
    sessions = await get_sessions()
    return templates.TemplateResponse(
        request,
        "sidebar_sessions.html",
        {"sessions": sessions}
    )

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
