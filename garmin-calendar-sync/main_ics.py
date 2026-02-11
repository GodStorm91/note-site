#!/usr/bin/env python3
"""
Garmin → Google Calendar (ICS-based, simple version)

- Fetch Garmin training calendar (ICS) from ICS_URL
- Parse scheduled workouts (Base/Sprint/...)
- Map type → duration (Base/Sprint = 30')
- Find a time slot in:
  - Weekdays (Mon–Fri): 08:30–10:00
  - Weekends (Sat–Sun): 18:00–21:00
  with BUFFER_MINUTES before/after
- Create a single “🏃 …” event per day if none exists yet
"""

import os
import logging
from datetime import datetime, timedelta, date, time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


# ---------- Helpers ----------


def load_env() -> Tuple[str, int]:
    load_dotenv()
    ics_url = os.getenv(
        "GARMIN_ICS_URL",
        "https://connect.garmin.com/modern/calendar/export/56a37c8e29e14805932946f8770e208b",
    )
    buffer_minutes = int(os.getenv("BUFFER_MINUTES", "15"))
    return ics_url, buffer_minutes


def fetch_ics(ics_url: str) -> str:
    logger.info(f"Fetching Garmin ICS from {ics_url}")
    resp = requests.get(ics_url, timeout=15)
    resp.raise_for_status()
    return resp.text


def parse_ics_schedule(ics_text: str) -> Dict[date, str]:
    """Parse VEVENTs from Garmin ICS → {date: workout_type}."""
    schedule: Dict[date, str] = {}

    lines = [l.strip() for l in ics_text.splitlines()]
    current_summary: Optional[str] = None
    current_date: Optional[date] = None

    for line in lines:
        if line.startswith("SUMMARY:"):
            current_summary = line[len("SUMMARY:") :].strip()
        elif line.startswith("DTSTART"):
            # Example: DTSTART;VALUE=DATE:20260210
            if ":" in line:
                _, value = line.split(":", 1)
                value = value.strip()
                try:
                    dt = datetime.strptime(value, "%Y%m%d").date()
                    current_date = dt
                except ValueError:
                    current_date = None
        elif line == "END:VEVENT":
            if current_summary and current_date:
                schedule[current_date] = current_summary
            current_summary = None
            current_date = None

    logger.info("Parsed schedule from ICS:")
    for d, t in sorted(schedule.items()):
        logger.info(f"  {d} → {t}")
    return schedule


def map_type_to_duration_minutes(workout_type: str) -> int:
    t = workout_type.lower()
    if "long" in t:
        return 60
    if "sprint" in t:
        return 30
    # default Base / easy
    return 30


def get_google_service(token_file: str = "token_godstorm91.json"):
    token_path = Path(token_file)
    if not token_path.exists():
        raise RuntimeError(f"Token file not found: {token_file}")
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    service = build("calendar", "v3", credentials=creds)
    return service


def list_events_for_day(service, calendar_id: str, day: date) -> List[dict]:
    day_start = datetime.combine(day, time(0, 0))
    day_end = datetime.combine(day, time(23, 59, 59))
    try:
        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=day_start.isoformat() + "Z",
                timeMax=day_end.isoformat() + "Z",
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return events_result.get("items", [])
    except HttpError as e:
        logger.error(f"Error fetching events for {day}: {e}")
        return []


def parse_event_time(event_time: dict) -> datetime:
    if "dateTime" in event_time:
        dt_str = event_time["dateTime"]
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    elif "date" in event_time:
        return datetime.fromisoformat(event_time["date"])
    return datetime.now()


def find_time_slot_for_day(
    day: date,
    weekday_window: Tuple[time, time],
    weekend_window: Tuple[time, time],
    events: List[dict],
    duration_minutes: int,
    buffer_minutes: int,
) -> Optional[Tuple[datetime, datetime]]:
    """Return (start_dt, end_dt) in local time, or None if no slot."""
    # Decide window based on weekday/weekend
    if day.weekday() < 5:  # Mon–Fri
        start_t, end_t = weekday_window
        logger.info("  → Weekday: checking morning slot (8:30-10:00)")
    else:
        start_t, end_t = weekend_window
        logger.info("  → Weekend: checking evening slot (18:00-21:00)")

    window_start = datetime.combine(day, start_t)
    window_end = datetime.combine(day, end_t)

    slot_duration = timedelta(minutes=duration_minutes)
    buffer = timedelta(minutes=buffer_minutes)

    current = window_start
    while current + slot_duration <= window_end:
        slot_end = current + slot_duration
        is_free = True

        for e in events:
            summary = (e.get("summary") or "").lower()
            # Treat "Home/自宅" work-location blocks as soft → ignore them
            if "自宅" in summary or "home" == summary.strip():
                continue

            es = parse_event_time(e["start"]).replace(tzinfo=None)
            ee = parse_event_time(e["end"]).replace(tzinfo=None)
            # Overlap with buffer
            if (current - buffer) < ee and (slot_end + buffer) > es:
                is_free = False
                break

        if is_free:
            return current, slot_end

        # move by 15-min step
        current += timedelta(minutes=15)

    return None


def create_running_event(
    service,
    calendar_id: str,
    day: date,
    start: datetime,
    end: datetime,
    workout_type: str,
    duration_minutes: int,
) -> None:
    title = f"🏃 {workout_type} {duration_minutes}'"

    desc = "Garmin Coach (ICS-based)\n"
    desc += "─────────────────\n"
    desc += f"• Type: {workout_type}\n"
    desc += f"• Duration: {duration_minutes} minutes\n"
    desc += "\n─────────────────\n"
    desc += f"📅 {day.strftime('%A, %Y-%m-%d')}\n"
    desc += f"🕐 {start.strftime('%H:%M')}–{end.strftime('%H:%M')}"

    event = {
        "summary": title,
        "description": desc,
        "start": {
            "dateTime": start.isoformat(),
            "timeZone": "Asia/Tokyo",
        },
        "end": {
            "dateTime": end.isoformat(),
            "timeZone": "Asia/Tokyo",
        },
    }

    try:
        created = (
            service.events()
            .insert(calendarId=calendar_id, body=event)
            .execute()
        )
        logger.info(
            f"  ✓ Created event: {title} at {start.strftime('%H:%M')} "
            f"(link: {created.get('htmlLink')})"
        )
    except HttpError as e:
        logger.error(f"  ✗ Failed to create event: {e}")


# ---------- Main ----------


def main() -> None:
    ics_url, buffer_minutes = load_env()

    # 1) Fetch + parse ICS
    ics_text = fetch_ics(ics_url)
    schedule = parse_ics_schedule(ics_text)  # {date: "Base"/"Sprint"/...}

    # 2) Google Calendar service (primary calendar of godstorm token)
    service = get_google_service("token_godstorm91.json")

    cals = service.calendarList().list().execute().get("items", [])
    primary_cal = next((c for c in cals if c.get("primary")), None)
    if not primary_cal:
        raise RuntimeError("No primary calendar found for token_godstorm91")
    calendar_id = primary_cal["id"]
    logger.info(f"Using calendar: {primary_cal['summary']} ({calendar_id})")

    # 3) For next 7 days, apply schedule if exists
    today = date.today()
    weekday_window = (time(8, 30), time(10, 0))
    weekend_window = (time(18, 0), time(21, 0))

    for offset in range(0, 7):
        day = today + timedelta(days=offset)
        logger.info(f"\n📅 {day.strftime('%A, %Y-%m-%d')}")

        workout_type = schedule.get(day)
        if not workout_type:
            logger.info("  → No Garmin workout scheduled in ICS, skipping")
            continue

        duration_minutes = map_type_to_duration_minutes(workout_type)

        events = list_events_for_day(service, calendar_id, day)

        # If already has a 🏃 event, skip
        if any("🏃" in (e.get("summary") or "") for e in events):
            logger.info("  → Running event already exists, skipping")
            continue

        slot = find_time_slot_for_day(
            day,
            weekday_window=weekday_window,
            weekend_window=weekend_window,
            events=events,
            duration_minutes=duration_minutes,
            buffer_minutes=buffer_minutes,
        )

        if not slot:
            logger.info("  → No suitable time slots available")
            continue

        start_dt, end_dt = slot
        create_running_event(
            service,
            calendar_id,
            day,
            start_dt,
            end_dt,
            workout_type=workout_type,
            duration_minutes=duration_minutes,
        )

    logger.info("\n✅ ICS-based sync completed")


if __name__ == "__main__":
    main()
