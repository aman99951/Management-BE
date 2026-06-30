import requests
import json
import re
import sys
from django.conf import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_INPUT_CHARS = 30000
CHUNK_SIZE = 10000  # chars per chunk for transcript processing

NAME_MAP_PROMPT = """
Employee name mapping (use these ALWAYS):
- "Praveen" or "Praveen G" -> "Praveen GM"
- "Sekar" or "Sekar D" -> "Sekar"
- "Karan" or "karan kumar" -> "Karan Kumar"
- "Avinesh" -> "Avinesh Duraimanickam"
- "Aman" or "Aman Kumar" -> "Aman Kumar"
- "Gajendran" or "MG" or "sir" -> "Gajendran Mani"
"""

def generate_tasks_from_summary(transcript_text, meeting_title):
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return None

    model = settings.OPENROUTER_MODEL
    print(f"Calling OpenRouter model={model} input_len={len(transcript_text)}", file=sys.stderr)

    # Split into header (Meeting Title + Transcript:) and body (entries + optional NOTE)
    header = ""
    body = transcript_text
    transcript_marker = "Transcript:\n"
    if transcript_marker in transcript_text:
        parts = transcript_text.split(transcript_marker, 1)
        header = parts[0] + transcript_marker
        body = parts[1]

    # Separate NOTE section (existing Fathom tasks) — append to every chunk
    note_section = ""
    note_marker = "\n\nNOTE - "
    if note_marker in body:
        body_parts = body.split(note_marker, 1)
        body = body_parts[0]
        note_section = note_marker + body_parts[1]

    # Split body into entries (lines), then chunk at entry boundaries
    lines = body.split('\n')
    chunks = []
    current = []
    current_size = 0
    for line in lines:
        line_size = len(line) + 1
        if current_size + line_size > CHUNK_SIZE and current:
            chunks.append('\n'.join(current))
            current = [line]
            current_size = line_size
        else:
            current.append(line)
            current_size += line_size
    if current:
        chunks.append('\n'.join(current))

    if not chunks:
        return []

    base_prompt = f"""You extract action items from meeting transcripts.{NAME_MAP_PROMPT}
Rules:
- ONLY extract when someone commits to doing something (I will/I'll/I'm going to/I need to/I plan to/I'll call/I'll check/I'll follow up/I'll share/I'm working on)
- Or when someone is assigned work (Can you/Please/Could you + acknowledgment/agreement)
- NEVER invent or guess tasks — if there is no clear action item, skip it entirely
- Each task MUST have: title, description, assignee, priority
- Use the name mapping above to standardize all employee names
- Return ONLY a valid JSON array — no commentary, no markdown

Meeting: {meeting_title}
"""

    all_tasks = []
    import time

    for i, chunk in enumerate(chunks):
        chunk_prompt = base_prompt + f"\nTranscript (part {i+1} of {len(chunks)}):\n{chunk}"
        if note_section:
            chunk_prompt += f"\n{note_section}"

        print(f"  Chunk {i+1}/{len(chunks)} ({len(chunk)} chars)", file=sys.stderr)

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
                        "messages": [{"role": "user", "content": chunk_prompt}],
                        "temperature": 0.0,
                        "max_tokens": 4096,
                    },
                    timeout=60,
                )
                if resp.status_code != 200:
                    print(f"  Chunk {i+1} attempt {attempt+1} failed: {resp.status_code} {resp.text[:300]}", file=sys.stderr)
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                    continue
                content = resp.json()["choices"][0]["message"]["content"]
                result = _parse_json_response(content)
                if result and isinstance(result, list):
                    all_tasks.extend(result)
                    print(f"  Chunk {i+1}: {len(result)} tasks", file=sys.stderr)
                    break
                if attempt < 2:
                    time.sleep(2 ** attempt)
            except requests.RequestException as e:
                print(f"  Chunk {i+1} exception: {e}", file=sys.stderr)
                if attempt < 2:
                    time.sleep(2 ** attempt)

    if not all_tasks:
        return []

    # Deduplicate by title similarity across chunks
    seen_titles = set()
    unique = []
    for t in all_tasks:
        title = t.get('title', '').lower().strip()
        if not title:
            continue
        is_dup = False
        for seen in seen_titles:
            if len(title) > 5 and len(seen) > 5 and (title in seen or seen in title):
                is_dup = True
                break
        if not is_dup:
            seen_titles.add(title)
            unique.append(t)

    print(f"Total: {len(all_tasks)} raw -> {len(unique)} unique", file=sys.stderr)
    return unique


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
    Uses chunking for long transcripts to avoid truncation.
    """
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return []

    model = settings.OPENROUTER_MODEL

    # Chunk long meeting texts
    if len(meeting_text) > CHUNK_SIZE:
        lines = meeting_text.split('\n')
        chunks = []
        current = []
        current_size = 0
        for line in lines:
            line_size = len(line) + 1
            if current_size + line_size > CHUNK_SIZE and current:
                chunks.append('\n'.join(current))
                current = [line]
                current_size = line_size
            else:
                current.append(line)
                current_size += line_size
        if current:
            chunks.append('\n'.join(current))
    else:
        chunks = [meeting_text]

    base_prompt = """You are a product enhancement analyst. Analyze the following meeting conversation and extract structured backlog items (feature suggestions, improvements, etc.).

Rules — STRICTLY follow these:
- ONLY extract when the meeting discussion clearly describes a SPECIFIC problem AND a concrete proposed solution or feature.
- The discussion must contain both: (1) a clear pain point or unmet need, AND (2) a specific proposed enhancement or fix (not just vague acknowledgment).
- Simple status updates, casual mentions, or discussions where no clear solution was proposed must be SKIPPED.
- Never invent, assume, or hallucinate details. If the transcript doesn't explicitly describe a problem+solution pair, do NOT create a backlog item.
- Each item must represent a single, unique, actionable idea — no merging unrelated topics.
- When unsure, SKIP. It is better to miss a marginal item than to pollute the backlog with noise.

For each valid backlog item, capture:
1. title: A concise, descriptive title (max 120 chars)
2. background: The specific problem statement / context
3. proposed_enhancement: The concrete proposed solution or improvement discussed
4. expected_benefits: What benefit was explicitly mentioned or clearly implied
5. stakeholders: Who is affected (choose from: Customer, Provider, Seller, Admin, Telecaller, Platform, or a combination like "Customer, Admin")
6. priority: "Low", "Medium", "High", or "Critical"
7. source_of_idea: Where this idea came from (choose from: "Meeting discussion", "Customer feedback", "Provider feedback", "Internal suggestion")
8. status: "Future Consideration"

Return ONLY a valid JSON array of objects with the keys listed above. If no valid backlog items are found, return an empty array [].
"""

    all_items = []
    import time

    for i, chunk in enumerate(chunks):
        prompt = base_prompt + f"\nMeeting Title: {meeting_title}\n\nMeeting Content (part {i+1} of {len(chunks)}):\n{chunk}"

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
                        "temperature": 0.0,
                        "max_tokens": 2048,
                    },
                    timeout=30,
                )
                if resp.status_code != 200:
                    print(f"enhancements chunk {i+1} attempt {attempt+1} failed: {resp.status_code}", file=sys.stderr)
                    if attempt < 1:
                        time.sleep(2)
                    continue
                content = resp.json()["choices"][0]["message"]["content"]
                result = _parse_json_response(content)
                if result and isinstance(result, list):
                    for item in result:
                        if isinstance(item, dict) and item.get('title') and item.get('background'):
                            all_items.append(item)
                    break
                if attempt < 1:
                    time.sleep(2)
            except Exception as e:
                print(f"enhancements chunk {i+1} error: {e}", file=sys.stderr)
                if attempt < 1:
                    time.sleep(2)

    # Deduplicate by title similarity across chunks
    seen_titles = set()
    unique = []
    for item in all_items:
        title = item.get('title', '').lower().strip()
        if not title:
            continue
        is_dup = False
        for seen in seen_titles:
            if len(title) > 5 and len(seen) > 5 and (title in seen or seen in title):
                is_dup = True
                break
        if not is_dup:
            seen_titles.add(title)
            unique.append(item)

    return unique


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
