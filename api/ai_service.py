import requests
import json
import re
import sys
from django.conf import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_INPUT_CHARS = 50000

def generate_tasks_from_summary(transcript_text, meeting_title):
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return None

    model = settings.OPENROUTER_MODEL
    print(f"Calling OpenRouter model={model} input_len={len(transcript_text)}", file=sys.stderr)

    if len(transcript_text) > MAX_INPUT_CHARS:
        transcript_text = transcript_text[:MAX_INPUT_CHARS] + "\n\n[Note: transcript truncated due to length]"

    prompt = f"""You are a precise task extraction assistant. Your job is to extract ONLY explicit action items where someone is clearly assigned to do something in the future.

For each task provide:
- title: concise title (max 100 chars) — GENERATE THIS FROM the description, DO NOT leave it blank or "Untitled"
- description: specific task details quoting what was actually said
- assignee: the person responsible — use their FULL name EXACTLY as it appears in the transcript speaker labels (e.g., "Sekar D", "karan kumar", "Avinesh Duraimanickam", "Praveen G")
- priority: "low", "medium", "high", or "critical"

CRITICAL RULES — FOLLOW THESE WITHOUT EXCEPTION:
1. ONLY create a task when someone is EXPLICITLY told or agrees to do something in the FUTURE. IGNORE past-tense progress updates (e.g., "yesterday I worked on X" is NOT a task).
2. The assignee MUST be the person who WILL DO the work, not the person who assigned it.
3. If someone says "I'll do X" or "I will X", that is a task for that person.
4. If a manager tells someone "please do X", the assignee is the person told to do it.
5. Do NOT create tasks from general discussion, brainstorming, or problem descriptions without a clear "who will do what".
6. Use the speaker name EXACTLY as shown in the transcript (e.g., "Sekar D", "karan kumar", "Avinesh Duraimanickam").
7. NEVER use null for assignee — if no one is clearly assigned, omit that item entirely.
8. Return ONLY a valid JSON array of task objects — no commentary, no markdown.

Meeting: {meeting_title}

Transcript:
{transcript_text}"""

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
                    "temperature": 0.4,
                    "max_tokens": 8192,
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
