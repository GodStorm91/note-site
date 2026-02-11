#!/usr/bin/env python3
"""Cleanup script: delete auto-generated running events in the future.

Deletes events whose summary contains "🏃" or "Running" from the primary
calendar starting today onwards.
"""

import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar']


def main() -> None:
    creds = Credentials.from_authorized_user_file('token_godstorm91.json', SCOPES)
    service = build('calendar', 'v3', credentials=creds)

    now = datetime.datetime.now()
    end = now + datetime.timedelta(days=30)

    events = service.events().list(
        calendarId='primary',
        timeMin=now.isoformat() + 'Z',
        timeMax=end.isoformat() + 'Z',
        singleEvents=True,
        orderBy='startTime',
    ).execute().get('items', [])

    delete_ids = []
    for event in events:
        summary = event.get('summary', '') or ''
        # Heuristic: our auto-generated events always contain the running emoji
        # or start with "🏃" in the summary
        if '🏃' in summary or summary.startswith('Running'):
            delete_ids.append(event['id'])

    print(f'Found {len(delete_ids)} running events to delete')
    for event_id in delete_ids:
        service.events().delete(calendarId='primary', eventId=event_id).execute()
        print('  Deleted event', event_id)


if __name__ == '__main__':
    main()
