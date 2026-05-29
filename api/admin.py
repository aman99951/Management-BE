from django.contrib import admin
from .models import Employee, Meeting, Task, FathomConfig, GoogleCalendarToken, ScheduledMeeting, Notification

admin.site.register(Employee)
admin.site.register(Meeting)
admin.site.register(Task)
admin.site.register(FathomConfig)
admin.site.register(GoogleCalendarToken)
admin.site.register(ScheduledMeeting)
admin.site.register(Notification)
