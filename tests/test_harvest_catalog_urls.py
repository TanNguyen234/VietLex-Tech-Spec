# tests/test_harvest_catalog_urls.py
import os
import json
from scripts.harvest_legal_catalog_urls import parse_sitemap_index_xml

def test_parse_sitemap_index_xml():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://vbpl.vn/sitemap/1.xml</loc></sitemap>
    </sitemapindex>"""
    locs = parse_sitemap_index_xml(xml_content)
    assert len(locs) == 1
    assert locs[0] == "https://vbpl.vn/sitemap/1.xml"
