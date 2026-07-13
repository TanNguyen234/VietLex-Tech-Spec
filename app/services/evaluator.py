import logfire
from typing import List

@logfire.instrument("Chạy đánh giá chất lượng (LLM-as-a-judge)")
async def run_llm_as_judge(user_query: str, context: List[str], bot_response: str, trace_id: str):
    # Running Ragas evaluation in background
    # Faithfulness, Answer Relevance, Context Recall
    logfire.info(
        "Bắt đầu đánh giá Ragas cho truy vấn. Trace ID: {trace_id}", 
        trace_id=trace_id
    )
    
    # Mocking evaluation process
    logfire.info("Ragas Scores: Faithfulness=0.98, Answer Relevance=0.95, Context Recall=0.92")
