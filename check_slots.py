"""
H-1B slot monitor for checkvisaslots.com
Checks the H-1B (Regular) table and sends a phone notification (via ntfy)
whenever a location reports a new sighting.

Settings (environment variables):
  NTFY_TOPIC  - your private ntfy topic name (required for notifications)
  LOCATIONS   - optional, comma-separated filter, e.g. "HYDERABAD VAC,CHENNAI"
  SLOTS_URL   - optional, override the page URL

Run once:            python check_slots.py
Run every 10 min:    python check_slots.py --loop 10
"""
import json
import os
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = os.getenv("SLOTS_URL", "https://checkvisaslots.com/latest-us-visa-availability/h-1b-regular/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
LOCATIONS = [s.strip().upper() for s in os.getenv("LOCATIONS", "").split(",") if s.strip()]
STATE_FILE = Path(os.getenv("STATE_FILE", Path(__file__).with_name("state.json")))
HEADERS = {"User-Agent": "Mozilla/5.0 (personal H-1B slot monitor)"}


def fetch_rows():
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for table in soup.find_all("table"):
        cols = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        if not any("location" in c for c in cols):
            continue
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) == len(cols):
                rows.append(dict(zip(cols, cells)))
        return rows
    raise RuntimeError("Slot table not found - the page layout may have changed.")


def col(row, keyword):
    return next((v for k, v in row.items() if keyword in k), "")


def describe(row):
    loc = col(row, "location")
    earliest = col(row, "earliest")
    slots = col(row, "slots on")
    total = col(row, "total dates")
    if slots and slots.upper() != "N/A":
        return f"{loc}: {slots} slot(s) on {earliest} ({total} date(s) open)"
    return f"{loc}: earliest {earliest} ({total} date(s) open)"


def notify(title, message):
    print(f"[{title}]\n{message}")
    if not NTFY_TOPIC:
        print("(NTFY_TOPIC not set - printed only)")
        return
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={"Title": title, "Priority": "high", "Tags": "rotating_light", "Click": URL},
        timeout=30,
    )


def check_once():
    first_run = not STATE_FILE.exists()
    state = {} if first_run else json.loads(STATE_FILE.read_text())

    alerts = []
    watched = 0
    for row in fetch_rows():
        loc = col(row, "location").upper()
        if not loc or (LOCATIONS and loc not in LOCATIONS):
            continue
        watched += 1
        seen = col(row, "last seen")
        if not first_run and state.get(loc) != seen:
            alerts.append(describe(row))
        state[loc] = seen

    STATE_FILE.write_text(json.dumps(state, indent=2))

    if first_run:
        notify("H-1B monitor started", f"Watching {watched} location(s). You'll be pinged when new slots are reported.")
    elif alerts:
        notify("H-1B slots open", "\n".join(alerts))
    else:
        print("No new openings.")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--loop":
        minutes = float(sys.argv[2])
        while True:
            try:
                check_once()
            except Exception as e:
                print(f"Check failed: {e}")
            time.sleep(minutes * 60)
    else:
        check_once()
