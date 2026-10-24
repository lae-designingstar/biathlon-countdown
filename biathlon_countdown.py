
import os
import re
import json
import requests

from datetime import datetime, time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

CALENDAR_URL = "https://www.biathlonworld.com/calendar"
TIMEZONE = ZoneInfo("Europe/Helsinki")
STATE_FILE = Path("countdown_state.json")

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

def parse_start_date(text):
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("–", "—").replace("-", "—")

    # Example: 26—29 Nov 2026
    match = re.search(
        r"(\d{1,2})\s*—\s*\d{1,2}\s+"
        r"([A-Za-z]+)\s+(\d{4})",
        text
    )
    if match:
        day, month, year = match.groups()
        return datetime.strptime(
            f"{day} {month} {year}", "%d %b %Y"
        ).date()

    # Example: 24 Feb—01 Mar 2027
    match = re.search(
        r"(\d{1,2})\s+([A-Za-z]+)\s*—\s*"
        r"\d{1,2}\s+[A-Za-z]+\s+(\d{4})",
        text
    )
    if match:
        day, month, year = match.groups()
        return datetime.strptime(
            f"{day} {month} {year}", "%d %b %Y"
        ).date()

    return None


def find_next_world_cup():
    response = requests.get(
        CALENDAR_URL,
        timeout=30,
        headers={"User-Agent": "BiathlonCountdown/1.0"}
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    today = datetime.now(TIMEZONE).date()
    events = []

    for link in soup.find_all("a", href=True):
        href = link["href"]
        query = parse_qs(urlparse(href).query)
        event_id = query.get("EventId", [""])[0]

        # World Cup event IDs contain SWRLCP.
        if "SWRLCP" not in event_id.upper():
            continue

        text = " ".join(link.stripped_strings)
        start_date = parse_start_date(text)

        if not start_date or start_date < today:
            continue

        location = re.sub(
            r"^\s*\d{1,2}.*?\d{4}\s*",
            "", text
        ).strip()

        events.append({
            "date": start_date.isoformat(),
            "location": location or "World Cup venue",
            "url": href if href.startswith("http")
                   else "https://www.biathlonworld.com" + href
        })

    if not events:
        raise RuntimeError(
            "No upcoming World Cup events found. "
            "The official calendar may have changed format. "
            "No Discord message was changed."
        )

    events.sort(key=lambda event: event["date"])
    return events[0]


def make_message(event):
    start_date = datetime.combine(
        datetime.fromisoformat(event["date"]).date(),
        time(0, 0),
        tzinfo=TIMEZONE
    )
    timestamp = int(start_date.timestamp())

    return (
        "🎯 **BIATHLON WORLD CUP COUNTDOWN**\n\n"
        f"📍 **{event['location']}**\n"
        f"🏁 Season starts <t:{timestamp}:R>\n"
        f"🗓️ <t:{timestamp}:D>\n\n"
        f"[Official IBU calendar]({event['url']})"
    )


def main():
    event = find_next_world_cup()
    message = make_message(event)

    previous = {}
    if STATE_FILE.exists():
        previous = json.loads(STATE_FILE.read_text())

    # Avoid editing the Discord message if nothing changed.
    if (
        previous.get("event") == event
        and previous.get("message") == message
        and previous.get("message_id")
    ):
        print("Countdown unchanged.")
        return

    message_id = previous.get("message_id")

    if message_id:
        url = f"{WEBHOOK_URL}/messages/{message_id}"
        response = requests.patch(
            url,
            json={"content": message},
            timeout=30
        )
    else:
        separator = "&" if "?" in WEBHOOK_URL else "?"
        response = requests.post(
            WEBHOOK_URL + separator + "wait=true",
            json={"content": message},
            timeout=30
        )

    response.raise_for_status()
    result = response.json()

    if not message_id:
        message_id = result["id"]

    STATE_FILE.write_text(json.dumps({
        "event": event,
        "message": message,
        "message_id": message_id
    }, indent=2))

    print(f"Countdown updated: {event}")


if __name__ == "__main__":
    main()
