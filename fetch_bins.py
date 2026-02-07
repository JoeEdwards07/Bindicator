import os
import json
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build


# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------

CALENDAR_ID = "9e78b93597b2a5dc4dc1d103f229b71930612888caa0e4901d2c38a08ffcb6eb@group.calendar.google.com"

OUTPUT_FILE = "Instructions.json"

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


# Keywords → Output names
KEYWORDS = {
    "Green": ["Green bin collection"],
    "Black": ["Black bin collection"],
    "Box": ["Black box collection"]
}


# -------------------------------------------------------
# AUTH
# -------------------------------------------------------


def get_credentials():
    creds_info = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    return service_account.Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/calendar.readonly"])


# def get_credentials():
#     # For GitHub Actions
#     if "GOOGLE_CREDENTIALS" in os.environ:
#         creds_info = json.loads(os.environ["GOOGLE_CREDENTIALS"])
#         return service_account.Credentials.from_service_account_info(
#             creds_info, scopes=SCOPES
#         )

#     # For local testing
#     return service_account.Credentials.from_service_account_file(
#         "service_account.json", scopes=SCOPES
#     )


# -------------------------------------------------------
# FETCH
# -------------------------------------------------------

def get_events(service, weeks=12):

    now = datetime.utcnow().isoformat() + "Z"
    future = (datetime.utcnow() + timedelta(weeks=weeks)).isoformat() + "Z"

    print("Fetching events from", now, "to", future)

    events = []

    page_token = None

    while True:
        result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now,
            timeMax=future,
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token,
        ).execute()

        events.extend(result.get("items", []))

        page_token = result.get("nextPageToken")

        if not page_token:
            break

    return events



# -------------------------------------------------------
# PARSE
# -------------------------------------------------------

def parse_events(events):

    grouped = {}  # { "2026-03-04": {"Green", "Box"} }

    for event in events:

        title = event.get("summary", "").lower()

        start = (
            event.get("start", {}).get("date")
            or event.get("start", {}).get("dateTime", "")[:10]
        )

        if not start:
            continue

        found_keywords = []

        for name, words in KEYWORDS.items():
            if any(word.lower() in title for word in words):
                found_keywords.append(name)

        if not found_keywords:
            continue

        # Create date entry if missing
        if start not in grouped:
            grouped[start] = set()

        # Add keywords (set avoids duplicates)
        for k in found_keywords:
            grouped[start].add(k)

    # Convert to final list
    parsed = []

    for date in sorted(grouped.keys()):
        parsed.append({
            "date": date,
            "keywords": sorted(grouped[date])
        })

    return parsed



# -------------------------------------------------------
# MAIN
# -------------------------------------------------------

def main():

    print("[INFO] Authenticating...")
    creds = get_credentials()

    service = build("calendar", "v3", credentials=creds)

    print("[INFO] Fetching events...")
    events = get_events(service)

    print(f"[INFO] Found {len(events)} events")

    parsed = parse_events(events)

    parsed.sort(key=lambda x: x["date"])

    output = {
        "events": parsed
    }

    print("[INFO] Writing Instructions.json")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print("[OK] Done!")


if __name__ == "__main__":
    main()
