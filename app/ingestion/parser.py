import re
import logfire
from typing import List, Dict

@logfire.instrument("Phân tách văn bản luật")
def parse_legal_document(file_content: str) -> List[Dict]:
    # Regex parser to divide text into Chapter (Chương) -> Section (Mục) -> Article (Điều)
    logfire.info("Đang bắt đầu phân tách văn bản luật sử dụng Regex")
    
    chunks = []
    
    # Split by Chapter (Chương)
    # Match "Chương I", "Chương 1", "Chương Một", etc.
    chapter_matches = list(re.finditer(
        r'(?i)(?:^|\n)Chương\s+([A-Za-z0-9_À-ỹ]+)(.*?)(?=(?:\nChương\s+[A-Za-z0-9_À-ỹ]+)|$)', 
        file_content, 
        re.DOTALL
    ))
    
    if not chapter_matches:
        # Fallback if no chapters found, treat whole document as one chapter
        chapter_content_blocks = [(None, "Default", file_content)]
    else:
        chapter_content_blocks = [(m, m.group(1), m.group(2)) for m in chapter_matches]
        
    for ch_match_obj, ch_num, ch_content in chapter_content_blocks:
        # Split by Section (Mục)
        section_matches = list(re.finditer(
            r'(?i)(?:^|\n)Mục\s+([A-Za-z0-9_À-ỹ]+)(.*?)(?=(?:\nMục\s+[A-Za-z0-9_À-ỹ]+)|$)', 
            ch_content, 
            re.DOTALL
        ))
        
        if not section_matches:
            section_content_blocks = [(None, "Default", ch_content)]
        else:
            section_content_blocks = [(m, m.group(1), m.group(2)) for m in section_matches]
            
        for sec_match_obj, sec_num, sec_content in section_content_blocks:
            # Split by Article (Điều)
            article_matches = list(re.finditer(
                r'(?i)(?:^|\n)Điều\s+(\d+)\.?(.*?)(?=(?:\nĐiều\s+\d+\.?)|$)', 
                sec_content, 
                re.DOTALL
            ))
            
            for art_match in article_matches:
                art_num = art_match.group(1).strip()
                art_body = art_match.group(2).strip()
                
                chunks.append({
                    "chapter": ch_num,
                    "section": sec_num,
                    "article": art_num,
                    "content": f"Điều {art_num}. {art_body}"
                })
                
    logfire.info("Phân tách hoàn tất. Số lượng chunks: {count}", count=len(chunks))
    return chunks
