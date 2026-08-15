from __future__ import annotations

import asyncio
import logfire
from typing import List

from app.config import get_settings

from app.evaluation.online_metrics import is_sampled_for_ragas

settings = get_settings()

# Module-level placeholders for lazy loading and test monkeypatching
ChatOpenAI = None
OpenAIEmbeddings = None
evaluate = None
Dataset = None
_faithfulness = None
_answer_relevancy = None


def _load_ragas_dependencies():
    global ChatOpenAI, OpenAIEmbeddings, evaluate, Dataset, _faithfulness, _answer_relevancy
    if ChatOpenAI is None or OpenAIEmbeddings is None:
        from langchain_openai import ChatOpenAI as _ChatOpenAI, OpenAIEmbeddings as _OpenAIEmbeddings
        if ChatOpenAI is None:
            ChatOpenAI = _ChatOpenAI
        if OpenAIEmbeddings is None:
            OpenAIEmbeddings = _OpenAIEmbeddings
    if evaluate is None or Dataset is None:
        from datasets import Dataset as _Dataset
        from ragas import evaluate as _evaluate
        from ragas.metrics import _faithfulness as _f, _answer_relevancy as _ar
        if Dataset is None:
            Dataset = _Dataset
        if evaluate is None:
            evaluate = _evaluate
        if _faithfulness is None:
            _faithfulness = _f
        if _answer_relevancy is None:
            _answer_relevancy = _ar


@logfire.instrument("Chạy đánh giá chất lượng Ragas proxy (LLM-as-a-judge)")
async def run_llm_as_judge(
    user_query: str,
    context: List[str],
    bot_response: str,
    trace_id: str
) -> None:
    mode = getattr(settings, "RAGAS_EVALUATION_MODE", "off")

    # 1. Mode check: if 'off', execute/instantiate zero models
    if mode == "off":
        return

    # 2. No-context requests skip evaluation
    if not context:
        logfire.warning(
            "Không có context để đánh giá. Bỏ qua Ragas evaluation.",
            trace_id=trace_id
        )
        return

    # 3. Mode check: if 'sample', check deterministic trace-ID sampling
    if mode == "sample":
        sample_rate = getattr(settings, "RAGAS_SAMPLE_RATE", 0.1)
        if not is_sampled_for_ragas(trace_id, sample_rate):
            return

    logfire.info(
        "Bắt đầu đánh giá Ragas proxy cho truy vấn. Trace ID: {trace_id}",
        trace_id=trace_id
    )

    try:
        # Load dependencies lazily only when Ragas is enabled and selected
        _load_ragas_dependencies()

        # Configure LLM and Embeddings for Ragas using OmniGate settings
        llm = ChatOpenAI(
            model="legal-core-model",
            api_key=settings.LITELLM_MASTER_KEY,
            base_url=settings.OMNIGATE_BASE_URL,
            default_headers={"drop_params": "true"}
        )
        embeddings = OpenAIEmbeddings(
            model="legal-embedding-model",
            api_key=settings.LITELLM_MASTER_KEY,
            base_url=settings.OMNIGATE_BASE_URL
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

        # Save evaluation results to MongoDB
        from app.database import update_evaluation
        await update_evaluation(
            trace_id,
            faithfulness=scores["faithfulness"],
            answer_relevance=scores["answer_relevance"],
            status="ok",
            error=None,
            executed=True,
        )

        logfire.info(
            "Đánh giá Ragas proxy hoàn thành",
            trace_id=trace_id,
            metrics=scores
        )

    except Exception as e:
        logfire.error("Lỗi khi chạy Ragas evaluator: {error}", error=str(e), trace_id=trace_id)
        try:
            from app.database import update_evaluation
            safe_error = {
                "error_type": e.__class__.__name__,
                "message": str(e)[:200],
            }
            await update_evaluation(
                trace_id,
                faithfulness=None,
                answer_relevance=None,
                status="error",
                error=safe_error,
                executed=True,
            )
        except Exception as db_err:
            logfire.error("Lỗi khi ghi nhận trạng thái lỗi Ragas vào DB: {error}", error=str(db_err), trace_id=trace_id)
