from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EmployeeViewSet, MeetingViewSet, TaskViewSet, fathom_config_view, fathom_sync_view, fathom_webhook_view, dashboard_stats, auth_session, auth_logout, google_auth, oauth_sso, verify_sso, fathom_recording_detail, fathom_oauth_url, fathom_oauth_callback, extract_tasks_all, generate_ai_tasks

router = DefaultRouter()
router.register(r'employees', EmployeeViewSet)
router.register(r'meetings', MeetingViewSet)
router.register(r'tasks', TaskViewSet)

urlpatterns = [
    path('tasks/generate-ai/', generate_ai_tasks),
    path('', include(router.urls)),
    path('fathom/config/', fathom_config_view),
    path('fathom/sync/', fathom_sync_view),
    path('fathom/webhook/', fathom_webhook_view),
    path('dashboard/stats/', dashboard_stats),
    path('auth/session/', auth_session),
    path('auth/logout/', auth_logout),
    path('auth/google/', google_auth),
    path('auth/sso/', oauth_sso),
    path('auth/verify-sso/', verify_sso),
    path('fathom/oauth/url/', fathom_oauth_url),
    path('fathom/oauth/callback/', fathom_oauth_callback),
    path('fathom/recording/<int:meeting_id>/', fathom_recording_detail),
    path('tasks/extract-from-summaries/', extract_tasks_all),
]
