import requests
from django.conf import settings
from .models import FathomConfig, FathomUserToken, Meeting, Task, Employee

FATHOM_API_BASE = "https://api.fathom.ai/external/v1"

def get_config():
    return FathomConfig.objects.first()

def fathom_headers(user=None):
    if user:
        token = get_user_fathom_token(user)
        if token:
            return {"Authorization": f"Bearer {token}"}
    config = get_config()
    if not config or not config.api_key:
        return None
    return {"X-Api-Key": config.api_key}

def fetch_meetings(cursor=None):
    headers = fathom_headers()
    if not headers:
        return None
    params = {
        "include_summary": "true",
        "include_action_items": "true",
        "include_transcript": "true",
    }
    if cursor:
        params["cursor"] = cursor
    resp = requests.get(f"{FATHOM_API_BASE}/meetings", headers=headers, params=params)
    if resp.status_code != 200:
        return None
    return resp.json()

def fetch_transcript(recording_id):
    headers = fathom_headers()
    if not headers:
        return None
    resp = requests.get(f"{FATHOM_API_BASE}/recordings/{recording_id}/transcript", headers=headers)
    if resp.status_code != 200:
        return None
    return resp.json()

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
                    "recorded_at": item.get("recording_start_time"),
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

def sync_meetings():
    data = fetch_meetings()
    if not data:
        return 0
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
                "recorded_at": item.get("recording_start_time"),
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
            count += 1
    return count

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
    recording_id = payload.get("recording_id")
    title = payload.get("meeting_title") or payload.get("title", "Untitled Meeting")
    meeting_url = payload.get("url", "")
    share_url = payload.get("share_url", "")
    recorded_at = payload.get("recording_start_time")
    summary_data = payload.get("default_summary")
    summary = summary_data.get("markdown_formatted", "") if summary_data else ""
    action_items = payload.get("action_items", [])
    transcript = payload.get("transcript")

    meeting, created = Meeting.objects.update_or_create(
        fathom_recording_id=recording_id,
        defaults={
            "title": title,
            "meeting_url": meeting_url,
            "share_url": share_url,
            "recorded_at": recorded_at,
            "summary": summary,
            "raw_summary": summary_data,
            "raw_action_items": action_items,
            "transcript": transcript,
        },
    )

    return meeting

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
