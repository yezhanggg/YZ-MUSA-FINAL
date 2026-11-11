"""Machine-read zoning corpus for Pennsylvania municipalities (pilot).

Steps: places (municipality list and survey sample), fetch (polite downloader),
extract (text with pages and section labels), chunk, embed, search,
draft_rules (batch extraction with quote checks) and evaluate (against the
hand-checked town files).

Everything large lives under ~/musa-drive/corpus/. Nothing here is a rule file.
A machine-read summary is a draft. It is never shown as verified.
"""
