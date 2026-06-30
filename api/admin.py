from django.contrib import admin
from .models import Employee, Meeting, Task, Comment, FathomConfig, FathomUserToken, GoogleCalendarToken, ScheduledMeeting, Notification, BacklogItem, DismissedSuggestion


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'team', 'created_at']
    list_filter = ['team', 'created_at']
    search_fields = ['name', 'email']
    date_hierarchy = 'created_at'


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ['title', 'fathom_recording_id', 'recorded_at', 'created_at']
    list_filter = ['created_at', 'recorded_at']
    search_fields = ['title']
    date_hierarchy = 'created_at'


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'priority', 'assigned_to', 'source', 'created_at']
    list_filter = ['status', 'priority', 'source', 'created_at', 'assigned_to']
    search_fields = ['title', 'description']
    date_hierarchy = 'created_at'


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ['task', 'author', 'short_text', 'created_at']
    list_filter = ['created_at', 'author']
    search_fields = ['text']
    date_hierarchy = 'created_at'

    def short_text(self, obj):
        return obj.text[:60] + ('...' if len(obj.text) > 60 else '')
    short_text.short_description = 'Comment'


@admin.register(FathomConfig)
class FathomConfigAdmin(admin.ModelAdmin):
    list_display = ['key_preview', 'email_notifications_enabled', 'created_at', 'updated_at']
    list_filter = ['email_notifications_enabled', 'created_at']
    readonly_fields = ['created_at', 'updated_at']

    def key_preview(self, obj):
        if obj.api_key and len(obj.api_key) > 8:
            return obj.api_key[:8] + '...' + obj.api_key[-4:]
        return obj.api_key
    key_preview.short_description = 'API Key'


@admin.register(FathomUserToken)
class FathomUserTokenAdmin(admin.ModelAdmin):
    list_display = ['user', 'created_at', 'updated_at']
    list_filter = ['created_at']
    search_fields = ['user__email']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(GoogleCalendarToken)
class GoogleCalendarTokenAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_expired', 'expires_at', 'created_at']
    list_filter = ['created_at', 'expires_at']
    search_fields = ['user__email']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ScheduledMeeting)
class ScheduledMeetingAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'start_time', 'end_time', 'created_by', 'created_at']
    list_filter = ['status', 'start_time', 'created_at']
    search_fields = ['title', 'description']
    date_hierarchy = 'start_time'


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['recipient', 'short_title', 'is_read', 'created_at']
    list_filter = ['is_read', 'created_at']
    search_fields = ['title', 'message']
    date_hierarchy = 'created_at'

    def short_title(self, obj):
        return obj.title[:60] + ('...' if len(obj.title) > 60 else '')
    short_title.short_description = 'Title'


@admin.register(DismissedSuggestion)
class DismissedSuggestionAdmin(admin.ModelAdmin):
    list_display = ['meeting', 'content_hash_short', 'dismissed_at']
    list_filter = ['dismissed_at']
    date_hierarchy = 'dismissed_at'

    def content_hash_short(self, obj):
        return obj.content_hash[:16] + '...' if len(obj.content_hash) > 16 else obj.content_hash
    content_hash_short.short_description = 'Hash'


@admin.register(BacklogItem)
class BacklogItemAdmin(admin.ModelAdmin):
    list_display = ['short_description', 'priority', 'status', 'source', 'owner', 'created_at']
    list_filter = ['priority', 'status', 'source', 'created_at']
    search_fields = ['description']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'updated_at']

    def short_description(self, obj):
        return obj.description[:80] + ('...' if len(obj.description) > 80 else '')
    short_description.short_description = 'Description'
