import requests
import json
import re
import sys
from django.conf import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_INPUT_CHARS = 15000

def generate_tasks_from_summary(transcript_text, meeting_title):
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return None

    model = settings.OPENROUTER_MODEL
    print(f"Calling OpenRouter model={model} input_len={len(transcript_text)}", file=sys.stderr)

    if len(transcript_text) > MAX_INPUT_CHARS:
        transcript_text = transcript_text[:MAX_INPUT_CHARS] + "\n\n[Note: transcript truncated due to length]"

    prompt = f"""You are a precise and THOROUGH task extraction assistant. Extract EVERY explicit action item where someone is assigned to do something in the future — do not miss any assignee.

For each task provide:
- title: concise title (max 100 chars) — GENERATE THIS FROM the description, DO NOT leave it blank or "Untitled"
- description: detailed summary of what exactly needs to be done — include ALL specific requirements, features, deadlines, integrations, or action points the assigner (Sekar, Mani Gajendran, or anyone) mentioned. Write in clear English, but capture every concrete detail from the discussion. Do NOT be generic; be as specific as the transcript is.
- assignee: the person responsible — use their FULL name EXACTLY as it appears in the transcript speaker labels (e.g., "Sekar", "Aman Kumar", "karan kumar", "Avinesh Duraimanickam", "Praveen G")
- priority: "low", "medium", "high", or "critical"

CRITICAL RULES — FOLLOW THESE WITHOUT EXCEPTION:
1. ONLY create a task when someone is EXPLICITLY told or agrees to do something in the FUTURE. IGNORE past-tense progress updates (e.g., "yesterday I worked on X" is NOT a task).
2. The assignee MUST be the person who WILL DO the work, not the person who assigned it.
3. If someone says "I'll do X" or "I will X", that is a task for that person.
4. If a manager tells someone "please do X" or tells the group "X will handle this", the assignee is the person told to do it (or named as the doer).
5. Sekar and Mani Gajendran are the managers/owners who delegate work. When they say "Praveen, do X" or "Karan, please handle Y", assignee is Praveen/Karan, NOT Sekar/Mani. Only assign a task to Sekar or Mani if they explicitly say "I will do it myself".
6. Do NOT create tasks from general discussion, brainstorming, or problem descriptions without a clear "who will do what".
7. Use the speaker name EXACTLY as shown in the transcript (e.g., "Sekar", "Aman Kumar", "karan kumar", "Avinesh Duraimanickam", "Praveen G"). DO NOT modify or add extra words to names.
8. NEVER use null for assignee — if no one is clearly assigned, omit that item entirely.
9. Return ONLY a valid JSON array of task objects — no commentary, no markdown.
10. Be THOROUGH — scan the ENTIRE transcript and capture EVERY person who is assigned work, including Sekar, Aman, Karan, Praveen, Avinesh, and anyone else. Do not skip anyone.

If a NOTE section lists already-captured tasks, DO NOT create duplicates of them.

Meeting: {meeting_title}

Transcript:
{transcript_text}"""

    import time
    MAX_ATTEMPTS = 3
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
                    "temperature": 0.1,
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


def enrich_fathom_task_descriptions(transcript_text, meeting_title, fathom_tasks):
    """Given Fathom action items and the full transcript, enrich each task's
    description with relevant context from the transcript. Returns a list of
    dicts with 'id' and 'enriched_description', or None on failure."""
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        return None

    model = settings.OPENROUTER_MODEL
    if len(transcript_text) > MAX_INPUT_CHARS:
        transcript_text = transcript_text[:MAX_INPUT_CHARS] + "\n\n[Note: transcript truncated due to length]"

    tasks_block = '\n'.join(
        f"{i+1}. Title: {t.title}\n   Current description: {t.description}"
        for i, t in enumerate(fathom_tasks)
    )

    prompt = f"""You are a task description enhancer. You are given action items that were captured during a meeting (via Fathom), and the full meeting transcript.

For each action item:
1. Find the relevant discussion in the transcript where this task was discussed
2. Expand the description with specific details, requirements, context, and deadlines mentioned in the transcript
3. Keep the original meaning — just make it more detailed and specific
4. If the transcript has no additional context for a task, leave the description as-is

CRITICAL: Return ONLY a valid JSON array of objects with keys "id" (the number from the list above) and "enriched_description" (the expanded description). No commentary, no markdown.

Meeting: {meeting_title}

Action Items:
{tasks_block}

Transcript:
{transcript_text}"""

    import time
    MAX_ATTEMPTS = 2
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
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"enrich_fathom attempt {attempt+1} failed: {resp.status_code}", file=sys.stderr)
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(2 ** attempt)
                continue
            content = resp.json()["choices"][0]["message"]["content"]
            result = _parse_json_response(content)
            if result and isinstance(result, list) and len(result) > 0:
                return result
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
        except Exception as e:
            print(f"enrich_fathom attempt {attempt+1} error: {e}", file=sys.stderr)
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(2 ** attempt)

    return None


def analyze_meeting_for_enhancements(meeting_text, meeting_title):
    """
    Analyze a full meeting transcript/summary to extract structured product enhancement ideas,
    feature suggestions, process improvements, and other backlog-worthy items.
    Returns a list of dicts with: title, background, proposed_enhancement, expected_benefits,
    stakeholders, priority, source_of_idea, status.
    """
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return []

    model = settings.OPENROUTER_MODEL

    if len(meeting_text) > MAX_INPUT_CHARS:
        meeting_text = meeting_text[:MAX_INPUT_CHARS] + "\n\n[Note: content truncated due to length]"

    prompt = f"""You are a product enhancement analyst. Analyze the following meeting conversation and identify any future enhancement ideas, product improvements, workflow changes, new feature suggestions, category expansions, process optimizations, or user/provider feedback that may lead to a future implementation.

Create a backlog item ONLY if the discussion includes:
• A problem, pain point, limitation, or unmet need.
• A proposed solution, feature, or improvement.
• Suggestions for new categories, services, workflows, integrations, or operational enhancements.
• Customer, provider, telecaller, or admin feedback that indicates a recurring issue or opportunity.
• Ideas that are not part of the current sprint but could be considered in future releases.

For each backlog item, capture:
1. title: A concise, descriptive title (max 120 chars)
2. background: The problem statement / context behind this idea
3. proposed_enhancement: What the proposed solution or improvement is
4. expected_benefits: What business impact or benefit this would bring
5. stakeholders: Who is affected (choose from: Customer, Provider, Seller, Admin, Telecaller, Platform, or a combination like "Customer, Admin")
6. priority: "Low", "Medium", "High", or "Critical"
7. source_of_idea: Where this idea came from (choose from: "Meeting discussion", "Customer feedback", "Provider feedback", "Internal suggestion")
8. status: "Future Consideration"

Do NOT capture:
• Bug fixes already assigned to the current sprint.
• Status updates without enhancement suggestions.
• Duplicate ideas already recorded.
• Implementation details unless specifically discussed.

Return ONLY a valid JSON array of objects with the keys listed above. If no valid backlog items are found, return an empty array [].

Meeting Title: {meeting_title}

Meeting Content:
{meeting_text}
"""

    import time
    MAX_ATTEMPTS = 2
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
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"analyze_meeting_for_enhancements attempt {attempt+1} failed: {resp.status_code} {resp.text[:300]}", file=sys.stderr)
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(2 ** attempt)
                continue
            content = resp.json()["choices"][0]["message"]["content"]
            result = _parse_json_response(content)
            if result and isinstance(result, list):
                # Validate each item has the required fields
                validated = []
                for item in result:
                    if isinstance(item, dict) and item.get('title') and item.get('background'):
                        validated.append(item)
                if validated:
                    return validated
            print(f"analyze_meeting_for_enhancements attempt {attempt+1}: could not parse valid result from: {content[:300]}", file=sys.stderr)
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
        except Exception as e:
            print(f"analyze_meeting_for_enhancements attempt {attempt+1} error: {e}", file=sys.stderr)
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(2 ** attempt)

    return []


def generate_backlog_from_prompt(user_prompt):
    """
    Use AI to generate a well-structured backlog item from a user's free-form prompt.
    Returns a dict with 'description', 'priority', 'status', or None.
    """
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return None

    model = settings.OPENROUTER_MODEL

    prompt = f"""You are a backlog item generator. Given a user's prompt, generate a clear, structured backlog item.

Rules:
- Extract a concise but detailed description of what needs to be done.
- Assign a priority: "Low", "Medium", "High", or "Critical".
- Return ONLY valid JSON with keys: "description", "priority".
- Do not include any commentary or markdown outside the JSON.

User prompt:
{user_prompt}
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
                    "temperature": 0.3,
                    "max_tokens": 1000,
                },
                timeout=20,
            )
            if resp.status_code != 200:
                print(f"generate_backlog_from_prompt attempt {attempt+1} failed: {resp.status_code} {resp.text[:300]}", file=sys.stderr)
                if attempt < 2:
                    time.sleep(2 ** attempt)
                continue
            content = resp.json()["choices"][0]["message"]["content"]
            result = _parse_json_response(content)
            if result and isinstance(result, dict) and result.get("description"):
                return {
                    "description": result["description"].strip(),
                    "priority": result.get("priority", "Medium"),
                }
            print(f"generate_backlog_from_prompt attempt {attempt+1}: could not parse valid result from: {content[:300]}", file=sys.stderr)
            if attempt < 2:
                time.sleep(2 ** attempt)
        except Exception as e:
            print(f"generate_backlog_from_prompt attempt {attempt+1} error: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(2 ** attempt)

    return None


def _parse_json_response(content):
    if not content:
        return None
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
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
