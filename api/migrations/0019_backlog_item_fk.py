import django.db.models.deletion
from django.db import migrations, models


def copy_created_task_links(apps, schema_editor):
    BacklogItem = apps.get_model('api', 'BacklogItem')
    Task = apps.get_model('api', 'Task')
    for bi in BacklogItem.objects.filter(created_task__isnull=False).exclude(created_task=None).iterator():
        task = bi.created_task
        task.backlog_item = bi
        task.save(update_fields=['backlog_item'])


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0018_add_closed_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='backlog_item',
            field=models.ForeignKey(blank=True, help_text='Backlog item that generated this task', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tasks', to='api.backlogitem'),
        ),
        migrations.RunPython(copy_created_task_links, reverse_code=migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='backlogitem',
            name='created_task',
        ),
    ]
