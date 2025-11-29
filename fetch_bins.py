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

        # Wait a bit for JS to load
        sleep(1.2)

        # Try to find a postcode input - many govService pages use an input with placeholder 'Enter postcode'
        # We'll attempt multiple selectors
        postcode_selectors = [
            "input[name='Postcode']",
            "input[id*='postcode']",
            "input[placeholder*='postcode']",
            "input[type='text']"
        ]

        found_input = None
        for sel in postcode_selectors:
            try:
                if page.query_selector(sel):
                    found_input = sel
                    break
            except Exception:
                continue

        if not found_input:
            print("[WARN] Could not find postcode input by common selectors. Attempting to type into first visible text input.")
            try:
                page.fill("input[type='text']", POSTCODE, timeout=5000)
            except Exception as e:
                print("[ERROR] Could not fill any text input:", e)
                browser.close()
                return None

        else:
            print(f"[DEBUG] Found postcode selector: {found_input}. Filling with {POSTCODE}")
            try:
                page.fill(found_input, POSTCODE, timeout=7000)
            except Exception as e:
                print("[WARN] fill() failed for selector, trying generic text input. Error:", e)
                page.fill("input[type='text']", POSTCODE, timeout=7000)

        # Click a button that looks like 'Find' or 'Search' or 'Lookup'
        # Try sensible selectors
        button_selectors = [
            "button:has-text('Find')",
            "button:has-text('Find address')",
            "button:has-text('Search')",
            "button:has-text('Lookup')",
            "input[type='submit']"
        ]
        clicked = False
        for bsel in button_selectors:
            try:
                btn = page.query_selector(bsel)
                if btn:
                    print(f"[DEBUG] Clicking button selector: {bsel}")
                    btn.click()
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            print("[WARN] Could not find an obvious search button — attempting Enter key press in the postcode field")
            try:
                page.keyboard.press("Enter")
            except Exception as e:
                print("[ERROR] Could not press Enter:", e)

        # Wait for results / address dropdown
        print("[DEBUG] Waiting for address results to appear...")
        try:
            page.wait_for_timeout(2500)
            # attempt to select the correct address - search for the address text
            # Many govService pages render a list where each item contains the address string
            addr_elements = page.query_selector_all(f"text=\"{ADDRESS_TEXT}\"")
            if not addr_elements:
                # try case-insensitive partial match using contains
                print("[DEBUG] exact address text not found - searching for partial text")
                addr_elements = page.query_selector_all(f"text=Compton Avenue")
            if addr_elements:
                print(f"[DEBUG] Found {len(addr_elements)} address entries that match. Clicking the first.")
                addr_elements[0].click()
            else:
                print("[WARN] Address element not found automatically. Trying to pick first address in any address list.")
                # try clicking the first list item that looks like an address
                candidates = page.query_selector_all("li, .result, .address, select option")
                if candidates:
                    # try clicking the first candidate that contains a number or street
                    clicked_any = False
                    for c in candidates:
                        txt = c.inner_text().strip()
                        if "Compton" in txt or re.search(r"\b24\b", txt):
                            print(f"[DEBUG] clicking candidate with text: {txt[:80]}")
                            try:
                                c.click()
                                clicked_any = True
                                break
                            except Exception:
                                continue
                    if not clicked_any and candidates:
                        print("[DEBUG] clicking the first generic candidate")
                        try:
                            candidates[0].click()
                        except Exception as e:
                            print("[WARN] clicking candidate failed:", e)
                else:
                    print("[ERROR] No candidate addresses found on page. Will capture HTML for debugging.")

        except Exception as e:
            print("[WARN] Waiting for address results timed out or errored:", e)

        # give the page a moment to load the final schedule after address selection
        print("[DEBUG] Sleeping briefly to allow schedule to load...")
        page.wait_for_timeout(2000)

        html = page.content()
        browser.close()
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
