from django.db import models
from django.utils import timezone

class Employee(models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField(unique=True)
    team = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Meeting(models.Model):
    fathom_recording_id = models.IntegerField(unique=True, null=True, blank=True)
    google_event_id = models.CharField(max_length=500, unique=True, null=True, blank=True)
    title = models.CharField(max_length=500)
    meeting_url = models.URLField(blank=True)
    share_url = models.URLField(blank=True)
    recorded_at = models.DateTimeField(null=True, blank=True)
    summary = models.TextField(blank=True)
    raw_summary = models.JSONField(null=True, blank=True)
    raw_action_items = models.JSONField(null=True, blank=True)
    transcript = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def transcript_formatted(self):
        if not self.transcript:
            return ''
        lines = []
        for item in self.transcript:
            speaker = item.get('speaker', {}).get('display_name', 'Unknown')
            text = item.get('text', '')
            timestamp = item.get('timestamp', '')
            lines.append(f"[{timestamp}] {speaker}: {text}")
        return '\n'.join(lines)

    def __str__(self):
        return self.title

class Task(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    assigned_to = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks')
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, null=True, blank=True, related_name='tasks')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    due_date = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=20, default='fathom', choices=[('fathom', 'Fathom'), ('ai', 'AI'), ('manual', 'Manual')])
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.title

class Comment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True)
    text = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.author.name if self.author else '?'}: {self.text[:50]}"

class FathomConfig(models.Model):
    api_key = models.CharField(max_length=500)
    webhook_secret = models.CharField(max_length=500, blank=True)
    email_notifications_enabled = models.BooleanField(default=True, help_text='Master toggle for all email notifications (task assignments, meeting invites, etc.)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class FathomUserToken(models.Model):
    user = models.OneToOneField('auth.User', on_delete=models.CASCADE, related_name='fathom_token')
    access_token = models.CharField(max_length=2000)
    refresh_token = models.CharField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - Fathom"


class GoogleCalendarToken(models.Model):
    user = models.OneToOneField('auth.User', on_delete=models.CASCADE, related_name='google_calendar_token')
    access_token = models.CharField(max_length=2000)
    refresh_token = models.CharField(max_length=2000, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_expired(self):
        from django.utils import timezone
        return self.expires_at and self.expires_at <= timezone.now()

    def __str__(self):
        return f"{self.user.email} - Google Calendar"


class ScheduledMeeting(models.Model):
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('ongoing', 'Ongoing'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    location = models.CharField(max_length=500, blank=True, help_text='Physical location or meeting link')
    meeting_url = models.URLField(blank=True, help_text='Google Meet or video call link')
    created_by = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='scheduled_meetings')
    attendees = models.ManyToManyField(Employee, blank=True, related_name='scheduled_meetings')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    google_event_id = models.CharField(max_length=500, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_time']

    def __str__(self):
        return self.title


class BacklogItem(models.Model):
    PRIORITY_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
        ('Critical', 'Critical'),
    ]
    STATUS_CHOICES = [
        ('New', 'New'),
        ('Reviewed', 'Reviewed'),
        ('In Progress', 'In Progress'),
        ('Done', 'Done'),
        ('Future Consideration', 'Future Consideration'),
    ]
    description = models.TextField()
    image = models.TextField(blank=True, null=True, help_text='Base64 encoded image data')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='Medium')
    owner = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='backlog_items')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='New')
    source = models.CharField(max_length=20, default='manual', choices=[('manual', 'Manual'), ('auto-capture', 'Auto-captured')])
    source_ref = models.CharField(max_length=500, blank=True, help_text='Reference to the source meeting/comment')
    meeting_date = models.DateTimeField(null=True, blank=True, help_text='Date/time of the source meeting')
    created_task = models.ForeignKey('Task', on_delete=models.SET_NULL, null=True, blank=True, related_name='backlog_source', help_text='Task auto-created from this backlog item')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.description[:80]

class Notification(models.Model):
    recipient = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='notifications')
    meeting = models.ForeignKey(ScheduledMeeting, on_delete=models.CASCADE, related_name='notifications', null=True, blank=True)
    title = models.CharField(max_length=500)
    message = models.TextField(blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.recipient.name}: {self.title[:50]}"
