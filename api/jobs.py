"""Background job queue for AI task generation.

AI generation (OpenRouter calls for task extraction, classification, enrichment
and backlog analysis) can take minutes for long transcripts, so it must NOT run
inside a long HTTP request (Vercel kills serverless functions at their
max-duration limit). Two ways jobs get processed:

  1. `python manage.py task_worker` — a long-lived process (or `--once` for cron).
  2. `sweep()` — a time-budgeted sweep for serverless deployments. `sweep()`
     claims the oldest queued job and runs it until a deadline; if it runs out
     of time the job is returned to `queued` so the next sweep resumes it.
     Generation is idempotent + resumable: completed chunk indices are stored
     in `job.progress`, so a resumed run only does the remaining work and never
     duplicates tasks/backlog items.

Jobs are stored in the DB, so they survive restarts and need no extra
infrastructure (no Redis/Celery).
"""
import time as _time
from datetime import timedelta

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
    double-processing. Non-force requests whose latest job finished successfully
    within the last hour are not re-queued either (webhook redeliveries).
    """
    existing = _active_qs(meeting=meeting, batch=batch).order_by('created_at').first()
    if existing:
        return existing, False

    if not force and not batch and meeting is not None:
        last = TaskGenerationJob.objects.filter(meeting=meeting, batch=False).order_by('-created_at').first()
        if last and last.status == 'done' and last.finished_at:
            if timezone.now() - last.finished_at < timedelta(hours=1):
                return last, False

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


def claim_next_queued_job():
    """Atomically mark the oldest queued job as running (if any). Returns the
    job, or None. Concurrent sweeps can't claim the same job twice."""
    with transaction.atomic():
        job = (
            TaskGenerationJob.objects
            .select_for_update(skip_locked=True)
            .filter(status='queued')
            .order_by('created_at')
            .first()
        )
        if job is None:
            return None
        job.status = 'running'
        job.started_at = timezone.now()
        job.error = ''
        job.save(update_fields=['status', 'started_at', 'error'])
        return job


def requeue_stale_running(stale_after=timedelta(minutes=10)):
    """Return jobs left `running` by a crashed/killed invocation back to queued
    so the next sweep can resume them (serverless functions can be killed at
    their max-duration limit mid-run)."""
    cutoff = timezone.now() - stale_after
    return TaskGenerationJob.objects.filter(status='running', started_at__lt=cutoff).update(
        status='queued',
        error='Requeued: previous run was killed before finishing (stale running job)',
    )


def run_job(job, deadline=None):
    """Execute a queued job, optionally under a monotonic deadline.

    When the deadline passes mid-run, the job is marked `queued` again (with
    its progress persisted) so the next sweep/worker resumes it. When deadline
    is None (long-lived worker) the job always runs to completion.
    """
    job.status = 'running'
    job.started_at = timezone.now()
    job.error = ''
    job.save(update_fields=['status', 'started_at', 'error'])

    progress = dict(job.progress or {})
    progress.setdefault('batch_done', [])

    try:
        from .views import _auto_generate_tasks_for_meeting

        done = True
        if job.batch:
            total_tasks = 0
            total_backlogs = 0
            emails_sent = 0
            emails_failed = 0
            batch_done = set(progress.get('batch_done', []))
            for meeting in Meeting.objects.all().iterator():
                if meeting.id in batch_done:
                    continue
                if deadline is not None and _time.monotonic() >= deadline:
                    done = False
                    break
                result = _auto_generate_tasks_for_meeting(meeting, deadline=deadline, progress=progress)
                total_tasks += result['task_count']
                total_backlogs += result.get('backlog_count', 0)
                emails_sent += result['email_status']['sent_count']
                emails_failed += result['email_status']['failed_count']
                if result.get('done', True):
                    batch_done.add(meeting.id)
                else:
                    done = False
            progress['batch_done'] = sorted(batch_done)
            job.task_count = total_tasks
            job.backlog_count = total_backlogs
            job.emails_sent = emails_sent
            job.emails_failed = emails_failed
        else:
            if job.force:
                # Regenerate from scratch, same as the old synchronous endpoint
                Task.objects.filter(meeting=job.meeting, source__in=['fathom', 'ai']).delete()
            result = _auto_generate_tasks_for_meeting(job.meeting, deadline=deadline, progress=progress)
            job.task_count = Task.objects.filter(meeting=job.meeting, source__in=['fathom', 'ai']).count()
            job.backlog_count = result.get('backlog_count', 0)
            job.emails_sent = result['email_status']['sent_count']
            job.emails_failed = result['email_status']['failed_count']
            done = result.get('done', True)

        job.progress = progress
        if done:
            job.status = 'done'
        else:
            job.status = 'queued'
            job.error = 'Time budget exceeded — the job will resume on the next sweep.'
    except Exception as e:
        import traceback
        traceback.print_exc()
        job.status = 'failed'
        job.error = f'{type(e).__name__}: {e}'[:2000]

    job.finished_at = timezone.now()
    job.save(update_fields=['task_count', 'backlog_count', 'emails_sent', 'emails_failed', 'status', 'error', 'progress', 'finished_at'])
    return job


def sweep(budget_seconds=50):
    """Claim and run one queued job within a time budget (serverless-friendly).

    Used by the webhook/sync views, the frontend status poll, and the cron
    endpoint. Returns a small dict describing what happened.
    """
    requeue_stale_running()
    job = claim_next_queued_job()
    if job is None:
        return {'processed': False}

    deadline = _time.monotonic() + max(1, budget_seconds)
    run_job(job, deadline=deadline)
    return {
        'processed': True,
        'job_id': job.id,
        'meeting_id': job.meeting_id,
        'batch': job.batch,
        'status': job.status,
        'timed_out': job.status == 'queued',
        'task_count': job.task_count,
        'backlog_count': job.backlog_count,
        'emails_sent': job.emails_sent,
        'emails_failed': job.emails_failed,
        'error': job.error,
    }
