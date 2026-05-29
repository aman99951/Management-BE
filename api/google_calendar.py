import requests
from datetime import datetime, timedelta, timezone
from django.conf import settings
from django.utils import timezone
from .models import GoogleCalendarToken, Meeting

GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


def get_google_calendar_credentials(user):
    """Retrieve a valid access token for the user, refreshing if needed."""
    try:
        token_obj = GoogleCalendarToken.objects.get(user=user)
    except GoogleCalendarToken.DoesNotExist:
        return None

    # Check if token is expired and refresh if possible
    if token_obj.is_expired and token_obj.refresh_token:
        refreshed = _refresh_access_token(token_obj)
        if not refreshed:
            return None

    return token_obj.access_token


def _refresh_access_token(token_obj):
    """Refresh the access token using the refresh token."""
    client_id = settings.GOOGLE_CLIENT_ID
    client_secret = settings.GOOGLE_CLIENT_SECRET
    if not client_id or not client_secret:
        return False

    resp = requests.post(
        GOOGLE_OAUTH_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": token_obj.refresh_token,
            "grant_type": "refresh_token",
        },
    )
    if resp.status_code != 200:
        return False

    data = resp.json()
    token_obj.access_token = data.get("access_token", token_obj.access_token)
    expires_in = data.get("expires_in", 3600)
    token_obj.expires_at = timezone.now() + timedelta(seconds=expires_in)
    token_obj.save(update_fields=["access_token", "expires_at"])
    return True


def _get_auth_headers(user):
    """Get Authorization headers for Google API calls."""
    token = get_google_calendar_credentials(user)
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def create_meet_event(user, title, description="", start_time=None, end_time=None):
    """
    Create a Google Calendar event with Google Meet video conferencing.
    Returns a tuple: (event_data, error)
    - On success: (event_dict, None)
    - On no token: (None, "no_token")
    - On API error: (None, error_message_string)
    """
    headers = _get_auth_headers(user)
    if not headers:
        return None, "no_token"

    if not start_time:
        start_time = timezone.now() + timedelta(hours=1)
    if not end_time:
        end_time = start_time + timedelta(hours=1)

    event_body = {
        "summary": title,
        "description": description,
        "start": {
            "dateTime": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": end_time.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC",
        },
        "conferenceData": {
            "createRequest": {
                "requestId": f"managepro-{user.id}-{int(timezone.now().timestamp())}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }

    import logging
    logger = logging.getLogger(__name__)

    resp = requests.post(
        f"{GOOGLE_CALENDAR_API}/calendars/primary/events",
        headers=headers,
        params={"conferenceDataVersion": 1},
        json=event_body,
    )

    if resp.status_code != 200:
        error_data = resp.json()
        error_message = error_data.get('error', {}).get('message', resp.text)
        logger.error(f"Google Calendar API error for user {user.id}: {resp.status_code} - {error_message}")
        return None, error_message

    return resp.json(), None


def list_upcoming_events(user, max_results=25):
    """List upcoming events from the user's primary Google Calendar."""
    headers = _get_auth_headers(user)
    if not headers:
        return None

    resp = requests.get(
        f"{GOOGLE_CALENDAR_API}/calendars/primary/events",
        headers=headers,
        params={
            "maxResults": max_results,
            "orderBy": "startTime",
            "singleEvents": True,
            "showDeleted": False,
            "timeMin": timezone.now().isoformat(),
        },
    )

    if resp.status_code != 200:
        return None

    return resp.json().get("items", [])


def list_past_events(user, max_results=50):
    """List past events from the user's primary Google Calendar (last 90 days)."""
    headers = _get_auth_headers(user)
    if not headers:
        return None

    from datetime import timedelta
    now = timezone.now()
    ninety_days_ago = now - timedelta(days=90)

    resp = requests.get(
        f"{GOOGLE_CALENDAR_API}/calendars/primary/events",
        headers=headers,
        params={
            "maxResults": max_results,
            "orderBy": "startTime",
            "singleEvents": True,
            "showDeleted": False,
            "timeMin": ninety_days_ago.isoformat(),
            "timeMax": now.isoformat(),
        },
    )

    if resp.status_code != 200:
        return None

    return resp.json().get("items", [])


def sync_calendar_events(user):
    """
    Sync upcoming and past Google Calendar events into our Meeting model.
    Returns the count of newly created meetings.
    """
    headers = _get_auth_headers(user)
    if not headers:
        return 0

    count = 0
    events = list_upcoming_events(user, max_results=50)
    past = list_past_events(user, max_results=50)
    all_events = (events or []) + (past or [])

    # Deduplicate by event id
    seen_ids = set()
    for event in all_events:
        event_id = event.get("id")
        if not event_id or event_id in seen_ids:
            continue
        seen_ids.add(event_id)

        title = event.get("summary", "Untitled Meeting")
        meet_link = ""
        if event.get("conferenceData") and event["conferenceData"].get("entryPoints"):
            for entry in event["conferenceData"]["entryPoints"]:
                if entry.get("entryPointType") == "video":
                    meet_link = entry.get("uri", "")
                    break

        start_info = event.get("start", {})
        start_time = start_info.get("dateTime") or start_info.get("date")

        # Parse start_time
        recorded_at = None
        if start_time:
            try:
                recorded_at = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # Check if this event already exists (by google_event_id or title+time matching)
        existing = Meeting.objects.filter(
            google_event_id=event_id
        ).first()

        if not existing:
            Meeting.objects.create(
                title=title,
                meeting_url=meet_link,
                recorded_at=recorded_at,
                google_event_id=event_id,
                summary="",
            )
            count += 1

    return count


def create_meeting_from_event(user, event):
    """Create a Meeting model instance from a Google Calendar event."""
    event_id = event.get("id")
    title = event.get("summary", "Untitled Meeting")

    meet_link = ""
    if event.get("conferenceData") and event["conferenceData"].get("entryPoints"):
        for entry in event["conferenceData"]["entryPoints"]:
            if entry.get("entryPointType") == "video":
                meet_link = entry.get("uri", "")
                break

    start_info = event.get("start", {})
    start_time = start_info.get("dateTime") or start_info.get("date")
    recorded_at = None
    if start_time:
        try:
            recorded_at = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

    meeting, created = Meeting.objects.update_or_create(
        google_event_id=event_id,
        defaults={
            "title": title,
            "meeting_url": meet_link,
            "recorded_at": recorded_at,
            "summary": event.get("description", ""),
        },
    )
    return meeting, created


from urllib.parse import urlencode


def get_google_calendar_auth_url(request):
    """Generate the Google OAuth URL for Calendar scopes."""
    client_id = settings.GOOGLE_CLIENT_ID
    redirect_uri = request.build_absolute_uri("/api/google-calendar/oauth/callback/")
    scope_str = " ".join(SCOPES)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope_str,
        "access_type": "offline",
        "prompt": "consent",
        "state": "google_calendar",
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return url
