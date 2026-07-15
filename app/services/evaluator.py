import logfire
import asyncio
from typing import List
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import _faithfulness, _answer_relevancy
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from app.config import get_settings

settings = get_settings()

@logfire.instrument("Chạy đánh giá chất lượng (LLM-as-a-judge)")
async def run_llm_as_judge(user_query: str, context: List[str], bot_response: str, trace_id: str):
    logfire.info(
        "Bắt đầu đánh giá Ragas cho truy vấn. Trace ID: {trace_id}", 
        trace_id=trace_id
    )
    
    if not context:
        logfire.warning("Không có context để đánh giá. Bỏ qua Ragas evaluation.", trace_id=trace_id)
        return
        
    try:
        # Configure LLM and Embeddings for Ragas using OmniGate settings
        llm = ChatOpenAI(
            model="legal-core-model",
            openai_api_key=settings.LITELLM_MASTER_KEY,
            openai_api_base=settings.OMNIGATE_BASE_URL
        )
        embeddings = OpenAIEmbeddings(
            model="legal-embedding-model",
            openai_api_key=settings.LITELLM_MASTER_KEY,
            openai_api_base=settings.OMNIGATE_BASE_URL
        )
        
        # Format dataset for Ragas
        data = {
            "question": [user_query],
            "contexts": [context],
            "answer": [bot_response]
        }
        dataset = Dataset.from_dict(data)
        
        # Run evaluation asynchronously in a separate thread to prevent blocking the event loop
        result = await asyncio.to_thread(
            evaluate,
            dataset=dataset,
            metrics=[_faithfulness, _answer_relevancy],
            llm=llm,
            embeddings=embeddings,
            raise_exceptions=True
        )
        
        scores = {
            "faithfulness": float(result.get("faithfulness", 0.0)),
            "answer_relevance": float(result.get("answer_relevancy", result.get("answer_relevance", 0.0)))
        }
        
        logfire.info(
            "Đánh giá Ragas hoàn thành",
            trace_id=trace_id,
            metrics=scores
        )
        
    except Exception as e:
        logfire.error("Lỗi khi chạy Ragas evaluator: {error}", error=str(e), trace_id=trace_id)
