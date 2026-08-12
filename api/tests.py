from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Employee, Meeting, Task, TaskGenerationJob
from .jobs import (
    claim_next_queued_job,
    enqueue_task_generation,
    requeue_stale_running,
    run_job,
    sweep,
)


def _fake_generate_result(done=True, task_count=0, backlog_count=0):
    return {
        'task_count': task_count,
        'backlog_count': backlog_count,
        'email_status': {'sent_count': 0, 'failed_count': 0, 'details': []},
        'done': done,
    }


class JobQueueTests(TestCase):
    def setUp(self):
        self.meeting = Meeting.objects.create(title='Test Meeting', recorded_at=timezone.now())

    def test_enqueue_dedupe(self):
        job1, new1 = enqueue_task_generation(meeting=self.meeting)
        job2, new2 = enqueue_task_generation(meeting=self.meeting)
        self.assertTrue(new1)
        self.assertFalse(new2)
        self.assertEqual(job1.id, job2.id)
        self.assertEqual(job1.status, 'queued')

    def test_enqueue_skips_recent_done_job(self):
        job, _ = enqueue_task_generation(meeting=self.meeting)
        job.status = 'done'
        job.finished_at = timezone.now()
        job.save()
        job2, is_new = enqueue_task_generation(meeting=self.meeting)
        self.assertFalse(is_new)
        self.assertEqual(job.id, job2.id)

    def test_claim_marks_running_and_prevents_double_claim(self):
        job, _ = enqueue_task_generation(meeting=self.meeting)
        claimed = claim_next_queued_job()
        self.assertEqual(claimed.id, job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'running')
        self.assertIsNone(claim_next_queued_job())

    def test_requeue_stale_running(self):
        job, _ = enqueue_task_generation(meeting=self.meeting)
        job.status = 'running'
        job.started_at = timezone.now() - timedelta(minutes=20)
        job.save()
        count = requeue_stale_running()
        self.assertEqual(count, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, 'queued')

    @mock.patch('api.views._auto_generate_tasks_for_meeting')
    def test_sweep_completes_job(self, mock_gen):
        mock_gen.return_value = _fake_generate_result(done=True, task_count=3)
        job, _ = enqueue_task_generation(meeting=self.meeting)
        result = sweep(budget_seconds=10)
        self.assertTrue(result['processed'])
        self.assertEqual(result['job_id'], job.id)
        self.assertEqual(result['status'], 'done')
        self.assertFalse(result['timed_out'])
        job.refresh_from_db()
        self.assertEqual(job.status, 'done')

    @mock.patch('api.views._auto_generate_tasks_for_meeting')
    def test_sweep_requeues_on_timeout_then_resumes(self, mock_gen):
        mock_gen.side_effect = [
            _fake_generate_result(done=False, task_count=1),
            _fake_generate_result(done=True, task_count=2),
        ]
        job, _ = enqueue_task_generation(meeting=self.meeting)

        result1 = sweep(budget_seconds=10)
        self.assertTrue(result1['timed_out'])
        job.refresh_from_db()
        self.assertEqual(job.status, 'queued')
        self.assertIn('resume', job.error.lower())

        result2 = sweep(budget_seconds=10)
        self.assertEqual(result2['status'], 'done')
        job.refresh_from_db()
        self.assertEqual(job.status, 'done')

    @mock.patch('api.views._auto_generate_tasks_for_meeting')
    def test_run_job_records_failure(self, mock_gen):
        mock_gen.side_effect = RuntimeError('boom')
        job, _ = enqueue_task_generation(meeting=self.meeting)
        run_job(job, deadline=None)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertIn('boom', job.error)

    def test_sweep_with_no_jobs(self):
        self.assertEqual(sweep(budget_seconds=5)['processed'], False)


@override_settings(OPENROUTER_API_KEY='test-key')
class AutoGenerateResumeTests(TestCase):
    """Tests the real _auto_generate_tasks_for_meeting with mocked AI calls."""

    def setUp(self):
        self.emp = Employee.objects.create(name='Aman Kumar', email='aman@mgtechnosolutions.com')
        self.transcript = [
            {'speaker': {'display_name': 'Aman Kumar'}, 'text': 'I will send the report today.', 'timestamp': '00:00:01'},
            {'speaker': {'display_name': 'Gajendran Mani'}, 'text': 'Please follow up with the vendor.', 'timestamp': '00:00:02'},
        ]

    @mock.patch('api.views.send_batch_tasks_email')
    @mock.patch('api.ai_service.generate_tasks_from_summary')
    @mock.patch('api.ai_service.analyze_meeting_for_enhancements')
    def test_resume_progress_tracked(self, mock_analyze, mock_gen, mock_email):
        meeting = Meeting.objects.create(title='Daily Scrum', recorded_at=timezone.now(), transcript=self.transcript, summary='summary')
        mock_gen.return_value = [
            {'title': 'Send the report', 'description': 'I will send the report today.', 'assignee': 'Aman Kumar', 'priority': 'high'},
        ]
        mock_analyze.return_value = []
        mock_email.return_value = {'sent_count': 0, 'failed_count': 0, 'details': []}

        from .views import _auto_generate_tasks_for_meeting
        progress = {}
        result = _auto_generate_tasks_for_meeting(meeting, deadline=None, progress=progress)

        self.assertTrue(result['done'])
        self.assertEqual(Task.objects.filter(meeting=meeting, source='ai').count(), 1)
        task = Task.objects.get(meeting=meeting)
        self.assertEqual(task.assigned_to, self.emp)
        self.assertEqual(task.priority, 'high')
        mp = progress[str(meeting.id)]
        self.assertTrue(mp['p2_done'])
        self.assertTrue(mp['p3_done'])

    @mock.patch('api.views.send_batch_tasks_email')
    @mock.patch('api.ai_service.generate_tasks_from_summary')
    @mock.patch('api.ai_service.analyze_meeting_for_enhancements')
    def test_resume_does_not_duplicate(self, mock_analyze, mock_gen, mock_email):
        """Re-running generation for a meeting with existing AI tasks is skipped."""
        meeting = Meeting.objects.create(title='Daily Scrum', recorded_at=timezone.now(), transcript=self.transcript, summary='summary')
        Task.objects.create(title='Existing', description='already here', meeting=meeting, source='ai', assigned_to=self.emp, status='pending', priority='medium')

        from .views import _auto_generate_tasks_for_meeting
        result = _auto_generate_tasks_for_meeting(meeting, deadline=None, progress={str(meeting.id): {}})

        self.assertTrue(result['done'])
        self.assertEqual(Task.objects.filter(meeting=meeting, source='ai').count(), 1)
        mock_gen.assert_not_called()

    @mock.patch('api.views.send_batch_tasks_email')
    @mock.patch('api.ai_service.generate_tasks_from_summary')
    @mock.patch('api.ai_service.analyze_meeting_for_enhancements')
    def test_timeout_marks_incomplete_and_resumes(self, mock_analyze, mock_gen, mock_email):
        """A run that hits its deadline marks the meeting incomplete, then a
        resumed run finishes it without duplicating work."""
        meeting = Meeting.objects.create(title='Daily Scrum', recorded_at=timezone.now(), transcript=self.transcript, summary='summary')
        mock_email.return_value = {'sent_count': 0, 'failed_count': 0, 'details': []}

        # Emulate the real analyze_meeting_for_enhancements: it sets
        # progress['p3_done']=True when it completes (ai_service.py:420).
        def fake_analyze(meeting_text, meeting_title, deadline=None, progress=None):
            if progress is not None:
                progress['p3_done'] = True
            return []
        mock_analyze.side_effect = fake_analyze

        from .views import _auto_generate_tasks_for_meeting
        progress = {}

        # Run 1: deadline already in the past -> nothing runs, job incomplete.
        result1 = _auto_generate_tasks_for_meeting(meeting, deadline=0.0, progress=progress)
        self.assertFalse(result1['done'])
        mock_gen.assert_not_called()
        mp = progress[str(meeting.id)]
        self.assertFalse(mp['p2_done'])
        self.assertFalse(mp['p3_done'])

        # Run 2: no deadline, resumes and completes.
        def fake_gen(transcript_text, meeting_title, deadline=None, progress=None):
            if progress is not None:
                progress['p2_done'] = True
            return [{'title': 'Follow up', 'description': 'Please follow up with the vendor.', 'assignee': 'Aman Kumar', 'priority': 'high'}]
        mock_gen.side_effect = fake_gen

        result2 = _auto_generate_tasks_for_meeting(meeting, deadline=None, progress=progress)
        self.assertTrue(result2['done'])
        self.assertEqual(Task.objects.filter(meeting=meeting, source='ai').count(), 1)
        self.assertTrue(progress[str(meeting.id)]['p2_done'])
        self.assertTrue(progress[str(meeting.id)]['p3_done'])


@override_settings(DEBUG=False)
class ProcessPendingViewTests(TestCase):
    def setUp(self):
        self.meeting = Meeting.objects.create(title='Test', recorded_at=timezone.now())
        self.client = APIClient()

    @override_settings(CRON_SECRET='sekret')
    @mock.patch('api.jobs.sweep')
    def test_requires_secret(self, mock_sweep):
        enqueue_task_generation(meeting=self.meeting)
        resp = self.client.get('/api/tasks/process-pending/')
        self.assertEqual(resp.status_code, 403)
        mock_sweep.assert_not_called()

    @override_settings(CRON_SECRET='sekret')
    @mock.patch('api.jobs.sweep')
    def test_secret_allowed(self, mock_sweep):
        mock_sweep.return_value = {'processed': True, 'status': 'done'}
        enqueue_task_generation(meeting=self.meeting)
        resp = self.client.get('/api/tasks/process-pending/?secret=sekret')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'done')
        mock_sweep.assert_called_once()

    @override_settings(CRON_SECRET='sekret')
    @mock.patch('api.jobs.sweep')
    def test_bearer_secret_allowed(self, mock_sweep):
        mock_sweep.return_value = {'processed': False}
        resp = self.client.get('/api/tasks/process-pending/', HTTP_AUTHORIZATION='Bearer sekret')
        self.assertEqual(resp.status_code, 200)
        mock_sweep.assert_called_once()

    @override_settings(CRON_SECRET='sekret')
    @mock.patch('api.jobs.sweep')
    def test_vercel_cron_user_agent_allowed(self, mock_sweep):
        mock_sweep.return_value = {'processed': False}
        resp = self.client.get('/api/tasks/process-pending/', HTTP_USER_AGENT='vercel-cron/1.0')
        self.assertEqual(resp.status_code, 200)
        mock_sweep.assert_called_once()

    @override_settings(CRON_SECRET='')
    @mock.patch('api.jobs.sweep')
    def test_denied_without_secret_and_not_cron(self, mock_sweep):
        resp = self.client.get('/api/tasks/process-pending/')
        self.assertEqual(resp.status_code, 403)
        mock_sweep.assert_not_called()


class StatusAndWebhookSweepTests(TestCase):
    def setUp(self):
        self.meeting = Meeting.objects.create(title='Test', recorded_at=timezone.now())
        self.client = APIClient()

    @mock.patch('api.jobs.sweep')
    def test_generation_status_polls_sweep_for_queued_job(self, mock_sweep):
        mock_sweep.return_value = {'processed': True}
        enqueue_task_generation(meeting=self.meeting)
        resp = self.client.get(f'/api/tasks/generation-status/?meeting_id={self.meeting.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'queued')
        mock_sweep.assert_called_once_with(budget_seconds=20)

    @mock.patch('api.jobs.sweep')
    def test_generation_status_no_sweep_when_done(self, mock_sweep):
        job, _ = enqueue_task_generation(meeting=self.meeting)
        job.status = 'done'
        job.finished_at = timezone.now()
        job.save()
        resp = self.client.get(f'/api/tasks/generation-status/?meeting_id={self.meeting.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'done')
        mock_sweep.assert_not_called()

    @mock.patch('api.views.process_webhook_payload')
    @mock.patch('api.jobs.sweep')
    def test_webhook_enqueues_and_runs_sweep(self, mock_sweep, mock_payload):
        mock_payload.return_value = (self.meeting, True)
        mock_sweep.return_value = {'processed': True, 'status': 'done'}
        resp = self.client.post('/api/fathom/webhook/', {'recording_id': 12345, 'meeting_title': 'Test'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(TaskGenerationJob.objects.filter(meeting=self.meeting).count(), 1)
        mock_sweep.assert_called_once_with(budget_seconds=45)

    @mock.patch('api.views.sync_meetings')
    @mock.patch('api.jobs.sweep')
    def test_sync_enqueues_and_runs_sweep(self, mock_sweep, mock_sync):
        mock_sync.return_value = ([self.meeting], 1)
        mock_sweep.return_value = {'processed': True, 'status': 'done'}
        resp = self.client.post('/api/fathom/sync/', {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['synced'], 1)
        self.assertEqual(TaskGenerationJob.objects.filter(meeting=self.meeting).count(), 1)
        mock_sweep.assert_called_once_with(budget_seconds=50)
