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

    prompt = f"""You are a meticulous task extraction assistant. Extract EVERY single action item and task for EVERY person in this transcript. Leave NOTHING out.

For each task provide:
- title: concise title (max 100 chars)
- description: full task details with context
- assignee: the person responsible — use their name EXACTLY as spoken in the transcript
- priority: "low", "medium", "high", or "critical"

ABSOLUTE RULES — FOLLOW THESE WITHOUT EXCEPTION:
1. Scan the ENTIRE transcript line by line. Every time someone is told to do something, that is a task.
2. Capture tasks EVEN if they seem small, obvious, or were already implied.
3. Pay close attention when the boss or manager assigns work — that person is the assignee.
4. If the same person has multiple tasks, create a SEPARATE task for EACH one.
5. Only merge two tasks if they are WORD-FOR-WORD identical in meaning.
6. Do NOT skip anyone. If their name appears with a responsibility, include them.
7. When unsure about assignee, use null rather than omit the task.
8. Include tasks from quick asides, follow-ups, and assumed handoffs.
9. Return ONLY a valid JSON array of task objects — no commentary.

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
