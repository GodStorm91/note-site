#!/usr/bin/env python3
"""
Garmin Coach → Google Calendar (Coach API version)

- Dùng get_adaptive_training_plan_by_id(plan_id) để lấy taskList
- Mỗi task có:
    - calendarDate: '2026-02-10'
    - taskWorkout: workoutName (Base/Sprint/Threshold...), workoutDescription,
      estimatedDurationInSecs, restDay, workoutPhrase,...
- Bỏ ngày restDay == True
- Duration = estimatedDurationInSecs/60 (round)
- Tìm slot:
    - Weekday: 08:30–10:00
    - Weekend: 18:00–21:00
    - Buffer = BUFFER_MINUTES (mặc định 5), bỏ qua block 'Home/自宅'
- Nếu ngày đó chưa có event 🏃 thì tạo event:
    - Title: '🏃 Base 30''
    - Description: type + duration + workoutDescription + ngày/giờ
"""

import os
import logging
from datetime import datetime, timedelta, date, time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from garminconnect import Garmin
from main import GarminCalendarSync

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
PLAN_ID = 43285461  # Coach plan ID


def load_env() -> Tuple[int, str, str]:
    load_dotenv()
    buffer_minutes = int(os.getenv("BUFFER_MINUTES", "5"))
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError("GARMIN_EMAIL / GARMIN_PASSWORD missing in .env")
    return buffer_minutes, email, password


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


def login_garmin_reuse_session() -> Garmin:
    """Reuse login logic from main.py (uses ~/.garminconnect tokens)."""
    sync = GarminCalendarSync()
    if not sync.login_garmin():
        raise RuntimeError("Garmin login failed via GarminCalendarSync")
    return sync.garmin_client


def get_schedule_from_plan(garmin: Garmin) -> Dict[date, dict]:
    """Return { date: { 'type', 'description', 'duration_mins', 'rest' } }"""
    logger.info(f"Fetching adaptive training plan {PLAN_ID}")
    plan = garmin.get_adaptive_training_plan_by_id(PLAN_ID)

    task_list = plan.get("taskList", [])
    schedule: Dict[date, dict] = {}

    for task in task_list:
        calendar_date = task.get("calendarDate")
        tw = task.get("taskWorkout") or {}
        rest_day = tw.get("restDay", False)
        w_name = tw.get("workoutName")  # Base / Sprint / Threshold...
        w_desc = tw.get("workoutDescription")
        est_secs = tw.get("estimatedDurationInSecs", 0)

        if not calendar_date:
            continue
        try:
            d = datetime.strptime(calendar_date, "%Y-%m-%d").date()
        except ValueError:
            continue

        schedule[d] = {
            "type": w_name or tw.get("workoutPhrase") or "Workout",
            "description": w_desc or "",
            "duration_mins": int(round(est_secs / 60)) if est_secs else 0,
            "rest": bool(rest_day),
        }

    logger.info("Coach schedule (from plan):")
    for d, info in sorted(schedule.items()):
        logger.info(
            f"  {d} → type={info['type']}, rest={info['rest']}, "
            f"duration={info['duration_mins']}m, desc={info['description']}"
        )
    return schedule


def find_time_slot_for_day(
    day: date,
    weekday_window: Tuple[time, time],
    weekend_window: Tuple[time, time],
    events: List[dict],
    duration_minutes: int,
    buffer_minutes: int,
) -> Optional[Tuple[datetime, datetime]]:
    """Return (start_dt, end_dt) in local time, or None if no slot."""
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
            # Bỏ qua block Home/自宅
            if "自宅" in summary or summary.strip() == "home":
                continue

            es = parse_event_time(e["start"]).replace(tzinfo=None)
            ee = parse_event_time(e["end"]).replace(tzinfo=None)
            if (current - buffer) < ee and (slot_end + buffer) > es:
                is_free = False
                break

        if is_free:
            return current, slot_end

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
    description_text: str,
) -> None:
    title = f"🏃 {workout_type} {duration_minutes}'"

    desc = "Garmin Coach – Adaptive Plan\n"
    desc += "─────────────────\n"
    desc += f"• Type: {workout_type}\n"
    if duration_minutes:
        desc += f"• Duration: {duration_minutes} minutes\n"
    if description_text:
        desc += f"• Workout: {description_text}\n"
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


def main() -> None:
    buffer_minutes, email, password = load_env()

    # Reuse existing Garmin session (MFA-safe)
    garmin = login_garmin_reuse_session()
    schedule = get_schedule_from_plan(garmin)

    service = get_google_service("token_godstorm91.json")
    cals = service.calendarList().list().execute().get("items", [])
    primary_cal = next((c for c in cals if c.get("primary")), None)
    if not primary_cal:
        raise RuntimeError("No primary calendar found for token_godstorm91")
    calendar_id = primary_cal["id"]
    logger.info(f"Using calendar: {primary_cal['summary']} ({calendar_id})")

    today = date.today()
    weekday_window = (time(8, 30), time(10, 0))
    weekend_window = (time(18, 0), time(21, 0))

    for offset in range(0, 7):
        day = today + timedelta(days=offset)
        logger.info(f"\n📅 {day.strftime('%A, %Y-%m-%d')}")

        info = schedule.get(day)
        if not info:
            logger.info("  → No Coach workout scheduled for this day, skipping")
            continue

        if info["rest"]:
            logger.info("  → Rest day in Coach plan, skipping")
            continue

        workout_type = info["type"] or "Workout"
        description_text = info["description"] or ""
        duration_minutes = info["duration_mins"] or 30

        events = list_events_for_day(service, calendar_id, day)

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
            description_text=description_text,
        )

    logger.info("\n✅ Coach-API-based sync completed")


if __name__ == "__main__":
    main()
