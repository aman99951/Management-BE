import os, sys
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()
from api.ai_service import generate_tasks_from_summary
from api.models import Meeting

meeting = Meeting.objects.get(id=9)
transcript_text = ''
if meeting.transcript:
    for entry in meeting.transcript:
        speaker = entry.get('speaker', {}).get('display_name', 'Unknown')
        text = entry.get('text', '')
        transcript_text += f"{speaker}: {text}\n"

print(f'Transcript length: {len(transcript_text)} chars')
print(f'Summary length: {len(meeting.summary)} chars')
print(f'Title: {meeting.title}')
print()

result = generate_tasks_from_summary(transcript_text, meeting.title, meeting.summary)
if result and isinstance(result, list):
    print(f'SUCCESS: Got {len(result)} tasks')
    for t in result[:5]:
        print(f'  - {t.get("title","?")} | assignee={t.get("assignee")} | priority={t.get("priority")}')
    if len(result) > 5:
        print(f'  ... and {len(result)-5} more')
else:
    print(f'FAILED: returned {result}')
