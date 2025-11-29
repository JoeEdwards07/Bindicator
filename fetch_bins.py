import os
import json
from datetime import datetime, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build

# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------
# Name of your hidden Google Calendar
CALENDAR_ID = "your_calendar_id@group.calendar.google.com"  # replace with your hidden Bins calendar ID
# Path to your service account JSON key stored as GitHub secret or local file
SERVICE_ACCOUNT_FILE = "service_account.json"  # replace with actual path if testing locally
OUTPUT_FILE = "bins.json"

# Bin type keywords
BIN_KEYWORDS = {
    "general": ["general", "black", "refuse", "household"],
    "recycling": ["recycling", "green", "green bin"],
    "glass": ["glass", "glass box", "black box"]
}

# -------------------------------------------------------
# AUTHENTICATION
# -------------------------------------------------------
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=["https://www.googleapis.com/auth/calendar.readonly"]
)

service = build("calendar", "v3", credentials=credentials)

# -------------------------------------------------------
# FETCH EVENTS
# -------------------------------------------------------
def get_upcoming_events(max_results=50):
    now = datetime.utcnow().isoformat() + "Z"  # 'Z' indicates UTC time
    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=now,
        maxResults=max_results,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])
    return events

# -------------------------------------------------------
# PARSE EVENTS FOR EACH BIN TYPE
# -------------------------------------------------------
def extract_next_bins(events):
    next_bins = {k: None for k in BIN_KEYWORDS.keys()}

    for event in events:
        title = event.get("summary", "").lower()
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        if not start:
            continue

        # Convert date string to ISO format
        if "T" not in start:
            # all-day event
            start_iso = f"{start}T07:00:00"  # assume collection at 7am if all-day
        else:
            start_iso = start

        # Check which bin type it matches
        for bin_type, keywords in BIN_KEYWORDS.items():
            if any(keyword in title for keyword in keywords):
                # Only keep first upcoming event
                if next_bins[bin_type] is None:
                    next_bins[bin_type] = start_iso
                    print(f"[DEBUG] Found next {bin_type}: {start_iso}")
    return next_bins

# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
def main():
    print("[INFO] Fetching events from Google Calendar...")
    events = get_upcoming_events()
    if not events:
        print("[WARN] No upcoming events found!")
    else:
        print(f"[INFO] Found {len(events)} upcoming events.")

    next_bins = extract_next_bins(events)

    print("[INFO] Writing bins.json:")
    print(json.dumps(next_bins, indent=2))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(next_bins, f, indent=2)

    print(f"[OK] {OUTPUT_FILE} updated.")

if __name__ == "__main__":
    main()
