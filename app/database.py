import logfire
import re
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from app.config import get_settings

settings = get_settings()

client: Optional[AsyncIOMotorClient] = None
db = None

def get_db():
    global client, db
    if client is None:
        if not settings.MONGO_URL:
            raise ValueError("MONGO_URL is not configured in settings!")
        logfire.info("Connecting to MongoDB...")
        client = AsyncIOMotorClient(settings.MONGO_URL)
        # client.get_default_database() automatically retrieves the DB from the connection string
        # e.g., the part after '/' like 'Legal-RAG'
        db = client.get_default_database()
        logfire.info("Connected to MongoDB database: {db_name}", db_name=db.name)
    return db

async def init_db():
    try:
        database = get_db()
        collection = database.evaluation_logs
        
        # Create descending index on timestamp for fast query listing
        await collection.create_index([("timestamp", -1)])
        # Create index on metrics.evaluated_at for filtering/aggregation
        await collection.create_index([("metrics.evaluated_at", -1)])
        # Create index on feedback.rating
        await collection.create_index([("feedback.rating", 1)])
        # Create index on session_id
        await collection.create_index([("session_id", 1)])
        await collection.create_index(
            [("expires_at", 1)],
            expireAfterSeconds=0,
            name="evaluation_logs_retention_ttl",
        )
        
        # Initialize sessions collection index
        sessions_collection = database.chat_sessions
        await sessions_collection.create_index([("timestamp", -1)])
        await sessions_collection.create_index([("client_id", 1), ("timestamp", -1)])
        await sessions_collection.create_index(
            [("expires_at", 1)],
            expireAfterSeconds=0,
            name="chat_sessions_retention_ttl",
        )
        from app.account_database import init_account_db
        from app.research_database import init_research_db

        await init_account_db()
        await init_research_db()
        await database.demo_usage.create_index("expires_at", expireAfterSeconds=0)
        
        logfire.info("MongoDB database and indexes initialized successfully.")
    except Exception as e:
        logfire.error("Failed to initialize MongoDB database: {error}", error=str(e))
        raise e

async def log_interaction(
    trace_id: str, 
    user_query: str, 
    bot_response: str, 
    contexts: List[str], 
    cached: bool,
    input_safe: bool = True,
    output_safe: bool = True,
    rejection_reason: Optional[str] = None,
    session_id: str = "default",
    *,
    client_id: Optional[str] = None,
    request_status: str = "ok",
    latency: Optional[Dict[str, Any]] = None,
    observed_provider: Optional[str] = None,
    observed_model: Optional[str] = None,
    provider_usage: Optional[Dict[str, Any]] = None,
    ragas_mode: str = "off",
    ragas_status: str = "disabled",
    ragas_selected: bool = False,
    ragas_executed: bool = False,
    citation_count: Optional[int] = None,
    context_count: Optional[int] = None,
    no_evidence: bool = False,
    refusal_category: Optional[str] = None,
    technical_error: Optional[Dict[str, Any] | str] = None,
    user_id: Optional[str] = None,
    retrieval_trace: Optional[Dict[str, Any]] = None,
    request_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    database = get_db()
    collection = database.evaluation_logs

    ctx_count = context_count if context_count is not None else len(contexts)
    cit_count = citation_count if citation_count is not None else 0
    from app.services.provider_runtime import current_provider_calls
    from app.services.admin_observability import summarize_usage
    calls = current_provider_calls()
    llm_calls = [call for call in (calls or []) if call.get("call_kind", "llm") == "llm"]
    external_calls = [call for call in (calls or []) if call.get("call_kind", "llm") != "llm"]

    # Structured workspace failures must participate in the same admin error
    # counters as chat failures. Do not relabel refusals or insufficient evidence.
    if technical_error is None:
        for stage in ("full_document_review", "contract_review", "research_report",
                      "claim_verification", "selected_evidence", "comparison",
                      "obligation_matrix"):
            for kind in ("invalid_structured_response", "provider_error"):
                if request_status == f"{stage}_{kind}":
                    technical_error = {"stage": stage, "error_type": kind}

    document = {
        "_id": trace_id,
        "trace_id": trace_id,
        "session_id": session_id,
        "client_id": client_id,
        "user_id": user_id,
        "timestamp": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(
            days=settings.DATA_RETENTION_DAYS
        ),
        "user_query": user_query,
        "bot_response": bot_response,
        "contexts": contexts,
        "cached": cached,
        "retrieval_trace": retrieval_trace,
        "request_metadata": {key: value for key, value in (request_metadata or {}).items()
                             if key in {'method', 'path', 'nemo_requested', 'guardrail_engine'}},
        "safety_status": {
            "input_safe": input_safe,
            "output_safe": output_safe,
            "rejection_reason": rejection_reason
        },
        "metrics": {
            # Operational status & telemetry
            "request_status": request_status,
            "observed_provider": observed_provider or "unobserved",
            "observed_model": observed_model or "unobserved",
            "provider_usage": provider_usage or {},
            "latency": latency or {},
            "context_count": ctx_count,
            "citation_count": cit_count,
            "no_evidence": no_evidence,
            "refusal_category": refusal_category,
            "technical_error": technical_error,
            # Ragas proxy metadata & execution state
            "ragas_mode": ragas_mode,
            "ragas_status": ragas_status,
            "ragas_selected": ragas_selected,
            "ragas_executed": ragas_executed,
            "ragas_error": None,
            "ragas_proxy_faithfulness": None,
            "ragas_proxy_answer_relevance": None,
            "evaluated_at": None,
        },
        "feedback": {
            "rating": None,
            "updated_at": None
        }
    }

    if calls is not None:
        document['metrics']['llm_calls'] = llm_calls
        document['metrics']['external_calls'] = external_calls
        document['metrics']['token_usage'] = summarize_usage(llm_calls)
        document['metrics']['usage_scope'] = 'reported_llm_results_excludes_embedding_reranker_unreported_attempts'
    try:
        await collection.replace_one({"_id": trace_id}, document, upsert=True)
        logfire.info("Saved interaction to MongoDB: {trace_id}", trace_id=trace_id)
        return document
    except Exception as e:
        logfire.error("Failed to log interaction to MongoDB: {error}", error=str(e), trace_id=trace_id)
        return {}


async def update_interaction_request_status(trace_id: str, status: str) -> bool:
    """Correct a persisted request outcome without rewriting its evidence ledger."""
    try:
        result = await get_db().evaluation_logs.update_one(
            {"_id": str(trace_id)[:100]},
            {"$set": {"metrics.request_status": str(status)[:100]}},
        )
        return result.matched_count > 0
    except Exception as error:
        logfire.error(
            "Failed to update interaction status: {error}",
            error=str(error),
            trace_id=trace_id,
        )
        return False

async def update_evaluation(
    trace_id: str,
    faithfulness: Optional[float] = None,
    answer_relevance: Optional[float] = None,
    status: str = "ok",
    error: Optional[Dict[str, Any] | str] = None,
    executed: bool = True,
    provider_calls: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    database = get_db()
    collection = database.evaluation_logs

    update_data = {
        "metrics.ragas_proxy_faithfulness": faithfulness,
        "metrics.ragas_proxy_answer_relevance": answer_relevance,
        "metrics.ragas_status": status,
        "metrics.ragas_executed": executed,
        "metrics.ragas_error": error,
        "metrics.evaluated_at": datetime.utcnow(),
    }

    try:
        update = {'$set': update_data}
        if provider_calls is not None:
            from app.services.admin_observability import mongo_usage_summary
            update = [
                {'$set': {**{key: {'$literal': value} for key, value in update_data.items()},
                          'metrics.llm_calls': {'$concatArrays': [{'$cond': [{'$isArray': '$metrics.llm_calls'}, '$metrics.llm_calls', []]}, {'$literal': provider_calls}]}}},
                {'$set': {'metrics.token_usage': mongo_usage_summary()}},
            ]
        result = await collection.update_one(
            {"_id": trace_id},
            update
        )
        if result.modified_count > 0:
            logfire.info("Updated Ragas proxy evaluation metrics for trace: {trace_id}", trace_id=trace_id)
            return True
        else:
            logfire.warning("No interaction found to update evaluation for trace: {trace_id}", trace_id=trace_id)
            return False
    except Exception as e:
        logfire.error("Failed to update evaluation in MongoDB: {error}", error=str(e), trace_id=trace_id)
        return False



async def update_feedback(
    trace_id: str,
    rating: str,
    client_id: Optional[str] = None,
    *,
    user_id: Optional[str] = None,
) -> bool:
    database = get_db()
    collection = database.evaluation_logs
    
    update_data = {
        "feedback.rating": rating,
        "feedback.updated_at": datetime.utcnow()
    }
    
    try:
        query: Dict[str, Any] = {"_id": trace_id}
        if user_id is not None:
            query["user_id"] = user_id
        elif client_id is not None:
            query["client_id"] = client_id
        result = await collection.update_one(
            query,
            {"$set": update_data}
        )
        if result.modified_count > 0:
            logfire.info("Updated feedback '{rating}' for trace: {trace_id}", rating=rating, trace_id=trace_id)
            return True
        else:
            logfire.warning("No interaction found to update feedback for trace: {trace_id}", trace_id=trace_id)
            return False
    except Exception as e:
        logfire.error("Failed to update feedback in MongoDB: {error}", error=str(e), trace_id=trace_id)
        return False

async def get_admin_logs(
    limit: int = 50,
    skip: int = 0,
    search_query: Optional[str] = None,
    *,
    request_status: Optional[str] = None,
    provider: Optional[str] = None,
    cache_hit: Optional[bool] = None,
    model: Optional[str] = None,
    ragas_status: Optional[str] = None,
    feedback: Optional[str] = None,
    start_date=None,
    end_date=None,
    user_id=None,
    session_id=None,
) -> List[Dict[str, Any]]:
    from app.services.admin_observability import admin_query
    query = admin_query(search_query=search_query, request_status=request_status, provider=provider,
                        model=model, cache_hit=cache_hit, ragas_status=ragas_status, feedback=feedback,
                        start_date=start_date, end_date=end_date, user_id=user_id, session_id=session_id)
        
    try:
        collection = get_db().evaluation_logs
        bounded_limit = min(max(1, limit), 100)
        cursor = collection.find(query).sort("timestamp", -1).skip(max(0, skip)).limit(bounded_limit)
        logs = await cursor.to_list(length=bounded_limit)
        return logs
    except Exception as e:
        from app.services.admin_observability import AdminDataUnavailable
        logfire.error('Admin logs unavailable: {error_kind}', error_kind=type(e).__name__)
        raise AdminDataUnavailable(type(e).__name__) from e


async def get_admin_audit_logs(
    limit: int = 50, *, skip: int = 0, strict: bool = False
) -> List[Dict[str, Any]]:
    bounded_limit = min(max(1, limit), 100)
    try:
        cursor = get_db().admin_audit_logs.find({}).sort("timestamp", -1)
        if skip:
            cursor = cursor.skip(min(max(0, skip), 100000))
        cursor = cursor.limit(bounded_limit)
        return await cursor.to_list(length=bounded_limit)
    except Exception as error:
        logfire.error(
            "Failed to fetch administrative audit logs: {error_kind}",
            error_kind=type(error).__name__,
        )
        if strict:
            from app.services.admin_observability import AdminDataUnavailable

            raise AdminDataUnavailable("audit_unavailable") from None
        return []

async def get_admin_stats(*, filters=None) -> Dict[str, Any]:
    
    stats = {
        "total_queries": 0,
        "cache_hit_rate": 0.0,
        "avg_faithfulness": None,
        "avg_relevance": None,
        "avg_ragas_proxy_faithfulness": None,
        "avg_ragas_proxy_relevance": None,
        "positive_feedback_rate": 0.0,
        "technical_error_count": 0,
        "ragas_coverage_rate": 0.0,
        "status": "available",
        "token_usage": {}, "providers": [], "daily": [], "request_statuses": [], "latency": {},
        "judge_statuses": [], "error_stages": [], "llm_usage": [],
    }
    
    try:
        collection = get_db().evaluation_logs
        pipeline = [
            {
                "$facet": {
                    "total": [{"$count": "count"}],
                    "cached": [
                        {"$match": {"cached": True}},
                        {"$count": "count"}
                    ],
                    "avg_faithfulness": [
                        {"$match": {"$or": [{"metrics.ragas_proxy_faithfulness": {"$ne": None}}, {"metrics.faithfulness": {"$ne": None}}]}},
                        {"$group": {
                            "_id": None,
                            "avg": {"$avg": {"$ifNull": ["$metrics.ragas_proxy_faithfulness", "$metrics.faithfulness"]}},
                            "count": {"$sum": {'$cond': [{'$isNumber': {'$ifNull': ['$metrics.ragas_proxy_faithfulness', '$metrics.faithfulness']}}, 1, 0]}}
                        }}
                    ],
                    "avg_relevance": [
                        {"$match": {"$or": [{"metrics.ragas_proxy_answer_relevance": {"$ne": None}}, {"metrics.answer_relevance": {"$ne": None}}]}},
                        {"$group": {
                            "_id": None,
                            "avg": {"$avg": {"$ifNull": ["$metrics.ragas_proxy_answer_relevance", "$metrics.answer_relevance"]}},
                            "count": {"$sum": {'$cond': [{'$isNumber': {'$ifNull': ['$metrics.ragas_proxy_answer_relevance', '$metrics.answer_relevance']}}, 1, 0]}}
                        }}
                    ],
                    "total_feedback": [
                        {"$match": {"feedback.rating": {"$in": ["up", "down"]}}},
                        {"$count": "count"}
                    ],
                    "positive_feedback": [
                        {"$match": {"feedback.rating": "up"}},
                        {"$count": "count"}
                    ],
                    "technical_errors": [
                        {"$match": {'$or': [
                            {'metrics.request_status': {'$in': ['technical_error', 'retrieval_error', 'reranker_error', 'partial_retrieval_error']}},
                            {'metrics.technical_error': {'$ne': None}},
                        ]}},
                        {"$count": "count"}
                    ],
                    "ragas_executed": [
                        {"$match": {"metrics.ragas_executed": True}},
                        {"$count": "count"}
                    ]
                }
            }
        ]
        from app.services.admin_observability import usage_facets
        pipeline[0]['$facet'].update(usage_facets())
        if filters:
            from app.services.admin_observability import admin_query
            query = admin_query(**filters)
            if query:
                pipeline.insert(0, {'$match': query})
        
        cursor = collection.aggregate(pipeline)
        result = await cursor.to_list(length=1)
        
        if result:
            facet = result[0]
            for key in ('providers', 'daily', 'request_statuses', 'judge_statuses', 'error_stages', 'llm_usage', 'latency_buckets', 'user_usage'):
                stats[key] = facet.get(key, [])
            for key in ('no_context', 'no_citation', 'context_measured', 'citation_measured', 'total_feedback', 'positive_feedback', 'ragas_executed'):
                rows = facet.get(key, [])
                stats[key + '_count'] = rows[0]['count'] if rows else 0
            for key in ('avg_faithfulness', 'avg_relevance'):
                rows = facet.get(key, [])
                stats[key + '_count'] = rows[0].get('count', 0) if rows else 0
            for key in ('token_usage', 'latency'):
                rows = facet.get(key, [])
                stats[key] = rows[0] if rows else {}
            total_count = facet["total"][0]["count"] if facet["total"] else 0
            stats["total_queries"] = total_count
            
            if total_count > 0:
                cached_count = facet["cached"][0]["count"] if facet["cached"] else 0
                stats["cache_hit_rate"] = round((cached_count / total_count) * 100, 2)
                ragas_count = facet["ragas_executed"][0]["count"] if facet["ragas_executed"] else 0
                stats["ragas_coverage_rate"] = round((ragas_count / total_count) * 100, 2)

            stats["technical_error_count"] = (
                facet["technical_errors"][0]["count"]
                if facet["technical_errors"]
                else 0
            )
                
            if facet["avg_faithfulness"] and facet["avg_faithfulness"][0]["avg"] is not None:
                val = round(facet["avg_faithfulness"][0]["avg"], 2)
                stats["avg_faithfulness"] = val
                stats["avg_ragas_proxy_faithfulness"] = val
                
            if facet["avg_relevance"] and facet["avg_relevance"][0]["avg"] is not None:
                val = round(facet["avg_relevance"][0]["avg"], 2)
                stats["avg_relevance"] = val
                stats["avg_ragas_proxy_relevance"] = val
                
            total_fb = facet["total_feedback"][0]["count"] if facet["total_feedback"] else 0
            if total_fb > 0:
                pos_fb = facet["positive_feedback"][0]["count"] if facet["positive_feedback"] else 0
                stats["positive_feedback_rate"] = round((pos_fb / total_fb) * 100, 2)
                
    except Exception as e:
        logfire.error('Admin stats unavailable: {error_kind}', error_kind=type(e).__name__)
        stats['status'] = 'unavailable'
        stats['error_kind'] = type(e).__name__

        
    return stats


async def get_admin_inventory() -> dict:
    import asyncio
    now = datetime.utcnow()
    try:
        database = get_db()
        queries = {
            'users': (database.users, {}),
            'active_users': (database.users, {'status': 'active'}),
            'admins': (database.users, {'role': 'admin', 'status': 'active'}),
            'verified_users': (database.users, {'email_verified': True}),
            'active_sessions': (database.auth_sessions, {'expires_at': {'$gt': now}}),
            'conversations': (database.chat_sessions, {}),
            'workspaces': (database.research_workspaces, {}),
        }
        values = await asyncio.gather(*(collection.count_documents(query) for collection, query in queries.values()))
        return {'status': 'available', **dict(zip(queries, values))}
    except Exception as error:
        logfire.error('Admin inventory unavailable: {error_kind}', error_kind=type(error).__name__)
        return {'status': 'unavailable', 'error_kind': type(error).__name__}

async def get_interaction(trace_id: str, *, strict: bool = False) -> Optional[Dict[str, Any]]:
    try:
        collection = get_db().evaluation_logs
        log = await collection.find_one({"_id": trace_id})
        return log
    except Exception as e:
        logfire.error('Interaction unavailable: {error_kind}', error_kind=type(e).__name__, trace_id=trace_id)
        if strict:
            from app.services.admin_observability import AdminDataUnavailable
            raise AdminDataUnavailable(type(e).__name__) from e
        return None


async def get_owned_interaction(
    trace_id: str, client_id: str, *, user_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    database = get_db()
    try:
        owner = {"user_id": user_id} if user_id else {"client_id": client_id}
        return await database.evaluation_logs.find_one({"_id": trace_id, **owner})
    except Exception as e:
        logfire.error(
            "Failed to fetch owned interaction: {error}",
            error=str(e),
            trace_id=trace_id,
        )
        return None

async def create_session(
    session_id: str,
    title: str,
    client_id: Optional[str] = None,
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    database = get_db()
    collection = database.chat_sessions
    document = {
        "_id": session_id,
        "session_id": session_id,
        "title": title,
        "client_id": client_id,
        "user_id": user_id,
        "timestamp": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(
            days=settings.DATA_RETENTION_DAYS
        ),
    }
    try:
        await collection.replace_one({"_id": session_id}, document, upsert=True)
        return document
    except Exception as e:
        logfire.error("Failed to create session {session_id}: {error}", session_id=session_id, error=str(e))
        return {}

async def get_sessions(
    client_id: Optional[str] = None,
    search_query: Optional[str] = None,
    *,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    database = get_db()
    collection = database.chat_sessions
    try:
        query: Dict[str, Any] = {}
        if user_id is not None:
            query["user_id"] = user_id
        elif client_id is not None:
            query["client_id"] = client_id
        if search_query:
            query["title"] = {
                "$regex": re.escape(search_query[:100]),
                "$options": "i",
            }
        cursor = collection.find(query).sort("timestamp", -1)
        sessions = await cursor.to_list(length=100)
        return sessions
    except Exception as e:
        logfire.error("Failed to fetch sessions: {error}", error=str(e))
        return []

async def get_session_messages(
    session_id: str,
    client_id: Optional[str] = None,
    *,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    database = get_db()
    collection = database.evaluation_logs
    try:
        query: Dict[str, Any] = {"session_id": session_id}
        if user_id is not None:
            query["user_id"] = user_id
        elif client_id is not None:
            query["client_id"] = client_id
        cursor = collection.find(query).sort("timestamp", 1)
        messages = await cursor.to_list(length=200)
        return messages
    except Exception as e:
        logfire.error("Failed to fetch messages for session {session_id}: {error}", session_id=session_id, error=str(e))
        return []

async def delete_session(
    session_id: str,
    client_id: Optional[str] = None,
    *,
    user_id: Optional[str] = None,
) -> bool:
    database = get_db()
    sessions_coll = database.chat_sessions
    logs_coll = database.evaluation_logs
    try:
        session_query: Dict[str, Any] = {"_id": session_id}
        log_query: Dict[str, Any] = {"session_id": session_id}
        if user_id is not None:
            session_query["user_id"] = user_id
            log_query["user_id"] = user_id
        elif client_id is not None:
            session_query["client_id"] = client_id
            log_query["client_id"] = client_id
        await sessions_coll.delete_one(session_query)
        await logs_coll.delete_many(log_query)
        return True
    except Exception as e:
        logfire.error("Failed to delete session {session_id}: {error}", session_id=session_id, error=str(e))
        return False

async def rename_session(
    session_id: str,
    title: str,
    client_id: Optional[str] = None,
    *,
    user_id: Optional[str] = None,
) -> bool:
    database = get_db()
    collection = database.chat_sessions
    try:
        query: Dict[str, Any] = {"_id": session_id}
        if user_id is not None:
            query["user_id"] = user_id
        elif client_id is not None:
            query["client_id"] = client_id
        result = await collection.update_one(query, {"$set": {"title": title}})
        return result.modified_count > 0
    except Exception as e:
        logfire.error("Failed to rename session {session_id}: {error}", session_id=session_id, error=str(e))
        return False
