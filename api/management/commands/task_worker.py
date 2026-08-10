"""Background worker that processes queued AI task-generation jobs.

Run it as a long-lived process on the server:

    python manage.py task_worker

Or one job at a time (for cron):

    python manage.py task_worker --once

The worker picks up TaskGenerationJob rows and runs the (slow, multi-minute)
OpenRouter task extraction outside the HTTP request so gunicorn timeouts can
never kill generation again.
"""
import signal
import sys
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from api.models import TaskGenerationJob


class Command(BaseCommand):
    help = 'Process queued TaskGenerationJob items (AI task generation).'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process a single job then exit')
        parser.add_argument('--poll', type=int, default=2, help='Seconds to wait between polls when idle')

    def handle(self, *args, **opts):
        running = [True]

        def _stop(signum, frame):
            running[0] = False

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        self.stdout.write('task_worker started (Ctrl+C to stop)')
        sys.stdout.flush()

        while running[0]:
            close_old_connections()
            job = (
                TaskGenerationJob.objects
                .filter(status='queued')
                .select_related('meeting')
                .order_by('created_at')
                .first()
            )
            if job is None:
                if opts['once']:
                    running[0] = False
                    break
                time.sleep(opts['poll'])
                continue

            target = f'meeting {job.meeting_id}' if job.meeting_id else 'all meetings (batch)'
            self.stdout.write(f"Processing job {job.id} [{target}] ...")
            sys.stdout.flush()

            from api.jobs import run_job
            run_job(job)

            self.stdout.write(
                f"  job {job.id} -> {job.status} ({job.task_count} tasks, "
                f"{job.backlog_count} backlog, {job.emails_sent} emails sent)"
            )
            sys.stdout.flush()

            if opts['once']:
                running[0] = False

        self.stdout.write('task_worker stopped')
