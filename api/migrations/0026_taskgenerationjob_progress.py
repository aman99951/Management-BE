from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0025_fathomwebhook'),
    ]

    operations = [
        migrations.AddField(
            model_name='taskgenerationjob',
            name='progress',
            field=models.JSONField(blank=True, default=dict, help_text='Resume state for time-budgeted background processing (completed chunk indices per phase/meeting)'),
        ),
    ]
