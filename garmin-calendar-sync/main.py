#!/usr/bin/env python3
"""
Garmin Calendar Sync
Fetch training data from Garmin Connect and sync to Google Calendar
with AI-optimized scheduling based on user's preferences.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from garminconnect import Garmin

# Import Google libraries
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Google Calendar OAuth scope
SCOPES = ['https://www.googleapis.com/auth/calendar']


class GarminCalendarSync:
    """Main sync engine for Garmin to Google Calendar."""
    
    def __init__(self):
        load_dotenv()
        self.garmin_email = os.getenv('GARMIN_EMAIL')
        self.garmin_password = os.getenv('GARMIN_PASSWORD')
        
        # Scheduling preferences
        self.weekday_morning_start = os.getenv('WEEKDAY_MORNING_START', '08:30')
        self.weekday_morning_end = os.getenv('WEEKDAY_MORNING_END', '10:00')
        self.weekend_evening_start = os.getenv('WEEKEND_EVENING_START', '18:00')
        self.weekend_evening_end = os.getenv('WEEKEND_EVENING_END', '21:00')
        self.buffer_minutes = int(os.getenv('BUFFER_MINUTES', '30'))
        
        # Calendar configs - both tokens access same primary calendar (wealthpark)
        # godstorm91 token has owner access, wealthpark token has read-only
        # We'll use godstorm91 token to write, and skip wealthpark for writes
        self.calendars = {
            'godstorm': {
                'id': 'primary',
                'email': os.getenv('CALENDAR_ID_GODSTORM', 'godstorm91@gmail.com'),
                'token_file': os.getenv('GOOGLE_TOKEN_GODSTORM91', 'token_godstorm91.json'),
                'can_write': True
            },
            'wealthpark': {
                'id': 'primary',
                'email': os.getenv('CALENDAR_ID_WEALTHPARK', 'khanh.nguyen@wealth-park.com'),
                'token_file': os.getenv('GOOGLE_TOKEN_WEALTHPARK', 'token_khanh_wealthpark.json'),
                'can_write': False  # Read-only access
            }
        }
        
        self.garmin_client = None
        self.google_services = {}
    
    def login_garmin(self) -> bool:
        """Login to Garmin Connect using cached tokens."""
        garmin_token_dir = os.path.expanduser("~/.garminconnect")
        
        try:
            logger.info(f"Logging in to Garmin Connect as {self.garmin_email}")
            
            # First try to load existing session via tokenstore
            if os.path.exists(garmin_token_dir):
                logger.info("  → Loading existing session from ~/.garminconnect")
                try:
                    self.garmin_client = Garmin(self.garmin_email, self.garmin_password)
                    self.garmin_client.login(tokenstore=str(garmin_token_dir))
                    logger.info(f"✓ Garmin login successful")
                    logger.info(f"  User: {self.garmin_client.display_name}")
                    return True
                except Exception as e:
                    logger.warning(f"  ⚠ Could not load cached session: {e}")
                    logger.info("  → Attempting fresh login with MFA...")
            
            # No valid session, need to login
            logger.info("  → No valid session, logging in with MFA support...")
            
            if not self.garmin_email or not self.garmin_password:
                logger.error("  ✗ GARMIN_EMAIL and GARMIN_PASSWORD required in .env")
                return False
            
            # Login with MFA (will prompt if needed)
            garth.login(self.garmin_email, self.garmin_password)
            
            # Save session for future use
            garth.save(garmin_token_dir)
            logger.info("  ✓ Session saved to ~/.garminconnect")
            
            self.garmin_client = Garmin(client=garth.client)
            logger.info("✓ Garmin login successful")
            return True
            
        except Exception as e:
            logger.error(f"✗ Garmin login failed: {e}")
            logger.info("\n💡 If you have MFA enabled, run this first:")
            logger.info("   python3 login_mfa.py")
            return False
    
    def get_google_service(self, account_name: str) -> Optional[object]:
        """Get authenticated Google Calendar service for an account."""
        config = self.calendars[account_name]
        creds_file = config['token_file']
        creds_path = Path(__file__).parent / creds_file
        
        creds = None
        
        # Check for cached credentials
        if creds_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(creds_path), SCOPES)
                logger.info(f"  → Loaded cached credentials for {config['id']}")
            except Exception as e:
                logger.warning(f"  ⚠ Could not load cached credentials: {e}")
        
        # If no valid credentials, run OAuth flow
        if not creds or not creds.valid:
            google_creds_file = Path(__file__).parent / os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
            
            if not google_creds_file.exists():
                logger.error(f"✗ Google credentials file not found: {google_creds_file}")
                logger.info("   Please setup Google Cloud Console first!")
                return None
            
            logger.info(f"🔐 Starting OAuth flow for {config['email']}")
            flow = InstalledAppFlow.from_client_secrets_file(str(google_creds_file), SCOPES)
            creds = flow.run_local_server(port=0)
            
            # Save credentials for future use
            with open(creds_path, 'w') as f:
                f.write(creds.to_json())
            logger.info(f"  ✓ Credentials saved to {creds_file}")
        
        service = build('calendar', 'v3', credentials=creds)
        logger.info(f"✓ Google Calendar service ready for {config['email']}")
        return service
    
    def get_existing_events(self, service, calendar_id: str, days: int = 7) -> list:
        """Get existing events from calendar."""
        try:
            now = datetime.utcnow()
            end_time = now + timedelta(days=days)
            
            events_result = service.events().list(
                calendarId=calendar_id,
                timeMin=now.isoformat() + 'Z',
                timeMax=end_time.isoformat() + 'Z',
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            logger.info(f"  Found {len(events)} existing events in next {days} days")
            return events
            
        except HttpError as e:
            logger.error(f"✗ Error fetching events: {e}")
            return []
    
    def get_garmin_training_data(self) -> list:
        """Fetch training data from Garmin Connect."""
        try:
            # Get recent activities
            activities = self.garmin_client.get_activities(
                start=0, 
                limit=10
            )
            
            # Get training plans if available
            try:
                training_plans = self.garmin_client.get_training_plans()
            except:
                training_plans = []
            
            logger.info(f"✓ Fetched {len(activities)} activities, {len(training_plans)} training plans")
            
            # Get stats from latest running activity
            latest_run = None
            for activity in activities:
                if activity.get('activityType', {}).get('typeKey') == 'running':
                    latest_run = activity
                    break
            
            # Parse stats from latest run
            stats = {}
            if latest_run:
                dist_m = latest_run.get('distance', 0)
                duration_s = latest_run.get('duration', 0)
                avg_hr = latest_run.get('averageHR', 0)
                max_hr = latest_run.get('maxHR', 0)
                avg_cadence = latest_run.get('averageRunningCadenceInStepsPerMinute', 0)
                training_effect = latest_run.get('aerobicTrainingEffect', 0)
                activity_name = latest_run.get('activityName', 'Running')
                
                # Extract run type from name (e.g., "Koshigaya City - Long Run" -> "Long Run")
                run_type = 'Running'
                if ' - ' in activity_name:
                    run_type = activity_name.split(' - ')[-1].strip()
                
                stats = {
                    'activity_name': activity_name,
                    'run_type': run_type,
                    'distance_km': dist_m / 1000 if dist_m else 0,
                    'duration_mins': int(duration_s // 60) if duration_s else 0,
                    'duration_secs': int(duration_s % 60) if duration_s else 0,
                    'avg_hr': int(avg_hr) if avg_hr else 0,
                    'max_hr': int(max_hr) if max_hr else 0,
                    'cadence': int(avg_cadence) if avg_cadence else 0,
                    'training_effect': training_effect,
                }
                logger.info(f"  → Latest: {run_type} - {dist_m/1000:.1f}km in {int(duration_s//60)}m")
            
            return {
                'activities': activities,
                'training_plans': training_plans,
                'stats': stats
            }
            
        except Exception as e:
            logger.error(f"✗ Error fetching Garmin data: {e}")
            return {'activities': [], 'training_plans': [], 'stats': {}}
    
    def find_optimal_time_slots(self, day_of_week: int, existing_events: list, base_date: datetime) -> list:
        """Find optimal running time slots based on user preferences and existing events.
        
        Args:
            day_of_week: 0=Monday, 6=Sunday
            existing_events: List of existing calendar events
            base_date: Date for which we are scheduling (use its calendar day)
        """
        # Define preferred time window for this day
        if day_of_week < 5:  # Monday to Friday
            start_str = self.weekday_morning_start
            end_str = self.weekday_morning_end
            logger.info("  → Weekday: checking morning slot (8:30-10:00)")
        else:  # Saturday and Sunday
            start_str = self.weekend_evening_start
            end_str = self.weekend_evening_end
            logger.info("  → Weekend: checking evening slot (18:00-21:00)")
        
        # Parse time window on the specific check_date (not 'now')
        start_hour, start_min = map(int, start_str.split(':'))
        end_hour, end_min = map(int, end_str.split(':'))
        
        window_start = base_date.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
        window_end = base_date.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)
        
        # Find available 1-hour slots within the window
        available_slots = []
        slot_duration = timedelta(hours=1)
        buffer = timedelta(minutes=self.buffer_minutes)
        
        current = window_start
        while current + slot_duration <= window_end:
            slot_end = current + slot_duration
            
            # Check if slot conflicts with existing events
            is_available = True
            for event in existing_events:
                event_start = self._parse_event_time(event['start'])
                event_end = self._parse_event_time(event['end'])
                
                # Check for overlap (with buffer)
                if (current + buffer < event_end and slot_end - buffer > event_start):
                    is_available = False
                    break
            
            if is_available:
                available_slots.append({
                    'start': current,
                    'end': slot_end,
                    'formatted': current.strftime('%H:%M')
                })
            
            current += slot_duration
        
        return available_slots
    
    def _parse_event_time(self, event_time) -> datetime:
        """Parse event time from Google Calendar format."""
        if 'dateTime' in event_time:
            dt_str = event_time['dateTime']
            # Handle 'Z' suffix (UTC)
            if dt_str.endswith('Z'):
                dt_str = dt_str[:-1] + '+00:00'
            dt = datetime.fromisoformat(dt_str)
            # Convert to naive datetime (strip timezone for comparison)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        elif 'date' in event_time:
            # All-day event - set to naive datetime
            return datetime.fromisoformat(event_time['date'])
        return datetime.now()
    
    def create_calendar_event(self, service, calendar_id: str, title: str, 
                               description: str, start_time: datetime, 
                               end_time: datetime) -> Optional[str]:
        """Create a calendar event."""
        event = {
            'summary': title,
            'description': description,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Tokyo',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Tokyo',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 30},
                    {'method': 'popup', 'minutes': 10},
                ],
            },
        }
        
        try:
            created_event = service.events().insert(
                calendarId=calendar_id,
                body=event
            ).execute()
            
            event_link = created_event.get('htmlLink')
            logger.info(f"  ✓ Created event: {title} at {start_time.strftime('%H:%M')}")
            return event_link
            
        except HttpError as e:
            logger.error(f"  ✗ Failed to create event: {e}")
            return None
    
    def process_and_sync(self):
        """Main processing and sync logic."""
        logger.info("=" * 50)
        logger.info("🏃 Garmin Calendar Sync Started")
        logger.info("=" * 50)
        
        # Step 1: Login to Garmin
        if not self.login_garmin():
            logger.error("Cannot proceed without Garmin login")
            return
        
        # Step 2: Get training data
        training_data = self.get_garmin_training_data()
        garmin_stats = training_data.get('stats', {})
        
        # Step 3: Initialize Google services for both accounts
        for account_name, config in self.calendars.items():
            self.google_services[account_name] = self.get_google_service(account_name)
        
        # Step 4: Check next 7 days for running opportunities
        today = datetime.now()
        events_created = 0
        
        for day_offset in range(7):
            check_date = today + timedelta(days=day_offset)
            day_of_week = check_date.weekday()
            
            logger.info(f"\n📅 {check_date.strftime('%A, %Y-%m-%d')}")
            
            # Collect events from godstorm calendar (write-enabled) for this day
            service = self.google_services.get('godstorm')
            if not service:
                logger.error("  ✗ No Google service available")
                continue
                
            day_start = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = check_date.replace(hour=23, minute=59, second=59, microsecond=0)
            
            try:
                events_result = service.events().list(
                    calendarId=self.calendars['godstorm']['id'],
                    timeMin=day_start.isoformat() + 'Z',
                    timeMax=day_end.isoformat() + 'Z',
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
                all_events = events_result.get('items', [])
            except HttpError as e:
                logger.error(f"  Error fetching calendar: {e}")
                continue
            
            # Check if running event already exists for this day
            has_running_event = any(
                '🏃' in event.get('summary', '') for event in all_events
            )
            
            if has_running_event:
                logger.info("  → Running event already exists, skipping")
                continue
            
            # Find optimal time slots on this specific date
            available_slots = self.find_optimal_time_slots(day_of_week, all_events, check_date)
            
            if available_slots:
                # Pick the first available slot
                slot = available_slots[0]
                
                # Build title and description from Garmin stats
                run_type = garmin_stats.get('run_type', 'Running')
                title = f"🏃 {run_type}"
                
                # Build description with Garmin stats
                description = "🏃 Garmin Running Stats\n"
                description += "─────────────────\n"
                
                if garmin_stats:
                    dist_km = garmin_stats.get('distance_km', 0)
                    duration_mins = garmin_stats.get('duration_mins', 0)
                    duration_secs = garmin_stats.get('duration_secs', 0)
                    avg_hr = garmin_stats.get('avg_hr', 0)
                    max_hr = garmin_stats.get('max_hr', 0)
                    cadence = garmin_stats.get('cadence', 0)
                    training_effect = garmin_stats.get('training_effect', 0)
                    
                    if dist_km:
                        description += f"📏 Last: {dist_km:.2f}km\n"
                    if duration_mins:
                        description += f"⏱️ Duration: {duration_mins}m {duration_secs}s\n"
                    if avg_hr:
                        description += f"❤️ Avg HR: {avg_hr} bpm\n"
                    if max_hr:
                        description += f"💓 Max HR: {max_hr} bpm\n"
                    if cadence:
                        description += f"🦶 Cadence: {cadence} spm\n"
                    if training_effect:
                        description += f"📊 Training Effect: {training_effect}\n"
                
                description += f"\n─────────────────\n"
                description += f"📅 {check_date.strftime('%A, %Y-%m-%d')}\n"
                description += f"🕐 {slot['formatted']}"
                
                # Create event
                result = self.create_calendar_event(
                    service=service,
                    calendar_id=self.calendars['godstorm']['id'],
                    title=title,
                    description=description,
                    start_time=slot['start'],
                    end_time=slot['end']
                )
                if result:
                    events_created += 1
            else:
                logger.info("  → No suitable time slots available")
        
        logger.info("\n" + "=" * 50)
        logger.info("✅ Sync completed!")
        logger.info("=" * 50)


def main():
    """Entry point."""
    sync = GarminCalendarSync()
    sync.process_and_sync()


if __name__ == "__main__":
    main()
