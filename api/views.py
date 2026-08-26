from rest_framework import viewsets, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import api_view, action, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import login, logout as django_logout
from django.contrib.auth.models import User
from django.conf import settings
from django.http import JsonResponse, HttpResponse, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.middleware.csrf import get_token
from django.core.signing import Signer, BadSignature
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import json
import os
import sys
import hashlib
import traceback
from datetime import datetime, timedelta
from django.db.models import Count, Q
from django.db.models.functions import TruncDay
from django.utils import timezone
import requests as http_requests
from .models import Employee, Meeting, Task, FathomConfig, Comment, GoogleCalendarToken, ScheduledMeeting, Notification, BacklogItem, DismissedSuggestion
from .serializers import EmployeeSerializer, MeetingSerializer, TaskSerializer, FathomConfigSerializer, CommentSerializer, GoogleCalendarTokenSerializer, ScheduledMeetingSerializer, NotificationSerializer, BacklogItemSerializer
from .email_service import send_action_items_to_assignees, send_meeting_invitation, send_meeting_created_notification, send_task_assignment_email, send_batch_tasks_email


def _match_employee(assignee_name):
    """Fuzzy-match an assignee name from AI against known employees.
    Mappings:
      'Praveen G', 'Praveen' → 'Praveen GM'
      'Sekar D'             → 'Sekar'
      'karan kumar', 'Karan' → 'Karan Kumar'
      'Avinesh'             → 'Avinesh Duraimanickam'
      'Aman'                → 'Aman Kumar'
      'Gajendran', 'MG', 'sir' → 'Gajendran Mani'
    """
    if not assignee_name:
        return None
    name = assignee_name.strip()
    if not name:
        return None

    # 0. Direct name aliases
    ALIASES = {
        'praveen g': 'Praveen GM',
        'praveen': 'Praveen GM',
        'sekar d': 'Sekar',
        'karan kumar': 'Karan Kumar',
        'karan': 'Karan Kumar',
        'avinesh': 'Avinesh Duraimanickam',
        'aman': 'Aman Kumar',
        'gajendran': 'Gajendran Mani',
        'mg': 'Gajendran Mani',
        'sir': 'Gajendran Mani',
    }
    canonical = ALIASES.get(name.lower())
    if canonical:
        emp = Employee.objects.filter(name__iexact=canonical).first()
        if emp:
            return emp

    # 1. Exact match (case-insensitive)
    emp = Employee.objects.filter(name__iexact=name).first()
    if emp:
        return emp

    # 2. AI name contains employee name as a word
    words = [w for w in name.split() if len(w) > 1]
    if words:
        emp = Employee.objects.filter(name__in=words).first()
        if emp:
            return emp

    # 3. Employee name is contained within AI name
    for emp in Employee.objects.all():
        if emp.name.lower() in name.lower():
            return emp

    # 4. AI name is contained within employee name
    name_lower = name.lower()
    for emp in Employee.objects.all():
        if name_lower in emp.name.lower():
            return emp

    # 5. Any word from AI name matches any word from employee name
    ai_words = set(name.lower().split())
    for emp in Employee.objects.all():
        emp_words = set(emp.name.lower().split())
        if ai_words & emp_words:
            return emp

    return None


def _generate_title_from_description(description):
    """Generate a concise title from the first sentence of a description."""
    if not description:
        return 'Untitled Task'
    # Take first sentence, limit to 100 chars
    first_sentence = description.split('.')[0].strip()
    if len(first_sentence) > 100:
        first_sentence = first_sentence[:97] + '...'
    return first_sentence if first_sentence else 'Untitled Task'


def _create_tasks_from_fathom_action_items(meeting):
    """Create Task objects directly from Fathom's raw_action_items (source='fathom').
    Uses AI classification to route each item as "task", "backlog", or "discard":
      - "task"      → creates a Task (current behavior, source='fathom')
      - "backlog"   → creates a BacklogItem instead (source='auto-capture')
      - "discard"   → skips the item entirely (likely hallucinated)
    Falls back to creating a Task if classification fails.
    """
    if not meeting.raw_action_items:
        return []

    created = []
    meeting_date = meeting.recorded_at or meeting.created_at
    seen_dedup_keys = set()

    # Build transcript text for classifier
    transcript_text = ''
    if meeting.transcript:
        for entry in meeting.transcript:
            speaker = entry.get('speaker', {}).get('display_name', 'Unknown')
            text = entry.get('text', '')
            transcript_text += f"{speaker}: {text}\n"

    # Batch-classify all items
    classifications = {}
    if transcript_text:
        from .ai_service import classify_fathom_action_items
        classifications = classify_fathom_action_items(meeting.raw_action_items, transcript_text)

    for idx, item in enumerate(meeting.raw_action_items):
        description = (item.get('description') or '').strip()
        if not description:
            continue

        assignee_data = item.get('assignee') or {}
        assignee_name = assignee_data.get('name', '') or ''

        dedup_key = (description.lower().strip()[:80], assignee_name.lower().strip())
        if dedup_key in seen_dedup_keys:
            continue
        seen_dedup_keys.add(dedup_key)

        # Determine classification (default to 'task' if classifier fails or misses)
        classification = classifications.get(str(idx), 'task')

        employee = None
        email = assignee_data.get('email')
        if email:
            employee = Employee.objects.filter(email__iexact=email).first()
        if not employee:
            name = assignee_data.get('name', '')
            if name:
                employee = _match_employee(name)

        title = _generate_title_from_description(description)

        if classification == 'discard':
            # Skip entirely — likely hallucinated
            continue

        if classification == 'backlog':
            # Route to BacklogItem instead of Task
            desc_hash = hashlib.md5(description.encode('utf-8')).hexdigest()
            src_ref = f"fathom:{desc_hash}"
            if BacklogItem.objects.filter(source_ref=src_ref).exists():
                continue
            BacklogItem.objects.create(
                description=description,
                priority='Medium',
                status='Future Consideration',
                source='auto-capture',
                source_ref=src_ref,
                meeting_date=meeting_date,
            )
            continue

        # Default: 'task' (or unknown) — create Task
        if Task.objects.filter(meeting=meeting, title__iexact=title, assigned_to=employee).exists():
            continue

        task = Task.objects.create(
            title=title,
            description=description,
            assigned_to=employee,
            meeting=meeting,
            status='pending',
            priority='medium',
            source='fathom',
            created_at=meeting_date,
        )
        created.append(task)

    return created


def _create_tasks_from_ai_list(ai_tasks, meeting, meeting_date, existing_descriptions=None, existing_titles_by_assignee=None):
    """Shared logic to create Task objects from AI response list.
    Handles title fallback, employee matching, and deduplication.
    """
    created_tasks = []
    seen_descriptions = set(existing_descriptions or [])
    seen_title_prefix_global = set()
    seen_title_words_by_assignee = {}

    if existing_titles_by_assignee:
        for ek, prefixes in existing_titles_by_assignee.items():
            seen_title_prefix_global.update(prefixes)

    for t in ai_tasks:
        desc = t.get('description', '')
        if isinstance(desc, list):
            desc = '\n'.join(f'- {item}' for item in desc)

        desc_lower = desc.lower().strip()[:80]
        if desc_lower in seen_descriptions:
            continue
        seen_descriptions.add(desc_lower)

        title = t.get('title', '').strip()
        if not title or title.lower() == 'untitled task' or title.lower() == 'untitled':
            title = _generate_title_from_description(desc)
        title = title[:500]

        assignee_name = t.get('assignee')
        employee = _match_employee(assignee_name) if assignee_name else None

        if Task.objects.filter(meeting=meeting, title__iexact=title, assigned_to=employee).exists():
            continue

        title_lower = title.lower().strip()
        title_prefix = title_lower[:40]

        # Global dedup: same title prefix seen already (regardless of assignee)
        if title_prefix in seen_title_prefix_global:
            continue
        seen_title_prefix_global.add(title_prefix)

        # Word-overlap dedup: same assignee + >50% significant word overlap = duplicate
        emp_key = employee.id if employee else None
        if emp_key is not None:
            words = {w for w in title_lower.split() if len(w) > 3}
            if words and emp_key in seen_title_words_by_assignee:
                is_dup = False
                for existing_words in seen_title_words_by_assignee[emp_key]:
                    overlap = len(words & existing_words)
                    smaller = min(len(words), len(existing_words))
                    if smaller > 0 and overlap / smaller >= 0.5:
                        is_dup = True
                        break
                if is_dup:
                    continue
            seen_title_words_by_assignee.setdefault(emp_key, []).append(words)

        priority = t.get('priority', 'medium')
        if priority not in dict(Task.PRIORITY_CHOICES):
            priority = 'medium'

        new_task = Task.objects.create(
            title=title,
            description=desc,
            assigned_to=employee,
            meeting=meeting,
            status='pending',
            priority=priority,
            source='ai',
            created_at=meeting_date,
        )
        created_tasks.append(new_task)

    return created_tasks


def _notify_task_assignees(tasks):
    """Send a single consolidated email per employee with all their tasks grouped.
    Called automatically after task generation.

    Returns:
        dict with 'sent_count', 'failed_count', and 'details' list.
    """
    return send_batch_tasks_email(tasks)
from .services import sync_meetings, process_webhook_payload, get_config, get_user_fathom_token, fathom_headers, FATHOM_API_BASE, fetch_transcript, fetch_meeting_by_id, get_api_key_list, mask_key, all_fathom_headers, get_api_key_entries, resolve_masked_keys
from .google_calendar import (create_meet_event, list_upcoming_events, sync_calendar_events, get_google_calendar_auth_url, get_google_calendar_credentials, resolve_calendar_state)
from urllib.parse import urlencode

class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer

class MeetingViewSet(viewsets.ModelViewSet):
    queryset = Meeting.objects.all().order_by('-recorded_at', '-created_at')
    serializer_class = MeetingSerializer

    @action(detail=False, methods=['post'])
    def create_with_link(self, request):
        title = request.data.get('title', '')
        meeting_url = request.data.get('meeting_url', '')
        if not meeting_url:
            return Response({'error': 'Meeting URL is required'}, status=400)
        meeting = Meeting.objects.create(
            title=title or 'Untitled Meeting',
            meeting_url=meeting_url,
        )
        return Response(MeetingSerializer(meeting).data, status=201)

    @action(detail=False, methods=['post'])
    def batch_generate_tasks(self, request):
        """Queue AI task generation for ALL meetings.

        Runs in the background worker; poll GET /api/tasks/generation-status/?batch=1.
        """
        from .jobs import enqueue_task_generation
        job, is_new = enqueue_task_generation(batch=True)
        return Response({
            'queued': True,
            'job_id': job.id,
            'new': is_new,
            'status': job.status,
            'message': 'Task generation queued — it runs in the background.',
        })

    @action(detail=True, methods=['post'])
    def check_fathom(self, request, pk=None):
        meeting = self.get_object()
        from .services import find_fathom_recording
        found = find_fathom_recording(meeting)
        if found:
            return Response({'matched': True, 'recording_id': found.recording_id})
        return Response({'matched': False})

    @action(detail=True, methods=['post'])
    def generate_tasks(self, request, pk=None):
        """Queue AI task generation for this meeting.

        The actual (slow, multi-minute) generation runs in the background worker
        (`python manage.py task_worker`) so this request returns immediately.
        Poll `GET /api/tasks/generation-status/?meeting_id=<id>` for the result.
        """
        meeting = self.get_object()
        from .jobs import enqueue_task_generation
        job, is_new = enqueue_task_generation(meeting=meeting, force=True)
        return Response({
            'queued': True,
            'job_id': job.id,
            'new': is_new,
            'status': job.status,
        })

class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all()
    serializer_class = TaskSerializer

    def perform_create(self, serializer):
        serializer.save(source='manual')

    @action(detail=False, methods=['post'])
    def send_action_items(self, request):
        """Send action items emails to assignees.

        Request body:
            priority: Optional — filter by priority ('critical', 'high', 'medium', 'low', 'all')
            status: Optional — filter by status ('pending', 'open' for pending+in_progress)
        """
        priority = request.data.get('priority', 'all')
        status = request.data.get('status', 'pending')

        results = send_action_items_to_assignees(
            priority_filter=priority,
            status_filter=status,
        )

        total_sent = sum(1 for r in results if r['sent'])
        total_failed = sum(1 for r in results if not r['sent'])
        total_tasks = sum(r['task_count'] for r in results)

        return Response({
            'status': 'completed',
            'total_employees_contacted': len(results),
            'total_emails_sent': total_sent,
            'total_emails_failed': total_failed,
            'total_tasks_included': total_tasks,
            'details': results,
        })

    @action(detail=True, methods=['post'])
    def send_assignment_email(self, request, pk=None):
        """Send an assignment notification email for this task."""
        task = self.get_object()
        if not task.assigned_to:
            return Response({'error': 'Task has no assignee'}, status=400)
        sent = send_task_assignment_email(task)
        if sent:
            return Response({'status': 'sent', 'to': task.assigned_to.email, 'task': task.title})
        return Response({'error': 'Failed to send email'}, status=500)

    @action(detail=True, methods=['patch'])
    def status(self, request, pk=None):
        task = self.get_object()
        new_status = request.data.get('status')
        if new_status not in dict(Task.STATUS_CHOICES):
            return Response({'error': 'Invalid status'}, status=400)
        task.status = new_status
        task.save()
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=['get', 'post'])
    def comments(self, request, pk=None):
        task = self.get_object()
        if request.method == 'GET':
            comments = task.comments.all()
            return Response(CommentSerializer(comments, many=True).data)
        serializer = CommentSerializer(data=request.data)
        if serializer.is_valid():
            author = None
            if request.user.is_authenticated:
                email = request.user.email or ''
                name = request.user.get_full_name() or request.user.username
                author, _ = Employee.objects.get_or_create(email=email, defaults={'name': name})
            serializer.save(task=task, author=author)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

class BacklogPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 500

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data,
            'pending_count': BacklogItem.objects.filter(created_task__isnull=True).exclude(status__in=['Done', 'Closed']).count(),
            'converted_count': BacklogItem.objects.filter(created_task__isnull=False).count(),
        })


class BacklogItemViewSet(viewsets.ModelViewSet):
    queryset = BacklogItem.objects.all()
    serializer_class = BacklogItemSerializer
    pagination_class = BacklogPagination

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        search = request.query_params.get('search', '')
        priority = request.query_params.get('priority', '')
        status = request.query_params.get('status', '')
        tab = request.query_params.get('tab', 'all')
        release_week = request.query_params.get('release_week', '')
        date_from = request.query_params.get('date_from', '')
        date_to = request.query_params.get('date_to', '')
        owner = request.query_params.get('owner', '')
        created_from = request.query_params.get('created_from', '')
        created_to = request.query_params.get('created_to', '')

        if search:
            queryset = queryset.filter(description__icontains=search)
        if priority and priority != 'All':
            queryset = queryset.filter(priority=priority)
        if status and status != 'All':
            queryset = queryset.filter(status=status)
        if release_week:
            queryset = queryset.filter(release_week=release_week)
        if date_from:
            queryset = queryset.filter(meeting_date__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(meeting_date__date__lte=date_to)
        if owner:
            queryset = queryset.filter(owner_id=owner)
        if created_from:
            queryset = queryset.filter(created_at__date__gte=created_from)
        if created_to:
            queryset = queryset.filter(created_at__date__lte=created_to)
        if tab == 'pending':
            queryset = queryset.filter(created_task__isnull=True).exclude(status__in=['Done', 'Closed'])
        elif tab == 'converted':
            queryset = queryset.filter(created_task__isnull=False)

        queryset = queryset.order_by('-meeting_date', '-created_at')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def generate_from_prompt(self, request):
        """
        Generate a backlog item from a free-form user prompt using AI.
        Accepts POST body: {"prompt": "..."}
        """
        prompt = request.data.get('prompt', '').strip()
        if not prompt:
            return Response({'error': 'Prompt is required'}, status=400)

        from .ai_service import generate_backlog_from_prompt
        result = generate_backlog_from_prompt(prompt)
        if not result:
            return Response({'error': 'AI generation failed. Check your OpenRouter API key.'}, status=500)

        # Create the backlog item with AI-generated data
        backlog_item = BacklogItem.objects.create(
            description=result['description'],
            priority=result.get('priority', 'Medium'),
            status='New',
            source='manual',
        )
        return Response(BacklogItemSerializer(backlog_item).data, status=201)

    @action(detail=True, methods=['post'])
    def convert_to_task(self, request, pk=None):
        """Convert a backlog item into a Task automatically.
        The task inherits description, priority, and owner from the backlog item.
        """
        backlog_item = self.get_object()

        if backlog_item.created_task:
            return Response({
                'status': 'already_converted',
                'task_id': backlog_item.created_task.id,
                'task': TaskSerializer(backlog_item.created_task).data,
            })

        # Generate a concise title from first line/sentence
        desc = backlog_item.description or ''
        title = desc.split('\n')[0].strip()
        if len(title) > 120:
            title = title[:117] + '...'
        if not title:
            title = 'Untitled Backlog Item'

        priority_map = {
            'Low': 'low',
            'Medium': 'medium',
            'High': 'high',
            'Critical': 'critical',
        }
        priority = priority_map.get(backlog_item.priority, 'medium')

        task = Task.objects.create(
            title=title,
            description=desc,
            assigned_to=backlog_item.owner,
            priority=priority,
            status='pending',
            source='ai',
        )

        backlog_item.created_task = task
        backlog_item.status = 'Reviewed'
        backlog_item.save(update_fields=['created_task', 'status'])

        # Send email notification if assignee exists
        if task.assigned_to:
            from .email_service import send_task_assignment_email
            send_task_assignment_email(task)

        return Response({
            'status': 'converted',
            'task': TaskSerializer(task).data,
            'backlog_item': BacklogItemSerializer(backlog_item).data,
        })

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """Close a backlog item (status → Done). If a task was promoted
        from this backlog item, also close that task (status → completed)."""
        backlog_item = self.get_object()
        backlog_item.status = 'Closed'
        backlog_item.save(update_fields=['status'])

        closed_task = None
        if backlog_item.created_task:
            task = backlog_item.created_task
            if task.status != 'completed':
                task.status = 'completed'
                task.save(update_fields=['status'])
                closed_task = TaskSerializer(task).data

        return Response({
            'status': 'closed',
            'backlog_item': BacklogItemSerializer(backlog_item).data,
            'closed_task': closed_task,
        })

    @action(detail=False, methods=['post'])
    def auto_roll_weeks(self, request):
        """Auto-assign release_week to items missing it.
        Items without release_week get the current ISO week.
        Only affects active items (not Done/Future Consideration)."""
        from datetime import datetime
        now = datetime.now()
        iso_year, iso_week, _ = now.isocalendar()
        current_week = f'W{iso_week}'

        updated = []
        qs = BacklogItem.objects.filter(
            release_week='',
            status__in=['New', 'Reviewed', 'In Progress'],
        )
        for item in qs:
            item.release_week = current_week
            item.save(update_fields=['release_week'])
            updated.append(item.id)

        return Response({'updated_count': len(updated), 'week': current_week})


@api_view(['POST'])
def backlog_scan(request):
    """AI-powered scan: analyze full meeting conversations to extract structured product enhancement ideas.
    Uses content-hash dedup against approved BacklogItems and DismissedSuggestions to avoid duplicates.
    Accepts optional POST body: {"days_back": N} — only scans meetings from last N days (default: 1).
    Uses a time budget to avoid Vercel Hobby 60s timeout — returns partial results if exceeded."""
    import traceback
    import time
    TIME_BUDGET = 50  # seconds — stay under Vercel Hobby 60s hard limit

    try:
        days_back = 1
        try:
            body = json.loads(request.body) if request.body else {}
            days_back = int(body.get('days_back', 1))
        except (json.JSONDecodeError, ValueError, TypeError):
            days_back = 1
        days_back = max(days_back, 0)

        from .ai_service import analyze_meeting_for_enhancements

        since_date = timezone.now() - timedelta(days=days_back) if days_back > 0 else None

        # Collect meetings with transcripts or summaries
        meetings = Meeting.objects.exclude(
            Q(transcript__isnull=True) & Q(summary__exact='')
        )
        if since_date:
            meetings = meetings.filter(created_at__gte=since_date)

        # Pre-load all approved & dismissed hashes for O(1) dedup
        approved_hashes = set(
            BacklogItem.objects.filter(source='auto-capture')
            .exclude(source_ref__exact='')
            .values_list('source_ref', flat=True)
        )
        dismissed_hashes = set(
            DismissedSuggestion.objects.values_list('content_hash', flat=True)
        )

        def _content_hash(meeting_id, title, proposed_enhancement):
            raw = f'{meeting_id}:{title}:{proposed_enhancement}'
            return hashlib.md5(raw.encode()).hexdigest()

        all_enhancements = []
        new_candidates = []
        processed_meetings = 0
        timed_out = False
        start_time = time.time()

        for meeting in meetings:
            if time.time() - start_time >= TIME_BUDGET:
                timed_out = True
                break

            # Build full meeting content
            meeting_text_parts = []
            if meeting.summary:
                meeting_text_parts.append(f"--- AI Summary ---\n{meeting.summary}")
            if meeting.transcript:
                if isinstance(meeting.transcript, str):
                    meeting_text_parts.append(f"--- Transcript ---\n{meeting.transcript}")
                elif isinstance(meeting.transcript, list):
                    transcript_lines = []
                    for chunk in meeting.transcript:
                        if isinstance(chunk, dict):
                            speaker = chunk.get('speaker', {})
                            speaker_name = speaker.get('display_name', 'Unknown') if isinstance(speaker, dict) else 'Unknown'
                            text = chunk.get('text', '') or chunk.get('content', '')
                        elif isinstance(chunk, str):
                            speaker_name = 'Unknown'
                            text = chunk
                        else:
                            continue
                        if text:
                            transcript_lines.append(f"{speaker_name}: {text}")
                    if transcript_lines:
                        meeting_text_parts.append(f"--- Transcript ---\n" + '\n'.join(transcript_lines))

            meeting_text = '\n\n'.join(meeting_text_parts)
            if not meeting_text:
                continue

            # Send to AI
            try:
                enhancements = analyze_meeting_for_enhancements(meeting_text, meeting.title)
            except Exception as e:
                print(f"backlog_scan: AI analysis failed for meeting {meeting.id}: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                continue
            processed_meetings += 1

            for item in enhancements:
                c_hash = _content_hash(meeting.id, item.get('title', ''), item.get('proposed_enhancement', ''))
                item['content_hash'] = c_hash
                item['meeting_id'] = meeting.id
                item['meeting_title'] = meeting.title
                item['meeting_date'] = meeting.recorded_at
                all_enhancements.append(item)

                # Dedup: skip if already approved or dismissed
                if c_hash in approved_hashes or c_hash in dismissed_hashes:
                    continue
                new_candidates.append(item)

            # Mark meeting as scanned
            if not timed_out:
                Meeting.objects.filter(id=meeting.id).update(last_scanned_at=timezone.now())

        # Build response for new candidates only
        response_items = []
        for item in new_candidates:
            md = item.get('meeting_date')
            priority = item.get('priority', 'Medium')
            if priority not in dict(BacklogItem.PRIORITY_CHOICES):
                priority = 'Medium'
            response_items.append({
                'content_hash': item.get('content_hash', ''),
                'title': item.get('title', ''),
                'background': item.get('background', ''),
                'proposed_enhancement': item.get('proposed_enhancement', ''),
                'expected_benefits': item.get('expected_benefits', ''),
                'stakeholders': item.get('stakeholders', ''),
                'priority': priority,
                'source_of_idea': item.get('source_of_idea', ''),
                'meeting_id': item.get('meeting_id'),
                'meeting_title': item.get('meeting_title', ''),
                'meeting_date': md.isoformat() if md else None,
            })

        return Response({
            'items': response_items,
            'total_found': len(all_enhancements),
            'new_count': len(new_candidates),
            'processed_meetings': processed_meetings,
            'timed_out': timed_out,
            'remaining_meetings': meetings.count() - processed_meetings if timed_out else 0,
        })
    except Exception as e:
        print(f"backlog_scan: unexpected error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return Response({
            'error': 'Internal server error during backlog scan',
            'detail': str(e),
        }, status=500)


@api_view(['POST'])
def dismiss_suggestion(request):
    """Dismiss an AI-generated enhancement so it won't reappear on future scans.
    Accepts POST body: {"meeting_id": N, "content_hash": "..."}"""
    try:
        body = json.loads(request.body) if request.body else {}
        meeting_id = body.get('meeting_id')
        content_hash = body.get('content_hash', '').strip()
        if not meeting_id or not content_hash:
            return Response({'error': 'meeting_id and content_hash are required'}, status=400)

        meeting = Meeting.objects.filter(id=meeting_id).first()
        if not meeting:
            return Response({'error': 'Meeting not found'}, status=404)

        DismissedSuggestion.objects.get_or_create(
            meeting=meeting,
            content_hash=content_hash,
        )
        return Response({'status': 'dismissed'})
    except Exception as e:
        return Response({'error': str(e)}, status=500)


def _fathom_uploader_name(request):
    user = request.user
    if user and user.is_authenticated:
        return user.get_full_name() or user.email or user.username
    return 'Unknown'

def _fathom_keys_response(config):
    entries = get_api_key_entries(config)
    return {
        'configured': True,
        'email_notifications_enabled': config.email_notifications_enabled,
        'api_keys': [
            {
                'key': mask_key(e['key']),
                'added_by': e.get('added_by') or '',
                'added_at': e.get('added_at') or '',
            }
            for e in entries
        ],
        'key_count': len(entries),
    }


@api_view(['GET', 'POST'])
@csrf_exempt
def fathom_config_view(request):
    if request.method == 'GET':
        config = get_config()
        if not config:
            return JsonResponse({'configured': False, 'email_notifications_enabled': True, 'api_keys': [], 'key_count': 0})
        return JsonResponse(_fathom_keys_response(config))
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    config = get_config()

    # Multi-account key management: api_keys replaces the list, api_key appends one.
    # Every key is stored as {key, added_by, added_at}; masked keys sent back from the
    # Settings page are mapped to the real stored values.
    if 'api_keys' in data or 'api_key' in data:
        uploader = _fathom_uploader_name(request)
        now_iso = timezone.now().isoformat()
        entries = resolve_masked_keys(data.get('api_keys') or [], get_api_key_entries(config)) if 'api_keys' in data else get_api_key_entries(config)
        for e in entries:
            if not e.get('added_at'):
                e['added_at'] = now_iso
        if 'api_key' in data:
            new_key = str(data.get('api_key') or '').strip()
            if new_key and new_key not in [e['key'] for e in entries]:
                entries.append({'key': new_key, 'added_by': uploader, 'added_at': now_iso})
        if not config:
            config = FathomConfig.objects.create(api_key=entries[0]['key'] if entries else '', api_keys=entries)
        else:
            config.api_keys = entries
            config.api_key = entries[0]['key'] if entries else ('' if 'api_keys' in data else config.api_key)
            if 'webhook_secret' in data:
                config.webhook_secret = str(data.get('webhook_secret') or '')
            if 'email_notifications_enabled' in data:
                config.email_notifications_enabled = bool(data.get('email_notifications_enabled'))
            config.save()
        return JsonResponse(_fathom_keys_response(config))

    # Handle single-field updates (e.g. just toggling email)
    partial_update = 'webhook_secret' not in data
    if config and partial_update:
        for key, val in data.items():
            if hasattr(config, key):
                setattr(config, key, val)
        config.save()
        return JsonResponse({'configured': True, 'email_notifications_enabled': config.email_notifications_enabled})

    serializer = FathomConfigSerializer(data=data)
    if not serializer.is_valid():
        return JsonResponse(serializer.errors, status=400)
    if config:
        for key, val in serializer.validated_data.items():
            setattr(config, key, val)
        config.save()
    else:
        config = FathomConfig.objects.create(**serializer.validated_data)
    return JsonResponse({'configured': True, 'email_notifications_enabled': config.email_notifications_enabled})

def _enrich_fathom_tasks(meeting, fathom_tasks):
    """Enrich Fathom task descriptions with context from the transcript using AI."""
    if not fathom_tasks or not meeting.transcript:
        return

    if not settings.OPENROUTER_API_KEY:
        return

    transcript_text = ''
    for entry in meeting.transcript:
        speaker = entry.get('speaker', {}).get('display_name', 'Unknown')
        text = entry.get('text', '')
        transcript_text += f"{speaker}: {text}\n"

    if not transcript_text:
        return

    from .ai_service import enrich_fathom_task_descriptions
    enriched = enrich_fathom_task_descriptions(transcript_text, meeting.title, fathom_tasks)
    if not enriched:
        return

    id_map = {item['id']: item['enriched_description'] for item in enriched if 'id' in item and 'enriched_description' in item}
    for i, task in enumerate(fathom_tasks):
        idx = i + 1  # 1-based index matching the AI prompt
        enriched_desc = id_map.get(idx)
        if enriched_desc and enriched_desc != task.description:
            task.description = enriched_desc
            task.save(update_fields=['description'])


def _auto_generate_tasks_for_meeting(meeting, deadline=None, progress=None):
    """Auto-generate tasks for a meeting.

    When Fathom raw_action_items exist: creates tasks from them (source='fathom'),
    then enriches descriptions with AI from the transcript. Never creates duplicate
    AI tasks alongside Fathom tasks.

    When no Fathom items but transcript exists: falls back to AI generation (source='ai').

    Skips meetings titled 'Fathom Demo'. If transcript/summary is missing but a
    fathom_recording_id exists, tries to fetch from Fathom's API first.

    Serverless support: when `deadline` (a time.monotonic() deadline) and
    `progress` (the job's per-meeting resume state dict) are provided, work is
    split across multiple sweeps. Completed AI chunk indices are recorded in
    `progress['<meeting_id>']` and a run that hits the deadline returns
    done=False so the job can be re-queued and resumed. All phases are
    idempotent, so a resumed run never duplicates tasks or backlog items.
    """
    import time as _time
    title_lower = (meeting.title or '').lower().strip()
    _empty_result = {'task_count': 0, 'email_status': {'sent_count': 0, 'failed_count': 0, 'details': []}, 'done': True}

    if 'fathom demo' in title_lower:
        return _empty_result

    mp = None
    if progress is not None:
        mp = progress.setdefault(str(meeting.id), {})

    def set_done(key, value):
        if mp is not None:
            mp[key] = value

    def deadline_hit():
        return deadline is not None and _time.monotonic() >= deadline

    # If transcript/summary is missing but we have a fathom_recording_id,
    # try to fetch it from Fathom's API
    if (not meeting.transcript or not meeting.summary) and meeting.fathom_recording_id:
        fetched = fetch_meeting_by_id(meeting.fathom_recording_id)
        if fetched:
            fetched_transcript = fetched.get('transcript')
            if not fetched_transcript:
                tdata = fetch_transcript(meeting.fathom_recording_id)
                if tdata:
                    fetched_transcript = tdata.get('transcript', tdata.get('items', tdata))

            summary_data = fetched.get('default_summary')
            fetched_summary = summary_data.get('markdown_formatted', '') if summary_data else ''
            fetched_raw_summary = summary_data
            fetched_action_items = fetched.get('action_items', meeting.raw_action_items or [])

            update_fields = []
            if not meeting.transcript and fetched_transcript:
                meeting.transcript = fetched_transcript
                update_fields.append('transcript')
            if not meeting.summary and fetched_summary:
                meeting.summary = fetched_summary
                update_fields.append('summary')
            if not meeting.raw_summary and fetched_raw_summary:
                meeting.raw_summary = fetched_raw_summary
                update_fields.append('raw_summary')
            if not meeting.raw_action_items and fetched_action_items:
                meeting.raw_action_items = fetched_action_items
                update_fields.append('raw_action_items')
            if update_fields:
                meeting.save(update_fields=update_fields)

    total_count = 0
    all_email_details = []

    # Phase 1: Create tasks DIRECTLY from Fathom raw_action_items (authoritative)
    fathom_created = []
    if meeting.raw_action_items:
        if mp is not None and mp.get('p1_done'):
            pass
        elif deadline_hit():
            set_done('p1_done', False)
        else:
            existing_fathom_count = Task.objects.filter(meeting=meeting, source='fathom').count()
            if existing_fathom_count == 0:
                fathom_created = _create_tasks_from_fathom_action_items(meeting)
                if fathom_created:
                    total_count += len(fathom_created)
                    result = send_batch_tasks_email(fathom_created)
                    if result.get('details'):
                        all_email_details.extend(result['details'])
            set_done('p1_done', True)

    # Enrichment step: If Fathom tasks were created and we have a transcript,
    # enrich descriptions with AI context instead of creating duplicate AI tasks
    if fathom_created and meeting.transcript and settings.OPENROUTER_API_KEY:
        _enrich_fathom_tasks(meeting, fathom_created)

    # Phase 2: Run AI extraction from transcript to catch tasks Fathom may have missed.
    # Even when Fathom raw_action_items exist, it may have captured only partial tasks.
    # AI finds additional tasks from the transcript, deduplicated against Fathom tasks.
    ai_created = []

    def _run_phase2():
        nonlocal total_count, all_email_details, ai_created
        set_done('p2_started', True)
        if deadline_hit():
            set_done('p2_done', False)
            return
        if not meeting.transcript and not meeting.summary:
            set_done('p2_done', True)
            return

        transcript_text = ''
        if meeting.transcript:
            for entry in meeting.transcript:
                speaker = entry.get('speaker', {}).get('display_name', 'Unknown')
                text = entry.get('text', '')
                transcript_text += f"{speaker}: {text}\n"

        if transcript_text or meeting.summary:
            input_text = f"Meeting Title: {meeting.title}\n\n"
            if transcript_text:
                input_text += f"Transcript:\n{transcript_text}\n"
            elif meeting.summary:
                input_text += f"Summary:\n{meeting.summary}\n"

            # Append already-captured tasks so AI knows not to re-create them
            if fathom_created:
                input_text += "\n\nNOTE - The following tasks were ALREADY CAPTURED from this meeting. DO NOT create duplicates of them:\n"
                for t in fathom_created:
                    aname = t.assigned_to.name if t.assigned_to else 'Unassigned'
                    input_text += f"- {t.title} (assignee: {aname})\n"

            if settings.OPENROUTER_API_KEY:
                from .ai_service import generate_tasks_from_summary
                ai_tasks = generate_tasks_from_summary(input_text, meeting.title, deadline=deadline, progress=mp)
                if ai_tasks and isinstance(ai_tasks, list):
                    meeting_date = meeting.recorded_at or meeting.created_at
                    existing_descriptions = None
                    existing_titles_by_assignee = None
                    if fathom_created:
                        existing_descriptions = set()
                        existing_titles_by_assignee = {}
                        for t in fathom_created:
                            existing_descriptions.add(t.description.lower().strip()[:80])
                            emp_key = t.assigned_to.id if t.assigned_to else None
                            existing_titles_by_assignee.setdefault(emp_key, set()).add(t.title.lower().strip()[:40])
                    ai_created = _create_tasks_from_ai_list(
                        ai_tasks, meeting, meeting_date,
                        existing_descriptions=existing_descriptions,
                        existing_titles_by_assignee=existing_titles_by_assignee,
                    )
                    if ai_created:
                        total_count += len(ai_created)
                        result = send_batch_tasks_email(ai_created)
                        if result.get('details'):
                            all_email_details.extend(result['details'])
            set_done('p2_done', mp.get('p2_done', True) if mp is not None else True)

    if mp is not None:
        if mp.get('p2_done'):
            pass
        elif mp.get('p2_started'):
            _run_phase2()  # resume: only remaining chunks (stored in p2_chunks)
        elif Task.objects.filter(meeting=meeting, source='ai').exists():
            set_done('p2_done', True)  # already generated by a previous completed job
        else:
            _run_phase2()
    else:
        if not Task.objects.filter(meeting=meeting, source='ai').exists():
            _run_phase2()

    # Phase 3: Auto-generate backlog items (enhancement ideas) from the meeting
    backlog_created = 0

    def _run_phase3():
        nonlocal backlog_created
        set_done('p3_started', True)
        if deadline_hit():
            set_done('p3_done', False)
            return
        try:
            transcript_text_p3 = ''
            if isinstance(meeting.transcript, list):
                for entry in meeting.transcript:
                    speaker = entry.get('speaker', {}).get('display_name', 'Unknown') if isinstance(entry, dict) else 'Unknown'
                    text = entry.get('text', '') if isinstance(entry, dict) else str(entry)
                    transcript_text_p3 += f"{speaker}: {text}\n"
            elif isinstance(meeting.transcript, str):
                transcript_text_p3 = meeting.transcript

            if transcript_text_p3:
                meeting_content = transcript_text_p3
                if meeting.summary:
                    meeting_content = f"--- AI Summary ---\n{meeting.summary}\n\n--- Transcript ---\n{transcript_text_p3}"
                from .ai_service import analyze_meeting_for_enhancements
                enhancements = analyze_meeting_for_enhancements(meeting_content, meeting.title, deadline=deadline, progress=mp)
                if enhancements and isinstance(enhancements, list):
                    approved = set(
                        BacklogItem.objects.filter(source='auto-capture')
                        .exclude(source_ref__exact='')
                        .values_list('source_ref', flat=True)
                    )
                    dismissed = set(
                        DismissedSuggestion.objects.values_list('content_hash', flat=True)
                    )
                    m_date = meeting.recorded_at or meeting.created_at
                    for item in enhancements:
                        c_hash = hashlib.md5(
                            f'{meeting.id}:{item.get("title", "")}:{item.get("proposed_enhancement", "")}'.encode()
                        ).hexdigest()
                        if c_hash in approved or c_hash in dismissed:
                            continue
                        desc_parts = []
                        if item.get('title'):
                            desc_parts.append(f'# {item["title"]}')
                        if item.get('background'):
                            desc_parts.append(f'\n**Background / Problem Statement:**\n{item["background"]}')
                        if item.get('proposed_enhancement'):
                            desc_parts.append(f'\n**Proposed Enhancement:**\n{item["proposed_enhancement"]}')
                        if item.get('expected_benefits'):
                            desc_parts.append(f'\n**Expected Benefits:**\n{item["expected_benefits"]}')
                        if item.get('stakeholders'):
                            desc_parts.append(f'\n**Stakeholders:** {item["stakeholders"]}')
                        if item.get('source_of_idea'):
                            desc_parts.append(f'\n**Source:** {item["source_of_idea"]}')
                        if meeting.title:
                            desc_parts.append(f'\n**From Meeting:** {meeting.title}')
                        priority = item.get('priority', 'Medium')
                        if priority not in dict(BacklogItem.PRIORITY_CHOICES):
                            priority = 'Medium'
                        BacklogItem.objects.create(
                            description='\n'.join(desc_parts) or item.get('title', ''),
                            priority=priority,
                            status='Future Consideration',
                            source='auto-capture',
                            source_ref=c_hash,
                            meeting_date=m_date,
                        )
                        backlog_created += 1
            set_done('p3_done', mp.get('p3_done', True) if mp is not None else True)
        except Exception as e:
            print(f"_auto_generate_tasks_for_meeting: backlog generation failed for meeting {meeting.id}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            set_done('p3_done', True)

    if meeting.transcript and settings.OPENROUTER_API_KEY:
        if mp is not None and mp.get('p3_done'):
            pass
        else:
            _run_phase3()
    elif mp is not None:
        set_done('p3_done', True)

    all_tasks = fathom_created + ai_created

    done = True
    if mp is not None:
        done = mp.get('p1_done', True) and mp.get('p2_done', True) and mp.get('p3_done', True)

    return {
        'task_count': len(all_tasks),
        'backlog_count': backlog_created,
        'email_status': {
            'sent_count': sum(1 for d in all_email_details if d.get('sent')),
            'failed_count': sum(1 for d in all_email_details if not d.get('sent')),
            'details': all_email_details,
        },
        'done': done,
    }


@csrf_exempt
@require_POST
def fathom_sync_view(request):
    try:
        new_meetings, count = sync_meetings()
        # Queue task generation for newly synced meetings (runs in background worker)
        from .jobs import enqueue_task_generation, sweep
        queued = 0
        for meeting in new_meetings:
            _, is_new = enqueue_task_generation(meeting=meeting)
            if is_new:
                queued += 1
        # Process a queued job right now (time-budgeted; resumes across sweeps).
        sweep_result = None
        try:
            sweep_result = sweep(budget_seconds=50)
        except Exception as e:
            print(f"fathom_sync: inline sweep failed: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        return JsonResponse({
            'synced': count,
            'queued_jobs': queued,
            'meeting_ids': [m.id for m in new_meetings],
            'sweep': sweep_result,
            'message': f'{count} meeting(s) synced; {queued} task-generation job(s) queued.',
        })
    except Exception as e:
        print(f"fathom_sync: unexpected error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return JsonResponse({'error': 'Sync failed', 'detail': str(e)}, status=500)

@csrf_exempt
def fathom_webhook_view(request):
    """Receive Fathom webhook POSTs.

    Bypasses DRF auth entirely (same approach as process_pending_jobs) so that
    external webhook POSTs are never blocked by SSO/Session authentication or
    CSRF enforcement. Signature verification is performed against locally
    registered secrets when available.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    import json as _json
    from .models import FathomWebhook
    from .services import verify_fathom_webhook

    # --- Signature verification (best-effort, backwards compatible) ----------
    raw_body = request.body.decode('utf-8', errors='replace') if request.body else ''
    registered_secrets = list(
        FathomWebhook.objects.exclude(secret__exact='').values_list('secret', flat=True)
    )
    if registered_secrets:
        ok = any(
            verify_fathom_webhook(secret, request.headers, raw_body)
            for secret in registered_secrets
        )
        if not ok:
            print(f"[webhook] signature verification FAILED  headers={dict(request.headers)}", file=sys.stderr)
            return JsonResponse({'status': 'forbidden', 'reason': 'invalid webhook signature'}, status=403)
        print("[webhook] signature verified OK", file=sys.stderr)
    else:
        print("[webhook] no registered secrets — skipping verification", file=sys.stderr)

    # --- Parse payload -------------------------------------------------------
    try:
        payload = _json.loads(raw_body) if raw_body else {}
    except Exception:
        payload = {}
    # DRF may have already parsed it
    if not payload:
        try:
            payload = request.data if isinstance(request.data, dict) else {}
        except Exception:
            payload = {}

    print(f"[webhook] payload keys={list(payload.keys())[:15]}  recording_id={payload.get('recording_id')}", file=sys.stderr)

    try:
        meeting, created = process_webhook_payload(payload)
    except Exception as e:
        print(f"[webhook] failed to process payload: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return JsonResponse({'status': 'error', 'detail': str(e)}, status=200)

    if meeting is None:
        print("[webhook] ignored — no usable recording_id", file=sys.stderr)
        return JsonResponse({'status': 'ignored', 'reason': 'no recording_id'}, status=200)

    # --- Queue task generation ------------------------------------------------
    from .jobs import enqueue_task_generation, sweep
    job, is_new = enqueue_task_generation(meeting=meeting)
    sweep_result = None
    try:
        sweep_result = sweep(budget_seconds=45)
        job.refresh_from_db()
    except Exception as e:
        print(f"[webhook] inline sweep failed: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

    print(f"[webhook] meeting={meeting.id} created={created} job={job.id} status={job.status}", file=sys.stderr)
    return JsonResponse({
        'meeting_id': meeting.id,
        'created': created,
        'queued': True,
        'job_id': job.id,
        'job_status': job.status,
        'sweep': sweep_result,
    }, status=200)


@api_view(['GET', 'POST', 'DELETE'])
def fathom_webhook_register_view(request):
    """GET: list webhooks registered in this app (there is no Fathom list API).
    POST: register a webhook for every configured Fathom account.
    DELETE: remove a webhook from Fathom and from the local DB.
    """
    from .services import register_fathom_webhooks, delete_fathom_webhook, mask_key
    from .models import FathomWebhook

    if request.method == 'GET':
        from .services import list_fathom_webhooks
        # Start with locally registered webhooks
        local = {
            w.webhook_id: {
                'api_key': w.api_key,
                'masked': mask_key(w.api_key),
                'webhook_id': w.webhook_id,
                'destination_url': w.destination_url,
                'secret_set': bool(w.secret),
                'triggered_for': w.triggered_for,
                'registered_at': w.created_at.isoformat() if w.created_at else None,
                'source': 'local',
            }
            for w in FathomWebhook.objects.all()
        }
        # Merge in any webhooks Fathom knows about that we don't have locally
        # (e.g. added manually in Fathom's dashboard)
        try:
            for fw in list_fathom_webhooks():
                wid = fw.get('webhook_id', '')
                if wid and wid not in local:
                    local[wid] = fw
        except Exception as e:
            print(f"fathom_webhook_register: list from API failed: {e}", file=sys.stderr)
        return Response({
            'webhooks': list(local.values()),
            'detail': 'Webhooks from local DB and Fathom API.',
        })

    if request.method == 'DELETE':
        webhook_id = (request.data.get('webhook_id') or '').strip()
        api_key = (request.data.get('api_key') or '').strip() or None
        if not webhook_id:
            return Response({'error': 'webhook_id is required'}, status=400)
        ok, msg = delete_fathom_webhook(webhook_id, key=api_key)
        # Remove from local DB regardless (Fathom may have already deleted it)
        deleted_count, _ = FathomWebhook.objects.filter(webhook_id=webhook_id).delete()
        if ok:
            return Response({'status': 'deleted', 'webhook_id': webhook_id, 'detail': msg})
        elif deleted_count:
            return Response({'status': 'removed_locally', 'webhook_id': webhook_id, 'detail': f'Fathom: {msg}. Local record removed.'})
        else:
            return Response({'status': 'error', 'detail': msg}, status=400)

    # POST
    destination_url = (request.data.get('destination_url') or '').strip()
    if not destination_url:
        return Response({'error': 'destination_url is required'}, status=400)
    results = register_fathom_webhooks(
        destination_url,
        triggered_for=request.data.get('triggered_for'),
        force=bool(request.data.get('force')),
    )
    return Response({'results': results})


@api_view(['GET'])
def generation_status_view(request):
    """Poll the status of queued AI task-generation jobs.

    Query params: meeting_id=<id> for a specific meeting, or batch=1 for the
    latest batch job. Returns queued/running/done/failed plus results.

    While the job is still queued, this poll also runs a short time-budgeted
    sweep so a serverless deployment can make progress on generation in the
    background of the frontend's 5s polling.
    """
    from .jobs import latest_job, sweep
    batch = request.GET.get('batch') == '1'
    meeting = None
    meeting_id = request.GET.get('meeting_id')
    if meeting_id and not batch:
        meeting = Meeting.objects.filter(id=meeting_id).first()
        if meeting is None:
            return Response({'status': 'not_found', 'meeting_id': meeting_id}, status=404)

    job = latest_job(meeting=meeting, batch=batch)
    if job is None:
        return Response({'status': 'none', 'batch': batch}, status=200)

    if job.status == 'queued':
        try:
            sweep(budget_seconds=20)
            job.refresh_from_db()
        except Exception as e:
            print(f"generation_status: sweep failed: {e}", file=sys.stderr)

    return Response({
        'status': job.status,
        'job_id': job.id,
        'batch': job.batch,
        'meeting_id': job.meeting_id,
        'task_count': job.task_count,
        'backlog_count': job.backlog_count,
        'emails_sent': job.emails_sent,
        'emails_failed': job.emails_failed,
        'error': job.error,
        'created_at': job.created_at.isoformat(),
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
    })


def _cron_request_authorized(request):
    """Gate the cron/process-pending endpoint.

    - Local dev (DEBUG=True): always allowed.
    - Vercel cron requests carry User-Agent 'vercel-cron/1.0': allowed.
    - Otherwise requires Authorization: Bearer <CRON_SECRET> or ?secret=.
    """
    secret = settings.CRON_SECRET
    ua = (request.headers.get('User-Agent') or '')
    if settings.DEBUG:
        return True
    if ua.startswith('vercel-cron'):
        return True
    if not secret:
        return False
    import hmac
    provided = (request.headers.get('Authorization') or '').removeprefix('Bearer ').strip() or (request.GET.get('secret') or '')
    return bool(provided) and hmac.compare_digest(provided, secret)


def _process_pending_jobs_impl(request):
    """Serverless-friendly job processor.

    Claims the oldest queued task-generation job and runs it within a time
    budget (default 50s, max 55s). If the budget is exceeded the job is
    re-queued and resumed by the next sweep, so long generations complete
    across multiple invocations (Vercel cron, webhook, or the frontend status
    poll). Protected with CRON_SECRET when configured.
    """
    from .jobs import sweep

    if not _cron_request_authorized(request):
        return Response({'error': 'unauthorized'}, status=403)

    budget = 50
    try:
        budget = max(1, min(int(request.GET.get('budget', 50)), 55))
    except (TypeError, ValueError):
        budget = 50

    return Response(sweep(budget_seconds=budget))


# The cron endpoint must NOT go through the project-wide SSO bearer auth
# (api.auth.SSOBearerAuthentication) -- that authenticator rejects every
# invalid 'Authorization: Bearer <token>' header (e.g. our CRON_SECRET) with
# 403 before this view even runs. Bypass DRF auth/permissions entirely here;
# access control is handled by _cron_request_authorized().
_process_pending_jobs_impl.authentication_classes = []
_process_pending_jobs_impl.permission_classes = []
process_pending_jobs = api_view(['GET', 'POST'])(_process_pending_jobs_impl)
process_pending_jobs.__name__ = 'process_pending_jobs'
process_pending_jobs.__doc__ = _process_pending_jobs_impl.__doc__

@api_view(['GET'])
def dashboard_stats(request):
    total_tasks = Task.objects.count()
    completed_tasks = Task.objects.filter(status='completed').count()

    employees_data = Employee.objects.annotate(
        total_tasks=Count('tasks'),
        pending_tasks=Count('tasks', filter=Q(tasks__status='pending')),
        in_progress_tasks=Count('tasks', filter=Q(tasks__status='in_progress')),
        completed_task_count=Count('tasks', filter=Q(tasks__status='completed')),
    ).values('id', 'name', 'total_tasks', 'pending_tasks', 'in_progress_tasks', 'completed_task_count')

    employee_progress = []
    for e in employees_data:
        rate = round((e['completed_task_count'] / e['total_tasks'] * 100), 1) if e['total_tasks'] > 0 else 0
        employee_progress.append({
            'id': e['id'],
            'name': e['name'],
            'total': e['total_tasks'],
            'pending': e['pending_tasks'],
            'in_progress': e['in_progress_tasks'],
            'completed': e['completed_task_count'],
            'completion_rate': rate,
        })

    task_by_status = {
        'pending': Task.objects.filter(status='pending').count(),
        'in_progress': Task.objects.filter(status='in_progress').count(),
        'completed': completed_tasks,
    }

    task_by_priority = {}
    for p in ['critical', 'high', 'medium', 'low']:
        task_by_priority[p] = Task.objects.filter(priority=p).count()

    task_by_source = {}
    for s in ['fathom', 'ai', 'manual']:
        task_by_source[s] = Task.objects.filter(source=s).count()

    scheduled_status = {}
    for s in ['scheduled', 'ongoing', 'completed', 'cancelled']:
        scheduled_status[s] = ScheduledMeeting.objects.filter(status=s).count()

    last_7 = timezone.now().date() - timedelta(days=6)
    task_trends = (
        Task.objects.annotate(day=TruncDay('created_at'))
        .filter(created_at__date__gte=last_7)
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )

    # Backlog stats
    total_backlog = BacklogItem.objects.count()
    pending_backlog = BacklogItem.objects.filter(created_task__isnull=True).exclude(status__in=['Done', 'Closed']).count()
    backlog_by_assignee = (
        BacklogItem.objects.filter(created_task__isnull=True)
        .exclude(status__in=['Done', 'Closed'])
        .exclude(owner__isnull=True)
        .values('owner__id', 'owner__name')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    backlog_aging = []
    now = timezone.now()
    for bi in BacklogItem.objects.filter(created_task__isnull=True).exclude(status__in=['Done', 'Closed']).only('id', 'created_at', 'eta', 'description'):
        age_days = (now - bi.created_at).days
        overdue = bi.eta and bi.eta < now.date()
        backlog_aging.append({
            'id': bi.id,
            'description': bi.description[:80],
            'age_days': age_days,
            'eta': bi.eta.isoformat() if bi.eta else None,
            'overdue': bool(overdue),
        })

    return Response({
        'total_meetings': Meeting.objects.count(),
        'total_tasks': total_tasks,
        'pending_tasks': task_by_status['pending'],
        'in_progress_tasks': task_by_status['in_progress'],
        'completed_tasks': completed_tasks,
        'total_employees': Employee.objects.count(),
        'employee_progress': employee_progress,
        'task_by_status': task_by_status,
        'task_by_priority': task_by_priority,
        'task_by_source': task_by_source,
        'scheduled_status': scheduled_status,
        'task_trends': [
            {'date': t['day'].isoformat() if t['day'] else '', 'count': t['count']}
            for t in task_trends
        ],
        'total_backlog': total_backlog,
        'pending_backlog': pending_backlog,
        'backlog_by_assignee': [
            {'id': b['owner__id'], 'name': b['owner__name'], 'count': b['count']}
            for b in backlog_by_assignee
        ],
        'backlog_aging': backlog_aging,
    })

@csrf_exempt
@require_POST
def google_auth(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    credential = data.get('credential')
    access_token = data.get('access_token')

    if credential:
        try:
            info = id_token.verify_oauth2_token(
                credential,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID
            )
        except ValueError as e:
            return JsonResponse({'error': 'Invalid token'}, status=400)
    elif access_token:
        resp = http_requests.get(
            'https://www.googleapis.com/oauth2/v3/tokeninfo',
            params={'access_token': access_token}
        )
        if resp.status_code != 200:
            return JsonResponse({'error': 'Invalid token'}, status=400)
        info = resp.json()
        if info.get('aud') != settings.GOOGLE_CLIENT_ID:
            return JsonResponse({'error': 'Token audience mismatch'}, status=400)
    else:
        return JsonResponse({'error': 'Missing token'}, status=400)

    email = info.get('email')
    if not email:
        return JsonResponse({'error': 'Email not found'}, status=400)

    user, created = User.objects.get_or_create(
        username=email,
        defaults={
            'email': email,
            'first_name': info.get('given_name', ''),
            'last_name': info.get('family_name', ''),
        }
    )

    login(request, user, backend='django.contrib.auth.backends.ModelBackend')

    return JsonResponse({
        'authenticated': True,
        'user': {
            'email': user.email,
            'name': user.get_full_name() or user.username,
        }
    })

sso_signer = Signer()

def oauth_sso(request):
    frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:5173')
    if not request.user.is_authenticated:
        return HttpResponseRedirect(f'{frontend_url}/login')
    token = sso_signer.sign(str(request.user.pk))
    return HttpResponseRedirect(f'{frontend_url}/?sso={token}')

@csrf_exempt
def google_oauth_callback(request):
    frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:5173')
    code = request.GET.get('code')
    if not code:
        return HttpResponseRedirect(f'{frontend_url}/login?error=missing_code')
    client_id = settings.GOOGLE_CLIENT_ID
    client_secret = settings.GOOGLE_CLIENT_SECRET
    if not client_id or not client_secret:
        # Fall back to SocialApp stored in the database
        try:
            from allauth.socialaccount.models import SocialApp
            app = SocialApp.objects.get(provider='google', sites__id=settings.SITE_ID)
            if not client_id:
                client_id = app.client_id
            if not client_secret:
                client_secret = app.secret
        except (SocialApp.DoesNotExist, ImportError):
            pass
        if not client_id or not client_secret:
            return HttpResponseRedirect(f'{frontend_url}/login?error=missing_oauth_config')
    token_resp = http_requests.post('https://oauth2.googleapis.com/token', data={
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': request.build_absolute_uri(request.path),
        'grant_type': 'authorization_code',
    })
    if token_resp.status_code != 200:
        return HttpResponseRedirect(f'{frontend_url}/login?error=token_exchange_failed')
    tokens = token_resp.json()
    userinfo_resp = http_requests.get('https://www.googleapis.com/oauth2/v2/userinfo', headers={
        'Authorization': f'Bearer {tokens["access_token"]}'
    })
    if userinfo_resp.status_code != 200:
        return HttpResponseRedirect(f'{frontend_url}/login?error=userinfo_failed')
    info = userinfo_resp.json()
    email = info.get('email')
    if not email:
        return HttpResponseRedirect(f'{frontend_url}/login?error=no_email')
    user, _ = User.objects.get_or_create(
        username=email,
        defaults={
            'email': email,
            'first_name': info.get('given_name', ''),
            'last_name': info.get('family_name', ''),
        }
    )

    # If Calendar scopes were granted, save the tokens for Google Calendar API
    granted_scopes = tokens.get('scope', '')
    if 'calendar' in granted_scopes and tokens.get('refresh_token'):
        GoogleCalendarToken.objects.update_or_create(
            user=user,
            defaults={
                'access_token': tokens['access_token'],
                'refresh_token': tokens['refresh_token'],
                'expires_at': timezone.now() + timedelta(seconds=tokens.get('expires_in', 3600)),
            },
        )

    token = sso_signer.sign(str(user.pk))
    return HttpResponseRedirect(f'{frontend_url}/?sso={token}')

@csrf_exempt
@require_POST
def verify_sso(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    token = data.get('sso')
    if not token:
        return JsonResponse({'error': 'Missing token'}, status=400)

    try:
        value = sso_signer.unsign(token)
        user_id = int(value)
    except (BadSignature, ValueError):
        return JsonResponse({'error': 'Invalid token'}, status=400)

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=400)

    return JsonResponse({
        'authenticated': True,
        'token': token,
        'user': {
            'email': user.email,
            'name': user.get_full_name() or user.username,
        }
    })

@api_view(['GET'])
def auth_session(request):
    if not request.user.is_authenticated:
        return Response({'authenticated': False})
    fathom_token = get_user_fathom_token(request.user)
    gc_connected = GoogleCalendarToken.objects.exists()
    return Response({
        'authenticated': True,
        'user': {
            'email': request.user.email,
            'name': request.user.get_full_name() or request.user.username,
            'fathom_connected': bool(fathom_token),
            'google_calendar_connected': gc_connected,
        }
    })

@csrf_exempt
@require_POST
def auth_logout(request):
    from allauth.socialaccount.models import SocialToken
    if request.user.is_authenticated:
        tokens = SocialToken.objects.filter(account__user=request.user, account__provider='google')
        for token in tokens:
            try:
                http_requests.post('https://oauth2.googleapis.com/revoke', params={'token': token.token})
            except Exception:
                pass
    django_logout(request)
    return JsonResponse({'authenticated': False})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def fathom_recording_detail(request, meeting_id):
    try:
        meeting = Meeting.objects.get(pk=meeting_id)
    except Meeting.DoesNotExist:
        return Response({'error': 'Meeting not found'}, status=404)
    if not meeting.fathom_recording_id:
        return Response({'error': 'No Fathom recording associated'}, status=400)
    header_sets = [h for h in ([fathom_headers(request.user)] if fathom_headers(request.user) else []) + list(all_fathom_headers())]
    if not header_sets:
        return Response({'error': 'Configure Fathom API key in Settings first', 'needs_fathom_auth': True}, status=400)
    data = None
    for headers in header_sets:
        resp = http_requests.get(
            f"{FATHOM_API_BASE}/meetings/{meeting.fathom_recording_id}",
            headers=headers
        )
        if resp.status_code == 200:
            data = resp.json()
            break
    if data is None:
        return Response({
            'recording_url': meeting.meeting_url,
            'share_url': meeting.share_url or None,
        })
    share_url = data.get('share_url') or meeting.share_url or None
    return Response({
        'recording_url': data.get('url', meeting.meeting_url),
        'share_url': share_url,
        'video_url': data.get('video_url'),
        'embed_url': data.get('embed_url'),
        'title': data.get('meeting_title') or data.get('title'),
    })

@api_view(['GET'])
def fathom_oauth_url(request):
    client_id = settings.FATHOM_OAUTH_CLIENT_ID
    redirect_uri = settings.FATHOM_OAUTH_REDIRECT_URI
    if not client_id:
        return Response({'error': 'Fathom OAuth not configured'}, status=400)
    url = (
        f"https://fathom.video/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=meetings:read recordings:read"
    )
    return Response({'url': url})

@csrf_exempt
@require_POST
def fathom_oauth_callback(request):
    from .services import exchange_fathom_code
    from json import loads
    try:
        data = loads(request.body)
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    code = data.get('code')
    if not code:
        return JsonResponse({'error': 'Missing authorization code'}, status=400)
    token = exchange_fathom_code(code, request.user)
    if token:
        return JsonResponse({'connected': True})
    return JsonResponse({'error': 'Failed to connect Fathom'}, status=400)

@csrf_exempt
@require_POST
def extract_tasks_all(request):
    from .services import _extract_tasks_from_summary
    count = 0
    for meeting in Meeting.objects.exclude(summary='').exclude(summary__isnull=True):
        existing = meeting.tasks.count()
        _extract_tasks_from_summary(meeting.summary, meeting)
        new_count = meeting.tasks.count() - existing
        count += new_count
    return JsonResponse({'tasks_created': count})

@csrf_exempt
def generate_ai_tasks(request):
    if request.method == 'OPTIONS':
        return HttpResponse()
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    from .ai_service import generate_tasks_from_summary
    from .serializers import TaskSerializer

    if not settings.OPENROUTER_API_KEY:
        return JsonResponse({'error': 'OpenRouter API key not configured. Set OPENROUTER_API_KEY in backend settings.'}, status=400)

    total = 0
    all_new_tasks = []
    meetings = Meeting.objects.exclude(transcript__isnull=True).exclude(transcript=[])
    for meeting in meetings:
        if meeting.raw_action_items:
            # Fathom already captured action items — skip AI generation to avoid duplicates
            # (auto-generation already enriched Fathom tasks with transcript context)
            continue
        if Task.objects.filter(meeting=meeting, source='ai').exists():
            continue
        transcript_text = ''
        if meeting.transcript:
            for entry in meeting.transcript:
                speaker = entry.get('speaker', {}).get('display_name', 'Unknown')
                text = entry.get('text', '')
                transcript_text += f"{speaker}: {text}\n"
        input_text = f"Meeting Title: {meeting.title}\n\n"
        if transcript_text:
            input_text += f"Transcript:\n{transcript_text}\n"
        ai_tasks = generate_tasks_from_summary(input_text, meeting.title)
        if not ai_tasks or not isinstance(ai_tasks, list):
            continue
        meeting_date = meeting.recorded_at or meeting.created_at
        new_tasks = _create_tasks_from_ai_list(ai_tasks, meeting, meeting_date)
        all_new_tasks.extend(new_tasks)
        total += len(new_tasks)

    # Send one consolidated email per employee
    email_result = {'sent_count': 0, 'failed_count': 0, 'details': []}
    if all_new_tasks:
        email_result = send_batch_tasks_email(all_new_tasks)

    return JsonResponse({
        'status': 'completed',
        'tasks_created': total,
        'emails_sent': email_result['sent_count'],
        'emails_failed': email_result['failed_count'],
        'email_details': email_result['details'],
        'message': f'{total} AI tasks generated across all meetings.',
    })


# ── Google Calendar / Google Meet Views ──

@api_view(['GET'])
def google_calendar_status(request):
    """Check if Google Calendar is connected (any user)."""
    token = GoogleCalendarToken.objects.first()
    if token:
        return Response({'connected': True, 'has_refresh_token': bool(token.refresh_token)})
    return Response({'connected': False})


@api_view(['GET'])
def google_calendar_auth_url(request):
    """Get the Google OAuth URL for Calendar scopes."""
    if not request.user.is_authenticated:
        return Response({'error': 'Not authenticated'}, status=401)
    url = get_google_calendar_auth_url(request)
    return Response({'url': url})


@csrf_exempt
def google_calendar_oauth_callback(request):
    """Handle the OAuth callback for Google Calendar (GET redirect from Google)."""
    frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:5173')

    code = request.GET.get('code')
    error = request.GET.get('error')

    if error:
        return HttpResponseRedirect(f'{frontend_url}/settings?calendar_error={error}')

    if not code:
        return HttpResponseRedirect(f'{frontend_url}/settings?calendar_error=missing_code')

    state = request.GET.get('state', '')
    user_pk = resolve_calendar_state(state)
    if not user_pk:
        return HttpResponseRedirect(f'{frontend_url}/login?calendar_error=invalid_state')

    try:
        user = User.objects.get(pk=user_pk)
    except User.DoesNotExist:
        return HttpResponseRedirect(f'{frontend_url}/login?calendar_error=user_not_found')

    client_id = settings.GOOGLE_CLIENT_ID
    client_secret = settings.GOOGLE_CLIENT_SECRET
    redirect_uri = request.build_absolute_uri('/api/google-calendar/oauth/callback/')

    if not client_id or not client_secret:
        return HttpResponseRedirect(f'{frontend_url}/settings?calendar_error=missing_config')

    token_resp = http_requests.post('https://oauth2.googleapis.com/token', data={
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    })

    if token_resp.status_code != 200:
        return HttpResponseRedirect(f'{frontend_url}/settings?calendar_error=token_exchange_failed')

    tokens = token_resp.json()
    access_token = tokens.get('access_token', '')
    refresh_token = tokens.get('refresh_token', '')
    expires_in = tokens.get('expires_in', 3600)

    GoogleCalendarToken.objects.update_or_create(
        user=user,
        defaults={
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_at': timezone.now() + timedelta(seconds=expires_in),
        },
    )

    return HttpResponseRedirect(f'{frontend_url}/meetings?calendar_connected=true')


@api_view(['POST'])
def google_calendar_create_meet(request):
    """Create a Google Calendar event with Google Meet link."""
    if not request.user.is_authenticated:
        return Response({'error': 'Not authenticated'}, status=401)

    title = request.data.get('title', 'Untitled Meeting')
    description = request.data.get('description', '')

    event, err = create_meet_event(request.user, title, description)
    if not event:
        if err == 'no_token':
            return Response({'error': 'Failed to create Google Meet. Connect your Google Calendar in Settings first.'}, status=400)
        return Response({'error': f'Google Calendar API error: {err}. Make sure the Google Calendar API is enabled in your Google Cloud project.'}, status=400)

    # Extract the Meet link
    meet_link = ''
    if event.get('conferenceData') and event['conferenceData'].get('entryPoints'):
        for entry in event['conferenceData']['entryPoints']:
            if entry.get('entryPointType') == 'video':
                meet_link = entry.get('uri', '')
                break

    # Save to our Meeting model
    start_info = event.get('start', {})
    start_time = start_info.get('dateTime') or start_info.get('date')
    recorded_at = None
    if start_time:
        try:
            recorded_at = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass

    meeting = Meeting.objects.create(
        title=title,
        meeting_url=meet_link,
        google_event_id=event.get('id'),
        recorded_at=recorded_at,
        summary=description,
    )

    return Response({
        'meeting': MeetingSerializer(meeting).data,
        'event_id': event.get('id'),
        'meet_link': meet_link,
        'html_link': event.get('htmlLink'),
    })


@api_view(['GET'])
def google_calendar_list_events(request):
    """List upcoming events from Google Calendar."""
    if not request.user.is_authenticated:
        return Response({'error': 'Not authenticated'}, status=401)

    events = list_upcoming_events(request.user, max_results=25)
    if events is None:
        gc_connected = GoogleCalendarToken.objects.filter(user=request.user).exists()
        if gc_connected:
            return Response({'error': 'Failed to fetch Google Calendar events. The Google Calendar API may not be enabled in your Google Cloud project.'}, status=400)
        return Response({'error': 'Failed to fetch Google Calendar events. Connect your Google Calendar in Settings first.'}, status=400)

    result = []
    for event in events:
        start_info = event.get('start', {})
        start_time = start_info.get('dateTime') or start_info.get('date')

        meet_link = ''
        if event.get('conferenceData') and event['conferenceData'].get('entryPoints'):
            for entry in event['conferenceData']['entryPoints']:
                if entry.get('entryPointType') == 'video':
                    meet_link = entry.get('uri', '')
                    break

        # Check if already synced
        existing_meeting = Meeting.objects.filter(google_event_id=event.get('id')).first()

        result.append({
            'id': event.get('id'),
            'title': event.get('summary', 'Untitled'),
            'description': event.get('description', ''),
            'start_time': start_time,
            'meet_link': meet_link,
            'html_link': event.get('htmlLink'),
            'synced': existing_meeting is not None,
            'meeting_id': existing_meeting.id if existing_meeting else None,
        })

    return Response({'events': result})


@api_view(['POST'])
def google_calendar_sync(request):
    """Sync Google Calendar events to our Meeting model."""
    if not request.user.is_authenticated:
        return Response({'error': 'Not authenticated'}, status=401)

    count = sync_calendar_events(request.user)
    if count is None:
        gc_connected = GoogleCalendarToken.objects.filter(user=request.user).exists()
        if gc_connected:
            return Response({'error': 'Failed to sync Google Calendar. The Google Calendar API may not be enabled in your Google Cloud project.'}, status=400)
        return Response({'error': 'Failed to sync. Connect your Google Calendar in Settings first.'}, status=400)

    return Response({'synced': count})


@api_view(['POST'])
def google_calendar_disconnect(request):
    """Disconnect Google Calendar integration."""
    if not request.user.is_authenticated:
        return Response({'error': 'Not authenticated'}, status=401)

    try:
        token = GoogleCalendarToken.objects.get(user=request.user)
        # Revoke the token
        try:
            http_requests.post('https://oauth2.googleapis.com/revoke', params={'token': token.access_token})
        except Exception:
            pass
        token.delete()
    except GoogleCalendarToken.DoesNotExist:
        pass

    return Response({'connected': False})


# ── Schedule / Notifications Views ──

class ScheduledMeetingViewSet(viewsets.ModelViewSet):
    queryset = ScheduledMeeting.objects.all()
    serializer_class = ScheduledMeetingSerializer

    def get_queryset(self):
        return ScheduledMeeting.objects.all()

    def perform_create(self, serializer):
        meeting = serializer.save(created_by=self.request.user)
        # Send meeting creation emails to attendees if any were provided
        if meeting.attendees.exists():
            created_by_name = self.request.user.get_full_name() or self.request.user.username
            for emp in meeting.attendees.all():
                created = Notification.objects.get_or_create(
                    recipient=emp,
                    meeting=meeting,
                    defaults={
                        'title': f"New Meeting: {meeting.title}",
                        'message': f"You've been added to '{meeting.title}' scheduled for {meeting.start_time.strftime('%b %d, %Y at %I:%M %p')}.",
                    }
                )
                send_meeting_created_notification(emp, meeting, created_by_name)

    @action(detail=True, methods=['post'])
    def invite(self, request, pk=None):
        meeting = self.get_object()
        employee_ids = request.data.get('employee_ids', [])
        if not employee_ids:
            return Response({'error': 'No employees selected'}, status=400)

        employees = Employee.objects.filter(id__in=employee_ids)
        meeting.attendees.add(*employees)

        created = []
        email_sent = 0
        email_failed = 0
        for emp in employees:
            notif, was_created = Notification.objects.get_or_create(
                recipient=emp,
                meeting=meeting,
                defaults={
                    'title': f"Meeting Invitation: {meeting.title}",
                    'message': (
                        f"You've been invited to '{meeting.title}' on "
                        f"{meeting.start_time.strftime('%b %d, %Y at %I:%M %p')}."
                        + (f" Location: {meeting.location}" if meeting.location else "")
                        + (f" Link: {meeting.meeting_url}" if meeting.meeting_url else "")
                    ),
                }
            )
            if was_created:
                created.append(NotificationSerializer(notif).data)

            # Also send a real email
            sent = send_meeting_invitation(emp, meeting)
            if sent:
                email_sent += 1
            else:
                email_failed += 1

        return Response({
            'invited': len(employees),
            'notifications_created': len(created),
            'emails_sent': email_sent,
            'emails_failed': email_failed,
            'attendees': ScheduledMeetingSerializer(meeting).data['attendees_details'],
        })

    @action(detail=True, methods=['post'])
    def create_meet_link(self, request, pk=None):
        """Attach a Google Meet link to this scheduled meeting."""
        meeting = self.get_object()
        event, err = create_meet_event(
            request.user,
            meeting.title,
            meeting.description,
            start_time=meeting.start_time,
            end_time=meeting.end_time,
        )
        if not event:
            if err == 'no_token':
                return Response({'error': 'Failed to create Google Meet. Connect Google Calendar in Settings first.'}, status=400)
            return Response({'error': f'Google Calendar API error: {err}. Make sure the Google Calendar API is enabled in your Google Cloud project.'}, status=400)

        meet_link = ''
        if event.get('conferenceData') and event['conferenceData'].get('entryPoints'):
            for entry in event['conferenceData']['entryPoints']:
                if entry.get('entryPointType') == 'video':
                    meet_link = entry.get('uri', '')
                    break

        meeting.meeting_url = meet_link
        meeting.google_event_id = event.get('id')
        meeting.save()

        return Response({
            'meeting_url': meet_link,
            'event_id': event.get('id'),
            'html_link': event.get('htmlLink'),
            'meeting': ScheduledMeetingSerializer(meeting).data,
        })

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        meeting = self.get_object()
        meeting.status = 'cancelled'
        meeting.save()
        return Response(ScheduledMeetingSerializer(meeting).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        meeting = self.get_object()
        meeting.status = 'completed'
        meeting.save()
        return Response(ScheduledMeetingSerializer(meeting).data)


@api_view(['GET'])
def notifications_list(request):
    """Get notifications for the current user (matched via employee email)."""
    if not request.user.is_authenticated:
        return Response({'error': 'Not authenticated'}, status=401)

    try:
        employee = Employee.objects.get(email=request.user.email)
    except Employee.DoesNotExist:
        name = request.user.get_full_name() or request.user.username
        employee = Employee.objects.create(name=name, email=request.user.email)

    notifications = Notification.objects.filter(recipient=employee)
    unread_count = notifications.filter(is_read=False).count()
    return Response({
        'notifications': NotificationSerializer(notifications, many=True).data,
        'unread_count': unread_count,
    })


@api_view(['POST'])
def notifications_mark_read(request):
    """Mark notifications as read."""
    if not request.user.is_authenticated:
        return Response({'error': 'Not authenticated'}, status=401)

    notification_ids = request.data.get('ids', [])
    if notification_ids:
        Notification.objects.filter(id__in=notification_ids).update(is_read=True)
    else:
        try:
            employee = Employee.objects.get(email=request.user.email)
            Notification.objects.filter(recipient=employee, is_read=False).update(is_read=True)
        except Employee.DoesNotExist:
            pass

    return Response({'status': 'ok'})
