import logfire
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
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
    rejection_reason: Optional[str] = None
) -> Dict[str, Any]:
    database = get_db()
    collection = database.evaluation_logs
    
    document = {
        "_id": trace_id,
        "trace_id": trace_id,
        "timestamp": datetime.utcnow(),
        "user_query": user_query,
        "bot_response": bot_response,
        "contexts": contexts,
        "cached": cached,
        "safety_status": {
            "input_safe": input_safe,
            "output_safe": output_safe,
            "rejection_reason": rejection_reason
        },
        "metrics": {
            "faithfulness": None,
            "answer_relevance": None,
            "evaluated_at": None
        },
        "feedback": {
            "rating": None,
            "updated_at": None
        }
    }
    
    try:
        await collection.replace_one({"_id": trace_id}, document, upsert=True)
        logfire.info("Saved interaction to MongoDB: {trace_id}", trace_id=trace_id)
        return document
    except Exception as e:
        logfire.error("Failed to log interaction to MongoDB: {error}", error=str(e), trace_id=trace_id)
        return {}

async def update_evaluation(trace_id: str, faithfulness: float, answer_relevance: float) -> bool:
    database = get_db()
    collection = database.evaluation_logs
    
    update_data = {
        "metrics.faithfulness": faithfulness,
        "metrics.answer_relevance": answer_relevance,
        "metrics.evaluated_at": datetime.utcnow()
    }
    
    try:
        result = await collection.update_one(
            {"_id": trace_id},
            {"$set": update_data}
        )
        if result.modified_count > 0:
            logfire.info("Updated Ragas evaluation metrics for trace: {trace_id}", trace_id=trace_id)
            return True
        else:
            logfire.warning("No interaction found to update evaluation for trace: {trace_id}", trace_id=trace_id)
            return False
    except Exception as e:
        logfire.error("Failed to update evaluation in MongoDB: {error}", error=str(e), trace_id=trace_id)
        return False

async def update_feedback(trace_id: str, rating: str) -> bool:
    database = get_db()
    collection = database.evaluation_logs
    
    update_data = {
        "feedback.rating": rating,
        "feedback.updated_at": datetime.utcnow()
    }
    
    try:
        result = await collection.update_one(
            {"_id": trace_id},
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

async def get_admin_logs(limit: int = 50, skip: int = 0, search_query: Optional[str] = None) -> List[Dict[str, Any]]:
    database = get_db()
    collection = database.evaluation_logs
    
    query = {}
    if search_query:
        query = {
            "$or": [
                {"user_query": {"$regex": search_query, "$options": "i"}},
                {"bot_response": {"$regex": search_query, "$options": "i"}},
                {"trace_id": {"$regex": search_query, "$options": "i"}}
            ]
        }
        
    try:
        cursor = collection.find(query).sort("timestamp", -1).skip(skip).limit(limit)
        logs = await cursor.to_list(length=limit)
        return logs
    except Exception as e:
        logfire.error("Failed to fetch admin logs from MongoDB: {error}", error=str(e))
        return []

async def get_admin_stats() -> Dict[str, Any]:
    database = get_db()
    collection = database.evaluation_logs
    
    stats = {
        "total_queries": 0,
        "cache_hit_rate": 0.0,
        "avg_faithfulness": 0.0,
        "avg_relevance": 0.0,
        "positive_feedback_rate": 0.0
    }
    
    try:
        pipeline = [
            {
                "$facet": {
                    "total": [{"$count": "count"}],
                    "cached": [
                        {"$match": {"cached": True}},
                        {"$count": "count"}
                    ],
                    "avg_faithfulness": [
                        {"$match": {"metrics.faithfulness": {"$ne": None}}},
                        {"$group": {
                            "_id": None,
                            "avg": {"$avg": "$metrics.faithfulness"}
                        }}
                    ],
                    "avg_relevance": [
                        {"$match": {"metrics.answer_relevance": {"$ne": None}}},
                        {"$group": {
                            "_id": None,
                            "avg": {"$avg": "$metrics.answer_relevance"}
                        }}
                    ],
                    "total_feedback": [
                        {"$match": {"feedback.rating": {"$in": ["up", "down"]}}},
                        {"$count": "count"}
                    ],
                    "positive_feedback": [
                        {"$match": {"feedback.rating": "up"}},
                        {"$count": "count"}
                    ]
                }
            }
        ]
        
        cursor = collection.aggregate(pipeline)
        result = await cursor.to_list(length=1)
        
        if result:
            facet = result[0]
            total_count = facet["total"][0]["count"] if facet["total"] else 0
            stats["total_queries"] = total_count
            
            if total_count > 0:
                cached_count = facet["cached"][0]["count"] if facet["cached"] else 0
                stats["cache_hit_rate"] = round((cached_count / total_count) * 100, 2)
                
            if facet["avg_faithfulness"] and facet["avg_faithfulness"][0]["avg"] is not None:
                stats["avg_faithfulness"] = round(facet["avg_faithfulness"][0]["avg"], 2)
                
            if facet["avg_relevance"] and facet["avg_relevance"][0]["avg"] is not None:
                stats["avg_relevance"] = round(facet["avg_relevance"][0]["avg"], 2)
                
            total_fb = facet["total_feedback"][0]["count"] if facet["total_feedback"] else 0
            if total_fb > 0:
                pos_fb = facet["positive_feedback"][0]["count"] if facet["positive_feedback"] else 0
                stats["positive_feedback_rate"] = round((pos_fb / total_fb) * 100, 2)
                
    except Exception as e:
        logfire.error("Failed to calculate admin stats from MongoDB: {error}", error=str(e))
        
    return stats

async def get_interaction(trace_id: str) -> Optional[Dict[str, Any]]:
    database = get_db()
    collection = database.evaluation_logs
    try:
        log = await collection.find_one({"_id": trace_id})
        return log
    except Exception as e:
        logfire.error("Failed to fetch interaction from MongoDB: {error}", error=str(e), trace_id=trace_id)
        return None
