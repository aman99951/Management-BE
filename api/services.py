import requests
from datetime import datetime, timezone
from django.conf import settings
from django.utils import timezone as django_timezone
from .models import FathomConfig, FathomUserToken, Meeting, Task, Employee

FATHOM_API_BASE = "https://api.fathom.ai/external/v1"


def coerce_recording_id(value):
    """Coerce a Fathom recording_id (int or numeric string) to an int, else None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_fathom_datetime(value):
    """Parse a Fathom timestamp that may be ISO-8601, MySQL-style, a unix epoch, or garbage."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        pass
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            naive = datetime.strptime(s, fmt)
            return naive.replace(tzinfo=django_timezone.get_current_timezone())
        except ValueError:
            continue
    return None

def get_config():
    return FathomConfig.objects.first()

def _normalize_key_entries(raw):
    """Normalize api_keys storage to a list of {key, added_by, added_at} dicts.

    Accepts plain key strings (legacy) or entry dicts.
    """
    entries = []
    for item in raw or []:
        if isinstance(item, dict):
            key = str(item.get("key") or "").strip()
            if not key:
                continue
            entries.append({
                "key": key,
                "added_by": str(item.get("added_by") or "").strip(),
                "added_at": str(item.get("added_at") or "").strip(),
            })
        else:
            key = str(item or "").strip()
            if key:
                entries.append({"key": key, "added_by": "", "added_at": ""})
    return entries

def get_api_key_entries(config=None):
    """Return all configured Fathom accounts as {key, added_by, added_at} dicts.

    Includes the legacy api_key as the first entry when it isn't already in api_keys.
    """
    config = config or get_config()
    if not config:
        return []
    entries = _normalize_key_entries(config.api_keys)
    seen = {e["key"] for e in entries}
    if config.api_key and config.api_key not in seen:
        entries.insert(0, {"key": config.api_key, "added_by": "", "added_at": ""})
    return entries

def get_api_key_list(config=None):
    """Return every configured Fathom API key (legacy api_key + api_keys list), deduplicated."""
    return [e["key"] for e in get_api_key_entries(config)]

def mask_key(key):
    """Mask a key for display: show first 6 + last 4 chars."""
    if not key:
        return ''
    if len(key) <= 10:
        return key
    return f"{key[:6]}...{key[-4:]}"

def resolve_masked_keys(requested, stored_entries):
    """Map masked keys from the client back to the real stored keys.

    The Settings page shows masked keys; when it saves the whole list back we need
    to restore the original values. Items without '...' are treated as raw new keys.
    """
    stored_by_mask = {}
    for e in stored_entries:
        stored_by_mask.setdefault(mask_key(e["key"]), e)
    resolved = []
    for item in requested:
        if isinstance(item, dict):
            key = str(item.get("key") or "").strip()
            added_by = str(item.get("added_by") or "").strip()
            added_at = str(item.get("added_at") or "").strip()
        else:
            key = str(item or "").strip()
            added_by = ""
            added_at = ""
        if not key:
            continue
        if "..." in key and key in stored_by_mask:
            e = stored_by_mask[key]
            resolved.append({
                "key": e["key"],
                "added_by": added_by or e.get("added_by") or "",
                "added_at": added_at or e.get("added_at") or "",
            })
        else:
            resolved.append({"key": key, "added_by": added_by, "added_at": added_at})
    # dedupe by key, keep first occurrence
    seen = set()
    unique = []
    for e in resolved:
        if e["key"] not in seen:
            seen.add(e["key"])
            unique.append(e)
    return unique

def fathom_headers(user=None):
    if user:
        token = get_user_fathom_token(user)
        if token:
            return {"Authorization": f"Bearer {token}"}
    keys = get_api_key_list()
    if not keys:
        return None
    return {"X-Api-Key": keys[0]}

def all_fathom_headers():
    """Yield header dicts for every configured Fathom account API key."""
    for key in get_api_key_list():
        if key:
            yield {"X-Api-Key": key}

def fetch_meetings(cursor=None):
    """Fetch meetings across every configured Fathom account, deduplicated by recording_id.

    Whichever account's notetaker stayed in the meeting records it, so a sync across
    all keys always finds the complete recording.
    """
    params = {
        "include_summary": "true",
        "include_action_items": "true",
        "include_transcript": "true",
    }
    if cursor:
        params["cursor"] = cursor
    items = []
    seen_ids = set()
    for headers in all_fathom_headers():
        resp = requests.get(f"{FATHOM_API_BASE}/meetings", headers=headers, params=params)
        if resp.status_code != 200:
            continue
        data = resp.json()
        for item in data.get("items", []):
            rid = item.get("recording_id")
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            items.append(item)
    return {"items": items}

def fetch_transcript(recording_id):
    for headers in all_fathom_headers():
        resp = requests.get(f"{FATHOM_API_BASE}/recordings/{recording_id}/transcript", headers=headers)
        if resp.status_code == 200:
            return resp.json()
    return None

def find_fathom_recording(meeting):
    headers = fathom_headers()
    if not headers:
        return None
    data = fetch_meetings()
    if not data:
        return None
    for item in data.get("items", []):
        item_title = (item.get("meeting_title") or item.get("title", "")).lower().strip()
        meeting_title = meeting.title.lower().strip()
        if meeting_title and (item_title == meeting_title or item_title.startswith(meeting_title) or meeting_title.startswith(item_title)):
            transcript = item.get("transcript")
            if not transcript:
                tdata = fetch_transcript(item["recording_id"])
                if tdata:
                    transcript = tdata.get("transcript", tdata.get("items", tdata))
            obj, _ = Meeting.objects.update_or_create(
                fathom_recording_id=item["recording_id"],
                defaults={
                    "title": item.get("meeting_title") or item.get("title", meeting.title),
                    "meeting_url": item.get("url", meeting.meeting_url),
                    "share_url": item.get("share_url", ""),
                    "recorded_at": parse_fathom_datetime(item.get("recording_start_time")),
                    "summary": (
                        item.get("default_summary", {}).get("markdown_formatted", "")
                        if item.get("default_summary") else ""
                    ),
                    "raw_summary": item.get("default_summary"),
                    "raw_action_items": item.get("action_items"),
                    "transcript": transcript,
                },
            )
            return obj
    return None

def fetch_meetings_from_fathom_by_title(title):
    headers = fathom_headers()
    if not headers:
        return None
    data = fetch_meetings()
    if not data:
        return None
    title_lower = title.lower().strip()
    for item in data.get("items", []):
        item_title = (item.get("meeting_title") or item.get("title", "")).lower().strip()
        if title_lower and (item_title == title_lower or item_title.startswith(title_lower) or title_lower.startswith(item_title)):
            return item
    return None

def fetch_meeting_by_id(recording_id):
    """Fetch a single meeting's full details (transcript + summary) from Fathom API.

    Tries every configured account so a recording made by any Fathom notetaker is found.
    """
    params = {
        "include_summary": "true",
        "include_action_items": "true",
        "include_transcript": "true",
    }
    for headers in all_fathom_headers():
        resp = requests.get(f"{FATHOM_API_BASE}/meetings/{recording_id}", headers=headers, params=params)
        if resp.status_code == 200:
            return resp.json()
    return None


def sync_meetings():
    data = fetch_meetings()
    if not data:
        return [], 0
    new_meetings = []
    count = 0
    for item in data.get("items", []):
        transcript = item.get("transcript")
        if not transcript:
            tdata = fetch_transcript(item["recording_id"])
            if tdata:
                transcript = tdata.get("transcript", tdata.get("items", tdata))
        meeting, created = Meeting.objects.update_or_create(
            fathom_recording_id=item["recording_id"],
            defaults={
                "title": item.get("meeting_title") or item.get("title", ""),
                "meeting_url": item.get("url", ""),
                "share_url": item.get("share_url", ""),
                "recorded_at": parse_fathom_datetime(item.get("recording_start_time")),
                "summary": (
                    item.get("default_summary", {}).get("markdown_formatted", "")
                    if item.get("default_summary") else ""
                ),
                "raw_summary": item.get("default_summary"),
                "raw_action_items": item.get("action_items"),
                "transcript": transcript,
            },
        )
        if created:
            new_meetings.append(meeting)
            count += 1
    return new_meetings, count

def _process_action_items(fathom_data, meeting):
    action_items = fathom_data.get("action_items", [])
    for ai in action_items:
        description = ai.get("description", "")
        assignee_data = ai.get("assignee", {})
        employee = None
        if assignee_data and assignee_data.get("email"):
            employee, _ = Employee.objects.get_or_create(
                email=assignee_data["email"],
                defaults={"name": assignee_data.get("name", ""), "team": assignee_data.get("team") or ""},
            )
        Task.objects.update_or_create(
            meeting=meeting,
            title=description[:500],
            defaults={
                'description': description,
                'assigned_to': employee,
            },
        )

def _extract_tasks_from_summary(summary_text, meeting):
    if not summary_text:
        return
    import re
    in_tasks = False
    current_person_name = None
    person_bullets = {}
    task_headers = ['current tasks', 'tasks:', 'action items', 'action items:']
    for line in summary_text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('## '):
            current_person_name = stripped[3:].strip()
            in_tasks = False
            continue
        if stripped.startswith('### '):
            heading = stripped[4:].lower().strip()
            in_tasks = any(h in heading for h in task_headers)
            continue
        if in_tasks and stripped.startswith('- '):
            task_text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', stripped[2:]).strip()
            if task_text:
                key = current_person_name or 'Unowned'
                person_bullets.setdefault(key, []).append(task_text)
    for person_name, bullets in person_bullets.items():
        full_desc = '\n'.join(f'- {b}' for b in bullets)
        title = f"Tasks for {person_name}" if person_name != 'Unowned' else 'Action Items'
        employee = Employee.objects.filter(name__iexact=person_name.strip()).first() if person_name != 'Unowned' else None
        Task.objects.update_or_create(
            meeting=meeting,
            title=title,
            defaults={
                'description': full_desc,
                'assigned_to': employee,
                'status': 'pending',
            },
        )

def process_webhook_payload(payload):
    """Create or update a Meeting from a Fathom webhook payload, tolerantly.

    Never rejects the payload because a field is missing/malformed — returns
    (None, False) when there is no usable recording_id, otherwise saves the
    meeting with whatever fields are present. Empty transcript/summary values
    are NOT written so a retry (which may arrive before Fathom finishes
    processing) can't wipe previously-synced data.
    """
    payload = payload or {}
    recording_id = coerce_recording_id(payload.get("recording_id"))
    if not recording_id:
        return None, False

    summary_data = payload.get("default_summary")
    if isinstance(summary_data, dict):
        summary = summary_data.get("markdown_formatted") or summary_data.get("text") or ""
    elif isinstance(summary_data, str):
        summary = summary_data
    else:
        summary = ""

    defaults = {}
    non_empty_fields = {
        "title": payload.get("meeting_title") or payload.get("title") or "Untitled Meeting",
        "meeting_url": payload.get("url") or "",
        "share_url": payload.get("share_url") or "",
        "recorded_at": parse_fathom_datetime(payload.get("recording_start_time")),
        "summary": summary,
        "raw_summary": summary_data,
        "raw_action_items": payload.get("action_items"),
        "transcript": payload.get("transcript"),
    }
    for key, value in non_empty_fields.items():
        if value not in (None, ""):
            defaults[key] = value

    meeting, created = Meeting.objects.update_or_create(
        fathom_recording_id=recording_id,
        defaults=defaults,
    )
    return meeting, created

def get_user_fathom_token(user):
    try:
        return user.fathom_token.access_token
    except (FathomUserToken.DoesNotExist, AttributeError):
        return None

def exchange_fathom_code(code, user):
    client_id = settings.FATHOM_OAUTH_CLIENT_ID
    client_secret = settings.FATHOM_OAUTH_CLIENT_SECRET
    redirect_uri = settings.FATHOM_OAUTH_REDIRECT_URI
    resp = requests.post("https://api.fathom.ai/oauth/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    })
    if resp.status_code != 200:
        return None
    data = resp.json()
    token, _ = FathomUserToken.objects.update_or_create(
        user=user,
        defaults={
            "access_token": data.get("access_token", ""),
            "refresh_token": data.get("refresh_token", ""),
        },
    )
    return token.access_token
