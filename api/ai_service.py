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
- description: detailed summary of what exactly needs to be done — include ALL specific requirements, features, deadlines, integrations, or action points the assigner (Sekar, Mani Gajendran, or anyone) mentioned. Write in clear English, but capture every concrete detail from the discussion. Do NOT be generic; be as specific as the transcript is.
- assignee: the person responsible — use their FULL name EXACTLY as it appears in the transcript speaker labels (e.g., "Sekar D", "karan kumar", "Avinesh Duraimanickam", "Praveen G")
- priority: "low", "medium", "high", or "critical"

CRITICAL RULES — FOLLOW THESE WITHOUT EXCEPTION:
1. ONLY create a task when someone is EXPLICITLY told or agrees to do something in the FUTURE. IGNORE past-tense progress updates (e.g., "yesterday I worked on X" is NOT a task).
2. The assignee MUST be the person who WILL DO the work, not the person who assigned it.
3. If someone says "I'll do X" or "I will X", that is a task for that person.
4. If a manager tells someone "please do X", the assignee is the person told to do it.
5. Sekar and Mani Gajendran are the managers/owners who delegate work. When they say "Praveen, do X" or "Karan, please handle Y", assignee is Praveen/Karan, NOT Sekar/Mani. Only assign a task to Sekar or Mani if they explicitly say "I will do it myself".
6. Do NOT create tasks from general discussion, brainstorming, or problem descriptions without a clear "who will do what".
7. Use the speaker name EXACTLY as shown in the transcript (e.g., "Sekar D", "karan kumar", "Avinesh Duraimanickam").
8. NEVER use null for assignee — if no one is clearly assigned, omit that item entirely.
9. Return ONLY a valid JSON array of task objects — no commentary, no markdown.

Meeting: {meeting_title}

Transcript:
{transcript_text}"""

    import time
    MAX_ATTEMPTS = 5
    for attempt in range(MAX_ATTEMPTS):
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
                print(f"OpenRouter attempt {attempt+1}/{MAX_ATTEMPTS} failed: {resp.status_code} {resp.text[:500]}", file=sys.stderr)
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(2 ** attempt)
                continue
            try:
                content = resp.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                print(f"OpenRouter attempt {attempt+1}/{MAX_ATTEMPTS} parse error: {e} body={resp.text[:500]}", file=sys.stderr)
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(2 ** attempt)
                continue
            if not content:
                print(f"OpenRouter attempt {attempt+1}/{MAX_ATTEMPTS} returned empty content", file=sys.stderr)
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(2 ** attempt)
                continue
            result = _parse_json_response(content)
            if result:
                return result
            print(f"OpenRouter attempt {attempt+1}/{MAX_ATTEMPTS}: could not parse JSON from content: {content[:500]}", file=sys.stderr)
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
        except requests.RequestException as e:
            print(f"OpenRouter attempt {attempt+1}/{MAX_ATTEMPTS} request exception: {e}", file=sys.stderr)
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(2 ** attempt)

    return None


def classify_backlog_item(text, source_label):
    """
    Use AI to detect when someone EXPLICITLY instructs to add an item to the backlog
    (e.g., "put this in the backlog", "add this task to the backlog"), OR when the
    text describes a clear actionable item that should be tracked in the backlog.
    Returns a dict with 'is_backlog_item' (bool) and 'description' (str) or None.
    """
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        return None

    model = settings.OPENROUTER_MODEL

    prompt = f"""You are a backlog intent detector. Your job is to identify when someone is GIVING AN INSTRUCTION to add a task or item to the backlog.

Rules:
- Return {{"is_backlog_item": true, "description": "..."}} when:
  1. Someone explicitly says to put/add/move something TO the backlog (e.g., "put this in the backlog", "add this task to the backlog", "let this be in the backlog", "move this to the backlog")
  2. Someone describes a task and says "add it to the backlog" or similar
  3. Someone refers to an existing task and says to add it to the backlog
  4. Someone clearly assigns a new task that they say should go in the backlog

- The "description" MUST capture WHAT needs to be added — extract the specific task, feature, or item being discussed. Write it as a clear backlog item description.

- If someone refers to an EXISTING task by name (e.g., "add the login page task to the backlog"), ALSO return "task_title": "the exact task name they mentioned". This helps us link to the existing task.

- Return {{"is_backlog_item": false}} when:
  1. The word "backlog" is used conversationally (e.g., "check the backlog", "backlog grooming session", "what's in the backlog", "backlog items from last sprint")
  2. A status update on existing backlog items ("I finished the backlog item on X")
  3. General discussion that does not include an instruction to add something new to the backlog
  4. Greetings, chit-chat, or unrelated topics

Source: {source_label}
Text:
{text}
"""

    import time
    for attempt in range(3):
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
                    "max_tokens": 500,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                continue
            content = resp.json()["choices"][0]["message"]["content"]
            result = _parse_json_response(content)
            if result and isinstance(result, dict):
                if result.get("is_backlog_item") and result.get("description"):
                    return {"is_backlog_item": True, "description": result["description"].strip()}
                return {"is_backlog_item": False}
        except Exception as e:
            print(f"classify_backlog_item attempt {attempt+1} error: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(2 ** attempt)

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
