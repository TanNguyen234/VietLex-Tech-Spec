import re
import logfire
from typing import List, dict

@logfire.instrument("Phân tách văn bản luật")
def parse_legal_document(file_content: str) -> List[dict]:
    # Regex parser skeleton to divide text into Chapter (Chương) -> Section (Mục) -> Article (Điều)
    logfire.info("Đang bắt đầu phân tách văn bản luật sử dụng Regex")
    
    chunks = []
    # Simplified regex-based separation placeholder
    chapters = re.split(r'(?i)Chương\s+\w+', file_content)
    
    for ch_idx, chapter in enumerate(chapters[1:], start=1):
        sections = re.split(r'(?i)Mục\s+\d+', chapter)
        for sec_idx, section in enumerate(sections[1:], start=1):
            articles = re.split(r'(?i)Điều\s+\d+', section)
            for art_idx, article in enumerate(articles[1:], start=1):
                chunks.append({
                    "chapter": ch_idx,
                    "section": sec_idx,
                    "article": art_idx,
                    "content": article.strip()
                })
                
    return chunks
