"""Background job queue for AI task generation.

AI generation (OpenRouter calls for task extraction, classification, enrichment
and backlog analysis) can take minutes for long transcripts, so it must NOT run
inside the HTTP request (gunicorn kills workers after 30s by default). Instead:

  - views enqueue a TaskGenerationJob and return immediately
  - `python manage.py task_worker` picks up queued jobs and runs them

Jobs are stored in the DB, so they survive worker restarts and need no extra
infrastructure (no Redis/Celery).
"""
from django.db import transaction
from django.utils import timezone

from .models import TaskGenerationJob, Task, Meeting

ACTIVE_STATUSES = ('queued', 'running')


def _active_qs(meeting=None, batch=False):
    qs = TaskGenerationJob.objects.filter(status__in=ACTIVE_STATUSES, batch=batch)
    if meeting is not None:
        qs = qs.filter(meeting=meeting)
    return qs


def enqueue_task_generation(meeting=None, force=False, batch=False):
    """Create a queued job, or return the already-active job for the same target.

    Returns (job, is_new). If a job for the same meeting/batch is already
    queued or running, the existing one is returned (is_new=False) to avoid
    double-processing.
    """
    existing = _active_qs(meeting=meeting, batch=batch).order_by('created_at').first()
    if existing:
        return existing, False
    job = TaskGenerationJob.objects.create(
        meeting=meeting,
        force=force,
        batch=batch,
        status='queued',
    )
    return job, True


def latest_job(meeting=None, batch=False):
    qs = TaskGenerationJob.objects.filter(batch=batch)
    if meeting is not None:
        qs = qs.filter(meeting=meeting)
    return qs.order_by('-created_at').first()


def run_job(job):
    """Execute a queued job. Updates the job record with results/errors."""
    job.status = 'running'
    job.started_at = timezone.now()
    job.error = ''
    job.save(update_fields=['status', 'started_at', 'error'])

    try:
        # Lazy import to avoid circular imports (views imports jobs)
        from .views import _auto_generate_tasks_for_meeting

        if job.batch:
            total_tasks = 0
            total_backlogs = 0
            emails_sent = 0
            emails_failed = 0
            for meeting in Meeting.objects.all().iterator():
                result = _auto_generate_tasks_for_meeting(meeting)
                total_tasks += result['task_count']
                total_backlogs += result.get('backlog_count', 0)
                emails_sent += result['email_status']['sent_count']
                emails_failed += result['email_status']['failed_count']
            job.task_count = total_tasks
            job.backlog_count = total_backlogs
            job.emails_sent = emails_sent
            job.emails_failed = emails_failed
        else:
            if job.force:
                # Regenerate from scratch, same as the old synchronous endpoint
                Task.objects.filter(meeting=job.meeting, source__in=['fathom', 'ai']).delete()
            result = _auto_generate_tasks_for_meeting(job.meeting)
            job.task_count = result['task_count']
            job.backlog_count = result.get('backlog_count', 0)
            job.emails_sent = result['email_status']['sent_count']
            job.emails_failed = result['email_status']['failed_count']
        job.status = 'done'
    except Exception as e:
        import traceback
        traceback.print_exc()
        job.status = 'failed'
        job.error = f'{type(e).__name__}: {e}'[:2000]

    job.finished_at = timezone.now()
    job.save(update_fields=['task_count', 'backlog_count', 'emails_sent', 'emails_failed', 'status', 'error', 'finished_at'])
    return job
