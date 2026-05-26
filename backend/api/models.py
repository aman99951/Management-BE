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
