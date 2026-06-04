from rest_framework import viewsets, status
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
from datetime import datetime, timedelta
from django.db.models import Count, Q
from django.db.models.functions import TruncDay
from django.utils import timezone
import requests as http_requests
from .models import Employee, Meeting, Task, FathomConfig, Comment, GoogleCalendarToken, ScheduledMeeting, Notification
from .serializers import EmployeeSerializer, MeetingSerializer, TaskSerializer, FathomConfigSerializer, FathomWebhookSerializer, CommentSerializer, GoogleCalendarTokenSerializer, ScheduledMeetingSerializer, NotificationSerializer
from .email_service import send_action_items_to_assignees, send_meeting_invitation, send_meeting_created_notification, send_task_assignment_email


def _notify_task_assignees(tasks):
    """Send assignment notification emails for all tasks that have an assignee.
    Called automatically after task generation.
    """
    sent_count = 0
    for task in tasks:
        if task.assigned_to and task.assigned_to.email:
            if send_task_assignment_email(task):
                sent_count += 1
    return sent_count
from .services import sync_meetings, process_webhook_payload, get_config, get_user_fathom_token, fathom_headers, FATHOM_API_BASE
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
        """Auto-generate AI tasks for all meetings that have transcripts/summaries but no tasks yet."""
        total = 0
        for meeting in Meeting.objects.all():
            count = _auto_generate_tasks_for_meeting(meeting)
            total += count
        return Response({'total_generated': total})

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
        meeting = self.get_object()

        Task.objects.filter(meeting=meeting, source='ai').delete()

        transcript_text = ''
        if meeting.transcript:
            for entry in meeting.transcript:
                speaker = entry.get('speaker', {}).get('display_name', 'Unknown')
                text = entry.get('text', '')
                transcript_text += f"{speaker}: {text}\n"

        input_text = f"Meeting Title: {meeting.title}\n\n"
        if transcript_text:
            input_text += f"Transcript:\n{transcript_text}\n"

        if not settings.OPENROUTER_API_KEY:
            return Response({'error': 'OpenRouter API key not configured. Set OPENROUTER_API_KEY in backend settings.'}, status=400)

        from .ai_service import generate_tasks_from_summary

        ai_tasks = generate_tasks_from_summary(input_text, meeting.title)
        if not ai_tasks or not isinstance(ai_tasks, list):
            return Response({'status': 'failed', 'error': f'AI returned no valid tasks. Model={settings.OPENROUTER_MODEL}, API key set={"yes" if settings.OPENROUTER_API_KEY else "no"}, input_len={len(input_text)}'}, status=500)

        meeting_date = meeting.recorded_at or meeting.created_at
        for t in ai_tasks:
            title = (t.get('title') or 'Untitled Task')[:500]
            desc = t.get('description', '')
            if isinstance(desc, list):
                desc = '\n'.join(f'- {item}' for item in desc)
            assignee_name = t.get('assignee')
            employee = None
            if assignee_name:
                name = assignee_name.strip()
                employee = Employee.objects.filter(name__iexact=name).first()
                if not employee:
                    employee = Employee.objects.filter(name__icontains=name).first()
            priority = t.get('priority', 'medium')
            if priority not in dict(Task.PRIORITY_CHOICES):
                priority = 'medium'
            Task.objects.create(
                title=title,
                description=desc,
                assigned_to=employee,
                meeting=meeting,
                status='pending',
                priority=priority,
                source='ai',
                created_at=meeting_date,
            )

        # Auto-send assignment emails to assignees
        created_tasks = Task.objects.filter(meeting=meeting, source='ai')
        emailed = _notify_task_assignees(created_tasks)

        from .serializers import TaskSerializer
        return Response({
            'status': 'created',
            'tasks': TaskSerializer(created_tasks, many=True).data,
            'emails_sent': emailed,
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

@api_view(['GET', 'POST'])
@csrf_exempt
def fathom_config_view(request):
    if request.method == 'GET':
        config = get_config()
        if not config:
            return JsonResponse({'configured': False})
        return JsonResponse({'configured': True})
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    serializer = FathomConfigSerializer(data=data)
    if not serializer.is_valid():
        return JsonResponse(serializer.errors, status=400)
    config = get_config()
    if config:
        for key, val in serializer.validated_data.items():
            setattr(config, key, val)
        config.save()
    else:
        config = FathomConfig.objects.create(**serializer.validated_data)
    return JsonResponse({'configured': True})

def _auto_generate_tasks_for_meeting(meeting):
    """Auto-generate AI tasks for a meeting. Skips meetings titled 'Fathom Demo'."""
    title_lower = (meeting.title or '').lower().strip()
    if 'fathom demo' in title_lower:
        return 0

    # Don't re-generate if AI tasks already exist
    if Task.objects.filter(meeting=meeting, source='ai').exists():
        return 0

    # Need transcript or summary to generate tasks
    if not meeting.transcript and not meeting.summary:
        return 0

    transcript_text = ''
    if meeting.transcript:
        for entry in meeting.transcript:
            speaker = entry.get('speaker', {}).get('display_name', 'Unknown')
            text = entry.get('text', '')
            transcript_text += f"{speaker}: {text}\n"

    if not transcript_text and not meeting.summary:
        return 0

    input_text = f"Meeting Title: {meeting.title}\n\n"
    if transcript_text:
        input_text += f"Transcript:\n{transcript_text}\n"
    elif meeting.summary:
        input_text += f"Summary:\n{meeting.summary}\n"

    if not settings.OPENROUTER_API_KEY:
        return 0

    from .ai_service import generate_tasks_from_summary
    ai_tasks = generate_tasks_from_summary(input_text, meeting.title)
    if not ai_tasks or not isinstance(ai_tasks, list):
        return 0

    meeting_date = meeting.recorded_at or meeting.created_at
    task_count = 0
    for t in ai_tasks:
        title = (t.get('title') or 'Untitled Task')[:500]
        desc = t.get('description', '')
        if isinstance(desc, list):
            desc = '\n'.join(f'- {item}' for item in desc)
        assignee_name = t.get('assignee')
        employee = None
        if assignee_name:
            name = assignee_name.strip()
            employee = Employee.objects.filter(name__iexact=name).first()
            if not employee:
                employee = Employee.objects.filter(name__icontains=name).first()
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
        # Auto-send assignment email
        if employee and employee.email:
            send_task_assignment_email(new_task)
        task_count += 1

    return task_count


@csrf_exempt
@require_POST
def fathom_sync_view(request):
    new_meetings, count = sync_meetings()
    # Auto-generate tasks for newly synced meetings
    auto_generated = 0
    for meeting in new_meetings:
        auto_generated += _auto_generate_tasks_for_meeting(meeting)
    return JsonResponse({'synced': count, 'auto_generated_tasks': auto_generated})

@api_view(['POST'])
def fathom_webhook_view(request):
    serializer = FathomWebhookSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)
    meeting, created = process_webhook_payload(serializer.validated_data)
    # Auto-generate tasks for newly webhook-created meetings
    tasks_auto_generated = 0
    if created:
        tasks_auto_generated = _auto_generate_tasks_for_meeting(meeting)
    return Response({'meeting_id': meeting.id, 'created': created, 'auto_generated_tasks': tasks_auto_generated}, status=201)

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
    headers = fathom_headers(request.user)
    if not headers:
        return Response({'error': 'Configure Fathom API key in Settings first', 'needs_fathom_auth': True}, status=400)
    resp = http_requests.get(
        f"{FATHOM_API_BASE}/meetings/{meeting.fathom_recording_id}",
        headers=headers
    )
    if resp.status_code == 404:
        return Response({
            'recording_url': meeting.meeting_url,
            'share_url': meeting.share_url or None,
        })
    if resp.status_code != 200:
        return Response({
            'recording_url': meeting.meeting_url,
            'share_url': meeting.share_url or None,
        })
    data = resp.json()
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
    meetings = Meeting.objects.exclude(transcript__isnull=True).exclude(transcript=[])
    for meeting in meetings:
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
        for t in ai_tasks:
            title = (t.get('title') or 'Untitled Task')[:500]
            desc = t.get('description', '')
            if isinstance(desc, list):
                desc = '\n'.join(f'- {item}' for item in desc)
            assignee_name = t.get('assignee')
            employee = None
            if assignee_name:
                name = assignee_name.strip()
                employee = Employee.objects.filter(name__iexact=name).first()
                if not employee:
                    employee = Employee.objects.filter(name__icontains=name).first()
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
            # Auto-send assignment email
            if employee and employee.email:
                send_task_assignment_email(new_task)
            total += 1

    return JsonResponse({'status': 'completed', 'tasks_created': total, 'message': f'{total} AI tasks generated across all meetings.'})


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
