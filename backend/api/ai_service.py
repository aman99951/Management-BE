import requests
import json
import re
from django.conf import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

def generate_tasks_from_summary(summary_text, meeting_title):
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        return None

    prompt = f"""You are a task extraction assistant. Extract ALL action items and tasks for EVERY person mentioned in this meeting transcript. For each task determine:
- title: a concise title (max 100 chars)
- description: the full task details
- assignee: the person responsible (full name exactly as written, or null if unclear)
- priority: one of "low", "medium", "high", "critical"

Rules:
- Create one task per person. If a person has multiple action items, combine them into ONE task with all items in the description.
- Every person who receives a task or action item MUST get their own task entry.
- Do NOT skip anyone. If someone's name appears with an action item, include them.
- Return a JSON array of task objects.
- Return ONLY the JSON array, no other text.

Meeting: {meeting_title}

Transcript:
{summary_text}"""

    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:5173",
            },
            json={
                "model": settings.OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 4096,
            },
            timeout=180,
        )
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, json.JSONDecodeError):
        return None

    if not content:
        return None

    return _parse_json_response(content)


def _parse_json_response(content):
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None
