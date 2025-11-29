# fetch_bins.py
import json
import re
import sys
from datetime import datetime
from time import sleep

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

POSTCODE = "LU4 9AZ"
ADDRESS_TEXT = "24 Compton Avenue"
BIN_URL = "https://myforms.luton.gov.uk/service/Find_my_bin_collection_date"
OUTPUT_FILE = "bins.json"

def parse_date_string(s):
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

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    full_text = "\n".join(lines)

    mapping = {
        "general": ["general", "black", "refuse", "household", "black bin", "refuse collection"],
        "recycling": ["recycling", "green", "green bin"],
        "glass": ["glass", "glass box", "glass bin", "black box"]
    }

    found = {"general": None, "recycling": None, "glass": None}

    date_rx = r"\b(?:\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})\b"

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
                        found[key] = parsed
                        break
            if found[key]:
                break

    return found

def run_lookup():
    print("[INFO] Starting Playwright...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()

        print(f"[INFO] Opening {BIN_URL}")
        page.goto(BIN_URL, timeout=90000)
        sleep(2)

        # Wait for iframe
        print("[INFO] Waiting for iframe to appear...")
        iframe_el = page.wait_for_selector("#fillform-frame-1", timeout=60000)
        frame = iframe_el.content_frame()
        if not frame:
            print("[ERROR] Iframe not found!")
            browser.close()
            return None
        print("[INFO] Iframe loaded successfully")

        # Fill postcode
        print(f"[INFO] Filling postcode: {POSTCODE}")
        frame.wait_for_selector("input[type='text']", timeout=45000)
        frame.fill("input[type='text']", POSTCODE)

        # Click 'Find address'
        print("[INFO] Clicking 'Find address' button...")
        frame.wait_for_selector("button:has-text('Find address')", timeout=45000)
        frame.click("button:has-text('Find address')")

        # Wait for address dropdown
        print("[INFO] Selecting address from dropdown...")
        frame.wait_for_selector("select", timeout=45000)
        frame.select_option("select", label=ADDRESS_TEXT)

        # Click final 'Find' button
        print("[INFO] Clicking final 'Find' button to get results...")
        frame.wait_for_selector("button:has-text('Find')", timeout=45000)
        frame.click("button:has-text('Find')")

        # Wait for table to appear
        print("[INFO] Waiting for results table...")
        frame.wait_for_selector("table", timeout=60000)

        html = frame.content()
        browser.close()
        print(f"[INFO] Captured HTML length: {len(html)}")
        return html

def main():
    print(f"[INFO] Running bin lookup for: {ADDRESS_TEXT} {POSTCODE}")
    html = run_lookup()
    if not html:
        print("[ERROR] Failed to capture HTML. Exiting.")
        sys.exit(1)

    found = extract_bins_from_html(html)
    print("[INFO] Extracted bin dates:")
    print(json.dumps(found, indent=2))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(found, f, indent=2)
    print(f"[INFO] Wrote {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
