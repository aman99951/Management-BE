import django.db.models.deletion
from django.db import migrations, models


def copy_backlink_to_created_task(apps, schema_editor):
    BacklogItem = apps.get_model('api', 'BacklogItem')
    Task = apps.get_model('api', 'Task')
    for bi in BacklogItem.objects.filter(tasks__isnull=False).iterator():
        first_task = bi.tasks.first()
        if first_task:
            bi.created_task = first_task
            bi.save(update_fields=['created_task'])


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0019_backlog_item_fk'),
    ]

    operations = [
        migrations.AddField(
            model_name='backlogitem',
            name='created_task',
            field=models.ForeignKey(blank=True, help_text='Task auto-created from this backlog item', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='backlog_source', to='api.task'),
        ),
        migrations.RunPython(copy_backlink_to_created_task, reverse_code=migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='task',
            name='backlog_item',
        ),
    ]
