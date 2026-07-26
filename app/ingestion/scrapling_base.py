import os
import logging
import requests
from abc import ABC, abstractmethod
from typing import Optional
from scrapling import Fetcher
from app.ingestion.schemas import LegalDocumentSchema

# Suppress third-party noisy loggers to prevent terminal freezing
for logger_name in ["scrapling", "patchright", "playwright", "urllib3", "asyncio", "WDM"]:
    logging.getLogger(logger_name).setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

BASE_RAW_DIR = os.path.join("data", "scrapling_raw")

def get_output_dir_for_source(source: str) -> str:
    folder_map = {
        "vbpl.vn": "vbpl",
        "vietlaw.quochoi.vn": "vietlaw",
        "moj.gov.vn": "moj"
    }
    subfolder = folder_map.get(source, "others")
    path = os.path.join(BASE_RAW_DIR, subfolder)
    os.makedirs(path, exist_ok=True)
    return path

class BaseLegalCrawler(ABC):
    def __init__(self, use_stealth: bool = False, timeout: int = 15):
        self.use_stealth = use_stealth
        self.timeout = timeout
        self.fetcher = Fetcher()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"
        })

    def fetch_page(self, url: str):
        try:
            res = self.session.get(url, timeout=self.timeout, verify=False)
            if res.status_code == 200 and res.text:
                return res
        except Exception as e:
            logger.debug(f"Requests failed for {url}: {e}, falling back to Scrapling")
        
        try:
            res = self.fetcher.get(url, timeout=self.timeout * 1000)
            return res
        except Exception:
            return None


    @abstractmethod
    def parse_document(self, url: str) -> Optional[LegalDocumentSchema]:
        pass
