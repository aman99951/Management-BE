from rest_framework import serializers
from .models import Employee, Meeting, Task, Comment, FathomConfig, GoogleCalendarToken, ScheduledMeeting, Notification

class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = '__all__'

class MeetingSerializer(serializers.ModelSerializer):
    tasks = serializers.SerializerMethodField()
    transcript_formatted = serializers.CharField(read_only=True)

    class Meta:
        model = Meeting
        fields = '__all__'

    def get_tasks(self, obj):
        return TaskSerializer(obj.tasks.all(), many=True).data

class GoogleCalendarTokenSerializer(serializers.ModelSerializer):
    connected = serializers.SerializerMethodField()

    class Meta:
        model = GoogleCalendarToken
        fields = ['connected']

    def get_connected(self, obj):
        return bool(obj.access_token)

class CommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source='author.name', read_only=True, default=None)

    class Meta:
        model = Comment
        fields = '__all__'
        extra_kwargs = {
            'task': {'required': False},
            'created_at': {'required': False},
        }

class TaskSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.CharField(source='assigned_to.name', read_only=True, default=None)
    meeting_title = serializers.CharField(source='meeting.title', read_only=True, default=None)
    comments = CommentSerializer(many=True, read_only=True)

    class Meta:
        model = Task
        fields = '__all__'
        extra_kwargs = {
            'created_at': {'required': False},
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['is_ai_generated'] = instance.pk and True
        return data

class FathomConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = FathomConfig
        fields = ['api_key', 'webhook_secret']
        extra_kwargs = {
            'api_key': {'write_only': True},
            'webhook_secret': {'write_only': True},
        }

class ScheduledMeetingSerializer(serializers.ModelSerializer):
    attendees_details = EmployeeSerializer(source='attendees', many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True, default=None)

    class Meta:
        model = ScheduledMeeting
        fields = '__all__'
        extra_kwargs = {
            'created_by': {'read_only': True},
        }


class NotificationSerializer(serializers.ModelSerializer):
    recipient_name = serializers.CharField(source='recipient.name', read_only=True)
    meeting_title = serializers.CharField(source='meeting.title', read_only=True, default=None)

    class Meta:
        model = Notification
        fields = '__all__'
        extra_kwargs = {
            'is_read': {'required': False},
        }


class FathomWebhookSerializer(serializers.Serializer):
    recording_id = serializers.IntegerField()
    title = serializers.CharField(required=False, default='')
    meeting_title = serializers.CharField(required=False, default='')
    url = serializers.URLField(required=False, default='')
    default_summary = serializers.JSONField(required=False, default=None)
    action_items = serializers.JSONField(required=False, default=None)
    recording_start_time = serializers.DateTimeField(required=False, default=None)
    transcript = serializers.JSONField(required=False, default=None)
