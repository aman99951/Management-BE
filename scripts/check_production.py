"""Check meetings, tasks, and transcripts on RDS."""

import psycopg2
from datetime import datetime, timezone, timedelta

RDS_URL = 'postgresql://postgres:-t%3DT3QxO7Z0%60@database-1.cxq4s0eq6xq3.ap-south-1.rds.amazonaws.com:5432/postgres?sslmode=require'

conn = psycopg2.connect(RDS_URL, connect_timeout=10)
cur = conn.cursor()

# Check meetings
cur.execute('SELECT id, title, recorded_at, summary, raw_summary FROM api_meeting ORDER BY recorded_at DESC')
meetings = cur.fetchall()
print(f'=== MEETINGS ({len(meetings)}) ===')
for m in meetings:
    summary_len = len(m[3]) if m[3] else 0
    raw_len = len(str(m[4])) if m[4] else 0
    print(f'  id={m[0]}, title={m[1][:60]}, recorded_at={m[2]}, summary_len={summary_len}, raw_len={raw_len}')

# Check meetings from today
today = datetime.now(timezone.utc).date()
cur.execute("SELECT id, title, recorded_at, summary, raw_summary, raw_action_items, transcript FROM api_meeting WHERE recorded_at::date = %s ORDER BY recorded_at DESC", (today,))
today_meetings = cur.fetchall()
print(f'\n=== TODAY\'S MEETINGS ({len(today_meetings)}) ===')
for m in today_meetings:
    summary_len = len(m[3]) if m[3] else 0
    raw_summary_len = len(str(m[4])) if m[4] else 0
    raw_actions_len = len(str(m[5])) if m[5] else 0
    transcript_len = len(str(m[6])) if m[6] else 0
    print(f'  id={m[0]}, title={m[1][:60]}')
    print(f'    recorded_at={m[2]}')
    print(f'    summary_len={summary_len}, raw_summary_len={raw_summary_len}, raw_actions_len={raw_actions_len}, transcript_len={transcript_len}')
    if m[6]:
        print(f'    transcript_preview={str(m[6])[:500]}')

# Check tasks assigned to Aman
cur.execute("""
    SELECT t.id, t.title, t.description, t.status, t.priority, t.source, m.title as meeting_title
    FROM api_task t
    LEFT JOIN api_meeting m ON t.meeting_id = m.id
    LEFT JOIN api_employee e ON t.assigned_to_id = e.id
    WHERE e.email = 'aman@mgtechnosolutions.com'
    ORDER BY t.id
""")
tasks = cur.fetchall()
print(f'\n=== TASKS FOR AMAN ({len(tasks)}) ===')
for t in tasks:
    desc_len = len(t[2]) if t[2] else 0
    print(f'  id={t[0]}, title={t[1][:60]}')
    print(f'    status={t[3]}, priority={t[4]}, source={t[5]}, desc_len={desc_len}')
    print(f'    meeting={t[6]}')
    if t[2]:
        print(f'    description={t[2][:300]}')

# Check for duplicate task titles for Aman
cur.execute("""
    SELECT title, COUNT(*) as cnt
    FROM api_task t
    LEFT JOIN api_employee e ON t.assigned_to_id = e.id
    WHERE e.email = 'aman@mgtechnosolutions.com'
    GROUP BY title
    HAVING COUNT(*) > 1
    ORDER BY cnt DESC
""")
dupes = cur.fetchall()
print(f'\n=== DUPLICATE TASK TITLES FOR AMAN ({len(dupes)}) ===')
for d in dupes:
    print(f'  title="{d[0][:80]}" x{d[1]} times')

# Also check by assigned_to name
cur.execute("""
    SELECT t.id, t.title, t.description, e.name
    FROM api_task t
    LEFT JOIN api_employee e ON t.assigned_to_id = e.id
    WHERE e.name ILIKE '%aman%'
    ORDER BY t.id
""")
tasks_by_name = cur.fetchall()
print(f'\n=== TASKS WHERE ASSIGNEE NAME CONTAINS "AMAN" ({len(tasks_by_name)}) ===')
for t in tasks_by_name:
    desc_len = len(t[2]) if t[2] else 0
    print(f'  id={t[0]}, title={t[1][:60]}, name={t[3]}, desc_len={desc_len}')

cur.close()
conn.close()
