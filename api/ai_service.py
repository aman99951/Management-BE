import requests
import json
import re
import sys
from django.conf import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_INPUT_CHARS = 30000

def generate_tasks_from_summary(transcript_text, meeting_title):
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return None

    model = settings.OPENROUTER_MODEL
    print(f"Calling OpenRouter model={model} input_len={len(transcript_text)}", file=sys.stderr)

    if len(transcript_text) > MAX_INPUT_CHARS:
        transcript_text = transcript_text[:MAX_INPUT_CHARS] + "\n\n[Note: transcript truncated due to length]"

    prompt = f"""You are a precise and THOROUGH task extraction assistant. Extract EVERY action item where someone is expected to do something in the future — do not miss any person.

For each task provide:
- title: concise title (max 100 chars) — GENERATE THIS FROM the description, DO NOT leave it blank or "Untitled"
- description: detailed summary of what exactly needs to be done — include ALL specific requirements, features, deadlines, integrations, or action points mentioned
- assignee: name of the person responsible — this is MANDATORY, NEVER leave it empty. Use the person's name exactly as it appears in the conversation when someone is addressed (e.g., if someone says "Praveen, can you X", the assignee is "Praveen G" if that's the speaker label, or "Praveen" if that's how they're addressed)
- priority: "low", "medium", "high", or "critical"

CRITICAL RULES FOR ASSIGNEE EXTRACTION:
- When someone is ADDRESSED BY NAME in a sentence (e.g., "Praveen, can you change the timing" or "Karan, did you ask these guys"), the person being addressed IS the assignee.
- When the SPEAKER says they will do something ("I'll X", "I'm going to X", "I need to X"), the SPEAKER is the assignee.
- When someone is REFERRED TO as doing something ("he'll do X", "X will handle Y"), the person referred to is the assignee.
- If a person says "I shared X with Y" or "I gave X to Y", then Y is the assignee (task transfer).
- The assignee name should MATCH one of these known team members: Sekar D, Aman Kumar, karan kumar, Avinesh Duraimanickam, Praveen G, Gajendran Mani, Sekar.
- If the name used in conversation is a shorter version (e.g., "Praveen" instead of "Praveen G"), still use that shorter version as the assignee.
- The assignee field is REQUIRED for every task. DO NOT omit it.

DEFINITION OF A TASK (create a task for EACH of these patterns):
1. "I will X" / "I'll X" / "I need to X" / "I have to X" / "I'm going to X" / "I'll call X" / "I'll check X" = task for that speaker.
2. "Please do X" / "Can you X?" / "Could you X?" / "X, please handle Y" directed at someone = task for the person addressed.
3. "He'll do X" / "She'll handle X" / "X will take care of Y" / "X will work on Y" / "X will fix it" spoken about someone = task for X.
4. TASK TRANSFERS: When someone says "I shared X with Y, Y will do it" or "I sent X to Y, Y will handle it" or "I've given X to Y, he'll work on it" — the task belongs to Y, NOT the speaker. The receiver (Y) is the assignee.
5. "Let me check" / "Let me look into it" / "Let me investigate" / "I'll check and come back" = task for the SPEAKER who says this, not the person they are talking to.
6. "We need to X" with a specific person named as responsible = task for that person.
7. Ongoing work mentioned in context of continuing today/tomorrow/this week = task (e.g., "I'm continuing X today").
8. TIME-BOUND COMMITMENTS: When person A asks "Will you be ready by X?" and person B answers "Yes" or "By X date" — task for person B.
9. FOLLOW-UP CALLS: "I'll call customers/providers/them" / "I'll follow up with X" = task for the speaker who says they will call.

IGNORE only pure past-tense updates with no future intent (e.g., "yesterday I did X" with no follow-up).

Be THOROUGH — scan the ENTIRE transcript. Extract tasks for EVERY employee who is assigned work. Include Sekar, Aman, Karan, Praveen, Avinesh, and anyone else.

CRITICAL: Create a SEPARATE task entry for EACH distinct action item. Do NOT merge or combine different action items into one task — even if they belong to the same person. Each action item gets its own task with its own title and description.

If someone's statement is ambiguous about who does the work, omit that item.

Return ONLY a valid JSON array — no commentary.

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
                    "temperature": 0.2,
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

    prompt = f"""You are a product enhancement analyst. Analyze the following meeting conversation and identify ANY future enhancement ideas, product improvements, workflow changes, new feature suggestions, category expansions, process optimizations, or user/provider feedback.

Capture ANY discussion that includes:
• A problem, pain point, limitation, or unmet need.
• A proposed solution, feature, or improvement.
• Suggestions for new categories, services, workflows, integrations, or operational enhancements.
• Customer, provider, telecaller, or admin feedback that indicates a recurring issue or opportunity.
• A new idea that could be implemented as a future project — even if it's also being worked on now.
• Implementation details, technical discussions, or how-to conversations — these indicate real feature work.
• Any feature, enhancement, or improvement that was discussed beyond a simple status update.

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
• Simple status updates that contain no suggestion or enhancement.
• Duplicate ideas already recorded in the transcript (capture each unique idea only once).

When in doubt, INCLUDE the item. It's better to over-capture and let the team review than to miss a valuable idea.

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
