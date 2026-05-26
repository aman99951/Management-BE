from django.contrib import admin
from .models import Employee, Meeting, Task, FathomConfig

admin.site.register(Employee)
admin.site.register(Meeting)
admin.site.register(Task)
admin.site.register(FathomConfig)
