# fetch_bins.py
# Requires: playwright, beautifulsoup4
# Usage: python fetch_bins.py
# Outputs: bins.json in the same folder

import json
import re
import sys
from datetime import datetime
from time import sleep

from bs4 import BeautifulSoup

# Playwright sync API
from playwright.sync_api import sync_playwright

POSTCODE = "LU4 9AZ"
ADDRESS_TEXT = "24 Compton Avenue"   # the visible address label to click

BIN_URL = "https://myforms.luton.gov.uk/service/Find_my_bin_collection_date"
OUTPUT_FILE = "bins.json"

# helper: parse a date-like string into yyyy-mm-dd
def parse_date_string(s):
    # Try common patterns e.g. "14 February 2025", "14/02/2025", "14 Feb 2025"
    s = s.strip()
    patterns = [
        ("%d %B %Y", r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b"),
        ("%d %b %Y", r"\b\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\b"),
        ("%d/%m/%Y", r"\b\d{1,2}/\d{1,2}/\d{4}\b"),
        ("%d-%m-%Y", r"\b\d{1,2}-\d{1,2}-\d{4}\b")
    ]
    for fmt, rx in patterns:
        m = re.search(rx, s)
        if m:
            try:
                dt = datetime.strptime(m.group(0), fmt)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                continue
    return None

def extract_bins_from_html(html):
    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text(separator="\n", strip=True)
    # Debug: output some of the page text
    print("----- page text snippet (first 500 chars) -----")
    print(text[:500])
    print("------------------------------------------------")

    # We'll search for lines that mention bin type and a date nearby.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # join back so we can search context
    full_text = "\n".join(lines)

    # bin keys we want and aliases to match
    mapping = {
        "general": ["general", "black", "refuse", "household", "black bin", "refuse collection"],
        "recycling": ["recycling", "green", "green bin"],
        "glass": ["glass", "glass box", "glass bin", "black box"]  # Luton uses black box for glass
    }

    # store first found date for each
    found = {"general": None, "recycling": None, "glass": None}

    # Candidate date regex - look for day month year and also dd/mm/yyyy
    date_rx = r"\b(?:\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})\b"

    # Strategy: for each bin alias, find occurrences in text and look +/- 120 characters for a date.
    for key, aliases in mapping.items():
        for alias in aliases:
            for m in re.finditer(re.escape(alias), full_text, flags=re.IGNORECASE):
                span_start = max(0, m.start()-120)
                span_end = min(len(full_text), m.end()+120)
                window = full_text[span_start:span_end]
                date_match = re.search(date_rx, window, flags=re.IGNORECASE)
                if date_match:
                    parsed = parse_date_string(date_match.group(0))
                    if parsed:
                        print(f"[DEBUG] Found '{alias}' -> '{date_match.group(0)}' -> {parsed}")
                        found[key] = parsed
                        break
                # fallback: sometimes the date is on the next line(s) — try the next 3 lines
                # Build small neighbor area:
                lines_window = full_text[max(0, full_text.rfind("\n", 0, m.start())-200):min(len(full_text), full_text.find("\n", m.end())+200)]
                md = re.search(date_rx, lines_window, flags=re.IGNORECASE)
                if md:
                    parsed = parse_date_string(md.group(0))
                    if parsed:
                        print(f"[DEBUG] (fallback) Found '{alias}' -> '{md.group(0)}' -> {parsed}")
                        found[key] = parsed
                        break
            if found[key]:
                break

    # Final safety: try to find any date lines mentioning "next collection" etc
    if not any(found.values()):
        # search for lines containing 'next collection' or 'next collections' with a date
        for m in re.finditer(r"(next collection|next collections|Next collection|Next collections|collection date|collection dates).{0,120}", full_text, flags=re.IGNORECASE):
            md = re.search(date_rx, m.group(0))
            if md:
                parsed = parse_date_string(md.group(0))
                if parsed:
                    print(f"[DEBUG] Found generic next-collection -> {md.group(0)} -> {parsed}")
                    # put it as a fallback for general
                    found["general"] = found["general"] or parsed

    return found

def run_lookup():
    print("Starting Playwright...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        print(f"Opening {BIN_URL}")
        page.goto(BIN_URL, timeout=60000)

        # Step 1: wait for the first visible input (postcode field)
        print("[DEBUG] Waiting for postcode input...")
        postcode_input = page.wait_for_selector("input[type='text']", timeout=30000)
        postcode_input.fill(POSTCODE)
        print(f"[DEBUG] Filled postcode: {POSTCODE}")

        # Step 2: Click 'Find address'
        print("[DEBUG] Clicking 'Find address' button...")
        find_address_btn = page.wait_for_selector("button:has-text('Find address')", timeout=15000)
        find_address_btn.click()

        # Step 3: Wait for address dropdown
        print("[DEBUG] Waiting for address dropdown...")
        select_el = page.wait_for_selector("select", timeout=30000)
        select_el.select_option(label=ADDRESS_TEXT)
        print(f"[DEBUG] Selected address: {ADDRESS_TEXT}")

        # Step 4: Click 'Find' to fetch results
        print("[DEBUG] Clicking 'Find' button to get results...")
        find_btn2 = page.wait_for_selector("button:has-text('Find')", timeout=15000)
        find_btn2.click()

        # Step 5: Wait for results table
        print("[DEBUG] Waiting for results table...")
        page.wait_for_selector("table", timeout=30000)

        # Capture HTML
        html = page.content()
        browser.close()
        print("[DEBUG] Captured HTML length:", len(html))
        return html



def main():
    print("Running bin lookup for:", ADDRESS_TEXT, POSTCODE)
    html = run_lookup()
    if not html:
        print("[ERROR] No HTML captured. Exiting with error.")
        sys.exit(1)

    print("[DEBUG] Captured HTML length:", len(html))
    found = extract_bins_from_html(html)

    print("[INFO] Extracted results (may include null values):")
    print(json.dumps(found, indent=2))

    # write to bins.json
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(found, f, indent=2)
    print(f"[OK] Wrote {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
