import os
import pytest
from scripts.run_scrapling_crawlers import run_crawler_job

def test_run_crawler_job_directories(tmp_path):
    urls = [
        "https://vbpl.vn/tw/Pages/vbpq-todan.aspx?ItemID=130000",
        "https://vietlaw.quochoi.vn/pages/vbpq-toanvan.aspx?ItemID=999",
        "https://moj.gov.vn/qt/vbpl/pages/chi-tiet-van-ban.aspx?ItemID=888"
    ]
    custom_out_dir = str(tmp_path)
    summary = run_crawler_job(urls=urls, is_test_run=True, mock=True, custom_out_dir=custom_out_dir)
    assert summary["vbpl.vn"] >= 1
    assert summary["vietlaw.quochoi.vn"] >= 1
    assert summary["moj.gov.vn"] >= 1
