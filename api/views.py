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
from django.core.signing import Signer, BadSignature
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import json
import os
import requests as http_requests
from .models import Employee, Meeting, Task, FathomConfig, Comment
from .serializers import EmployeeSerializer, MeetingSerializer, TaskSerializer, FathomConfigSerializer, FathomWebhookSerializer, CommentSerializer
from .services import sync_meetings, process_webhook_payload, get_config, get_user_fathom_token, fathom_headers, FATHOM_API_BASE

class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer

class MeetingViewSet(viewsets.ModelViewSet):
    queryset = Meeting.objects.all()
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

        existing = Task.objects.filter(meeting=meeting, source='ai')
        if existing.exists():
            from .serializers import TaskSerializer
            return Response({'status': 'exists', 'tasks': TaskSerializer(existing, many=True).data})

        transcript_text = ''
        if meeting.transcript:
            for entry in meeting.transcript:
                speaker = entry.get('speaker', {}).get('display_name', 'Unknown')
                text = entry.get('text', '')
                transcript_text += f"{speaker}: {text}\n"

        input_text = f"Meeting Title: {meeting.title}\n\n"
        if meeting.summary:
            input_text += f"Summary:\n{meeting.summary}\n\n"
        if transcript_text:
            input_text += f"Transcript:\n{transcript_text}\n"

        def run():
            import django
            django.db.close_old_connections()
            from .ai_service import generate_tasks_from_summary

            ai_tasks = generate_tasks_from_summary(input_text, meeting.title)
            if not ai_tasks or not isinstance(ai_tasks, list):
                return
            Task.objects.filter(meeting=meeting).delete()
            meeting_date = meeting.recorded_at or meeting.created_at
            for t in ai_tasks:
                title = (t.get('title') or 'Untitled Task')[:500]
                desc = t.get('description', '')
                if isinstance(desc, list):
                    desc = '\n'.join(f'- {item}' for item in desc)
                assignee_name = t.get('assignee')
                employee = None
                if assignee_name:
                    employee = Employee.objects.filter(name__iexact=assignee_name.strip()).first()
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

        import threading
        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        return Response({'status': 'started', 'message': 'AI task generation started'})

class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all()
    serializer_class = TaskSerializer

    def perform_create(self, serializer):
        serializer.save(source='manual')

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
                name = request.user.get_full_name() or request.user.username
                author, _ = Employee.objects.get_or_create(name=name, defaults={'email': request.user.email or ''})
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

@csrf_exempt
@require_POST
def fathom_sync_view(request):
    count = sync_meetings()
    return JsonResponse({'synced': count})

@api_view(['POST'])
def fathom_webhook_view(request):
    serializer = FathomWebhookSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)
    meeting = process_webhook_payload(serializer.validated_data)
    return Response({'meeting_id': meeting.id}, status=201)

@api_view(['GET'])
def dashboard_stats(request):
    return Response({
        'total_meetings': Meeting.objects.count(),
        'total_tasks': Task.objects.count(),
        'pending_tasks': Task.objects.filter(status='pending').count(),
        'completed_tasks': Task.objects.filter(status='completed').count(),
        'total_employees': Employee.objects.count(),
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
    client_id = os.getenv('GOOGLE_CLIENT_ID', '')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET', '')
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

    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request.session.save()

    response = JsonResponse({
        'authenticated': True,
        'user': {
            'email': user.email,
            'name': user.get_full_name() or user.username,
        }
    })
    from django.middleware.csrf import get_token
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        request.session.session_key,
        max_age=settings.SESSION_COOKIE_AGE,
        path=settings.SESSION_COOKIE_PATH,
        secure=secure,
        httponly=settings.SESSION_COOKIE_HTTPONLY,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )
    get_token(request)
    response.set_cookie(
        'csrftoken',
        request.META.get('CSRF_COOKIE', ''),
        max_age=settings.CSRF_COOKIE_AGE or 31449600,
        path=settings.CSRF_COOKIE_PATH or '/',
        secure=secure,
        httponly=False,
        samesite=settings.CSRF_COOKIE_SAMESITE or 'None',
    )
    response.set_cookie(
        'csrftoken',
        get_token(request),
        max_age=settings.CSRF_COOKIE_AGE or 31449600,
        path=settings.CSRF_COOKIE_PATH or '/',
        secure=secure,
        httponly=False,
        samesite=settings.CSRF_COOKIE_SAMESITE or 'None',
    )
    return response

@api_view(['GET'])
def auth_session(request):
    if not request.user.is_authenticated:
        return Response({'authenticated': False})
    fathom_token = get_user_fathom_token(request.user)
    return Response({
        'authenticated': True,
        'user': {
            'email': request.user.email,
            'name': request.user.get_full_name() or request.user.username,
            'fathom_connected': bool(fathom_token),
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

_ai_generation_running = False

@csrf_exempt
def generate_ai_tasks(request):
    global _ai_generation_running
    if request.method == 'OPTIONS':
        return HttpResponse()
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    if _ai_generation_running:
        return JsonResponse({'status': 'running', 'message': 'AI generation already in progress'})

    from .ai_service import generate_tasks_from_summary
    from .serializers import TaskSerializer

    _ai_generation_running = True

    def run():
        global _ai_generation_running
        import django
        django.db.close_old_connections()
        try:
            Task.objects.all().delete()
            meetings = Meeting.objects.exclude(summary='').exclude(summary__isnull=True)
            for meeting in meetings:
                ai_tasks = generate_tasks_from_summary(meeting.summary, meeting.title)
                if not ai_tasks or not isinstance(ai_tasks, list):
                    continue
                existing_titles = set(Task.objects.filter(meeting=meeting).values_list('title', flat=True))
                for t in ai_tasks:
                    title = (t.get('title') or 'Untitled Task')[:500]
                    if title in existing_titles:
                        continue
                    desc = t.get('description', '')
                    if isinstance(desc, list):
                        desc = '\n'.join(f'- {item}' for item in desc)
                    assignee_name = t.get('assignee')
                    employee = None
                    if assignee_name:
                        employee = Employee.objects.filter(name__iexact=assignee_name.strip()).first()
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
                    )
        finally:
            _ai_generation_running = False

    import threading
    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    return JsonResponse({'status': 'started', 'message': 'AI task generation started in background. Refresh to see results.'})
