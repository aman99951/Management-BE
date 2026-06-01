import requests
import json
import re
import sys
from django.conf import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_INPUT_CHARS = 8000

def generate_tasks_from_summary(summary_text, meeting_title):
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return None

    model = settings.OPENROUTER_MODEL
    print(f"Calling OpenRouter model={model} input_len={len(summary_text)}", file=sys.stderr)

    if len(summary_text) > MAX_INPUT_CHARS:
        summary_text = summary_text[:MAX_INPUT_CHARS] + "\n\n[Note: transcript truncated due to length]"

    prompt = f"""You are a task extraction assistant. Extract ALL action items and tasks for EVERY person mentioned in this meeting transcript. For each task determine:
- title: a concise title (max 100 chars)
- description: the full task details
- assignee: the person responsible (full name exactly as written, or null if unclear)
- priority: one of "low", "medium", "high", "critical"

Rules:
- Create ONE task per UNIQUE action item. If the same action item or task is mentioned multiple times (duplicate meaning), combine them into ONE task.
- If a person has multiple genuinely different action items, create a separate task for EACH distinct one.
- Do NOT create duplicate tasks with the same or near-identical meaning — detect and merge duplicates.
- Every distinct action item MUST be captured, but duplicates should be consolidated.
- Do NOT skip anyone or any action item. If someone's name appears with an action item, include them.
- Return a JSON array of task objects.
- Return ONLY the JSON array, no other text.

Meeting: {meeting_title}

Transcript:
{summary_text}"""

    import time
    for attempt in range(2):
        try:
            resp = requests.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:5173",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 2048,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"OpenRouter attempt {attempt+1} failed: {resp.status_code} {resp.text[:500]}", file=sys.stderr)
                if attempt < 1:
                    time.sleep(2)
                continue
            try:
                content = resp.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                print(f"OpenRouter attempt {attempt+1} parse error: {e} body={resp.text[:500]}", file=sys.stderr)
                if attempt < 1:
                    time.sleep(2)
                continue
            if not content:
                print(f"OpenRouter attempt {attempt+1} returned empty content", file=sys.stderr)
                if attempt < 1:
                    time.sleep(2)
                continue
            result = _parse_json_response(content)
            if result:
                return result
            print(f"OpenRouter attempt {attempt+1}: could not parse JSON from content: {content[:500]}", file=sys.stderr)
            if attempt < 1:
                time.sleep(2)
        except requests.RequestException as e:
            print(f"OpenRouter attempt {attempt+1} request exception: {e}", file=sys.stderr)
            if attempt < 1:
                time.sleep(2)

    return None


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
