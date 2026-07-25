import re
import logfire
from typing import List, Dict, Optional

@logfire.instrument("Phân tách văn bản luật với Context Enrichment")
def parse_legal_document_with_context(file_content: str, metadata: Optional[Dict] = None) -> List[Dict]:
    meta = metadata or {}
    title = meta.get("title", "").strip() or "Văn bản Luật"
    official_num = meta.get("official_number", "")
    if isinstance(official_num, list):
        official_num = ", ".join([str(x) for x in official_num if x])
    official_num = str(official_num).strip() or "Không có số hiệu"
    
    chunks = []
    
    chapter_matches = list(re.finditer(
        r'(?i)(?:^|\n)\s*Chương\s+([A-Za-z0-9_À-ỹ]+)(.*?)(?=(?:\n\s*Chương\s+[A-Za-z0-9_À-ỹ]+)|$)', 
        file_content, 
        re.DOTALL
    ))
    
    if not chapter_matches:
        chapter_content_blocks = [(None, "Chương chung", file_content)]
    else:
        chapter_content_blocks = [(m, f"Chương {m.group(1)}", m.group(2)) for m in chapter_matches]
        
    for _, ch_num, ch_content in chapter_content_blocks:
        section_matches = list(re.finditer(
            r'(?i)(?:^|\n)\s*Mục\s+([A-Za-z0-9_À-ỹ]+)(.*?)(?=(?:\n\s*Mục\s+[A-Za-z0-9_À-ỹ]+)|$)', 
            ch_content, 
            re.DOTALL
        ))
        
        if not section_matches:
            section_content_blocks = [(None, "Mục chung", ch_content)]
        else:
            section_content_blocks = [(m, f"Mục {m.group(1)}", m.group(2)) for m in section_matches]
            
        for _, sec_num, sec_content in section_content_blocks:
            article_matches = list(re.finditer(
                r'(?i)(?:^|\n)\s*Điều\s+(\d+)\.?(.*?)(?=(?:\n\s*Điều\s+\d+\.?)|$)', 
                sec_content, 
                re.DOTALL
            ))

            
            for art_match in article_matches:
                art_num = art_match.group(1).strip()
                art_body = art_match.group(2).strip()
                
                header_prefix = f"[Văn bản: {title} | Số hiệu: {official_num} | {ch_num} | {sec_num}]"
                full_chunk_text = f"{header_prefix}\nĐiều {art_num}. {art_body}"
                
                chunks.append({
                    "chapter": ch_num,
                    "section": sec_num,
                    "article": f"Điều {art_num}",
                    "content": full_chunk_text,
                    "raw_article_body": art_body,
                    "header_prefix": header_prefix
                })
                
    logfire.info("Phân tách hoàn tất. Số lượng chunks: {count}", count=len(chunks))
    return chunks

@logfire.instrument("Phân tách văn bản luật")
def parse_legal_document(file_content: str) -> List[Dict]:
    return parse_legal_document_with_context(file_content, metadata=None)

