import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django
django.setup()

from django.db.models import Count
from api.models import Meeting

print("=== MEETINGS WITH TRANSCRIPT BUT NO TASKS ===")
found = False
for m in Meeting.objects.filter(transcript__isnull=False).exclude(transcript=[]).annotate(tcount=Count('tasks')).filter(tcount=0):
    found = True
    fathom = bool(m.raw_action_items)
    print(f"  ID={m.id}: {m.title} ({m.recorded_at}) - transcript={len(m.transcript)} entries, fathom_items={len(m.raw_action_items) if fathom else 0}")

if not found:
    print("  (none)")

print("\n=== ALL MEETINGS SUMMARY ===")
for m in Meeting.objects.all().order_by('-recorded_at'):
    tc = m.tasks.count()
    has_t = bool(m.transcript)
    has_f = bool(m.raw_action_items)
    print(f"  ID={m.id}: {m.title} | recorded={m.recorded_at} | transcript={'Y' if has_t else 'N'} | fathom_items={len(m.raw_action_items) if has_f else 0} | tasks={tc} (f={m.tasks.filter(source='fathom').count()} ai={m.tasks.filter(source='ai').count()})")
