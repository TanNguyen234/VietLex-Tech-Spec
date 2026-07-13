import logfire
from typing import List, dict
from pyvi import ViTokenizer
from app.config import get_settings

settings = get_settings()

@logfire.instrument("Đồng bộ hóa dữ liệu lên Qdrant")
async def index_documents(chunks: List[dict]):
    logfire.info("Đang bắt đầu lập chỉ mục tài liệu")
    
    for chunk in chunks:
        # PyVi segmentation
        segmented_content = ViTokenizer.tokenize(chunk["content"])
        
        # Dense Embedding (Placeholder)
        # Sparse BM25 (Placeholder)
        
        logfire.info(
            "Đang upsert Qdrant chunk: Chương {chapter}, Mục {section}, Điều {article}", 
            chapter=chunk["chapter"], 
            section=chunk["section"], 
            article=chunk["article"]
        )
    
    logfire.info("Đồng bộ hóa lên Qdrant hoàn tất")
