"""
Email service for sending notifications and action items.

Uses Django HTML email templates in api/templates/email/ for rendering.
In development (default) it prints to the console via console.EmailBackend.
Configure SMTP in .env for real deliveries.
"""
import logging
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
import os
from .models import Employee, Task, ScheduledMeeting

logger = logging.getLogger(__name__)


# ── Frontend URL (used in email footer links) ──

def _get_frontend_url():
    return os.getenv('FRONTEND_URL', '#')


# ── CC recipients for task assignment emails ──
TASK_CC_LIST = ['gajendran@mgtechnosolutions.com', 'sekar@mgtechnosolutions.com']


# ── Core send function ──

def send_email(to_email, subject, html_body, text_body=None, cc_list=None):
    """Send a single email. Returns True on success."""
    if not to_email:
        logger.warning(f"send_email skipped: no recipient email (subject={subject[:50]})")
        return False
    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body or html_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
            cc=cc_list or [],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
        cc_str = f" (CC: {', '.join(cc_list)})" if cc_list else ''
        logger.info(f"Email sent to {to_email}{cc_str}: {subject[:60]}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


# ── Action Items Emails ──

def _build_action_items_context(employee, tasks):
    """Build context dict for action_items.html template."""
    PRIORITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    sorted_tasks = sorted(tasks, key=lambda t: PRIORITY_ORDER.get(t.priority, 99))

    task_list = []
    for t in sorted_tasks:
        desc = t.description or ''
        task_list.append({
            'title': t.title,
            'description': desc,
            'description_short': desc[:200] + ('…' if len(desc) > 200 else ''),
            'priority': t.priority,
            'status': t.status,
            'meeting_title': t.meeting.title if t.meeting else None,
        })

    return {
        'employee_name': employee.name,
        'tasks': task_list,
        'frontend_url': _get_frontend_url(),
    }


def send_action_items_to_assignees(priority_filter=None, status_filter='pending'):
    """
    Send action items emails to all employees who have open tasks.

    Args:
        priority_filter: Optional ('critical', 'high', 'medium', 'low') to filter by priority.
                         Uses inclusive ("at least this priority") semantics.
                         If None or 'all', all priorities are included.
        status_filter: Task status filter ('pending', 'open' for pending+in_progress).

    Returns:
        list of dicts: {'employee_name', 'employee_email', 'task_count', 'sent'}
    """
    PRIORITY_RANK = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}

    results = []

    qs = Task.objects.select_related('assigned_to', 'meeting')
    if status_filter == 'open':
        qs = qs.filter(status__in=['pending', 'in_progress'])
    else:
        qs = qs.filter(status=status_filter)

    # Inclusive priority filtering: "high" includes critical + high
    if priority_filter and priority_filter != 'all':
        min_rank = PRIORITY_RANK.get(priority_filter, 99)
        allowed = [p for p, r in PRIORITY_RANK.items() if r <= min_rank]
        qs = qs.filter(priority__in=allowed)

    qs = qs.exclude(assigned_to__isnull=True).order_by('assigned_to', '-priority')

    # Group by employee
    grouped = {}
    for task in qs:
        emp = task.assigned_to
        grouped.setdefault(emp.id, {'employee': emp, 'tasks': []})
        grouped[emp.id]['tasks'].append(task)

    for entry in grouped.values():
        emp = entry['employee']
        tasks = entry['tasks']

        context = _build_action_items_context(emp, tasks)
        html_body = render_to_string('email/action_items.html', context)

        text_body_lines = [f"Hi {emp.name},", f"", f"Your action items ({len(tasks)} open tasks):", ""]
        for t in tasks:
            text_body_lines.append(f"- [{t.priority.upper()}] {t.title}")
            if t.description:
                text_body_lines.append(f"  {t.description[:100]}")
        text_body_lines.append("")
        text_body_lines.append("View full details on the dashboard.")
        text_body = '\n'.join(text_body_lines)

        sent = send_email(
            to_email=emp.email,
            subject=f"📋 Your Action Items — {len(tasks)} task{'s' if len(tasks) != 1 else ''}",
            html_body=html_body,
            text_body=text_body,
            cc_list=TASK_CC_LIST,
        )
        results.append({
            'employee_name': emp.name,
            'employee_email': emp.email,
            'task_count': len(tasks),
            'sent': sent,
        })

    return results


def send_task_assignment_email(task):
    """Send a notification email when a task is newly assigned to someone."""
    if not task.assigned_to or not task.assigned_to.email:
        return False

    meeting_ref = f"(from meeting: {task.meeting.title})" if task.meeting else None
    desc = (task.description or '')[:300]

    context = {
        'employee_name': task.assigned_to.name,
        'task_title': task.title,
        'task_description': desc or None,
        'task_priority': task.priority.title(),
        'meeting_ref': meeting_ref,
        'frontend_url': _get_frontend_url(),
    }

    html_body = render_to_string('email/task_assigned.html', context)

    text_lines = [
        f"Hi {task.assigned_to.name},",
        "",
        f"A new task has been assigned to you:",
        "",
        f"{task.title}",
        f"",
        f"Priority: {task.priority}",
    ]
    if meeting_ref:
        text_lines.append(meeting_ref)
    text_body = '\n'.join(text_lines)

    return send_email(
        to_email=task.assigned_to.email,
        subject=f"📌 New Task: {task.title[:60]}",
        html_body=html_body,
        text_body=text_body,
        cc_list=TASK_CC_LIST,
    )


def send_batch_tasks_email(tasks):
    """Send a single consolidated email with all tasks for an employee.
    Groups tasks by employee and sends one email per employee.

    Returns:
        dict with 'sent_count', 'failed_count', and 'details' list
        where each detail has 'employee_name', 'employee_email', 'task_count', 'sent'
    """
    # Group tasks by employee
    grouped = {}
    for task in tasks:
        if not task.assigned_to or not task.assigned_to.email:
            continue
        emp = task.assigned_to
        grouped.setdefault(emp.id, {'employee': emp, 'tasks': []})
        grouped[emp.id]['tasks'].append(task)

    PRIORITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    details = []

    for entry in grouped.values():
        emp = entry['employee']
        emp_tasks = sorted(entry['tasks'], key=lambda t: PRIORITY_ORDER.get(t.priority, 99))

        task_list = []
        for t in emp_tasks:
            desc = t.description or ''
            task_list.append({
                'title': t.title,
                'description_short': desc[:200] + ('…' if len(desc) > 200 else ''),
                'priority': t.priority,
                'status': t.status,
                'meeting_title': t.meeting.title if t.meeting else None,
            })

        context = {
            'employee_name': emp.name,
            'tasks': task_list,
            'frontend_url': _get_frontend_url(),
        }

        html_body = render_to_string('email/tasks_batch.html', context)

        text_lines = [
            f"Hi {emp.name},",
            "",
            f"You have {len(emp_tasks)} new task{'s' if len(emp_tasks) != 1 else ''}:",
            "",
        ]
        for t in emp_tasks:
            meeting_ref = f"(from: {t.meeting.title})" if t.meeting else None
            text_lines.append(f"- [{t.priority.upper()}] {t.title}")
            if meeting_ref:
                text_lines.append(f"  {meeting_ref}")
        text_lines.append("")
        text_lines.append("View full details on the dashboard.")
        text_body = '\n'.join(text_lines)

        sent = send_email(
            to_email=emp.email,
            subject=f"📋 {len(emp_tasks)} New Task{'s' if len(emp_tasks) != 1 else ''} for You",
            html_body=html_body,
            text_body=text_body,
            cc_list=TASK_CC_LIST,
        )
        details.append({
            'employee_name': emp.name,
            'employee_email': emp.email,
            'task_count': len(emp_tasks),
            'sent': sent,
        })

    return {
        'sent_count': sum(1 for d in details if d['sent']),
        'failed_count': sum(1 for d in details if not d['sent']),
        'details': details,
    }


# ── Meeting Emails ──

def send_meeting_invitation(employee, meeting):
    """Send an invitation email to an employee for a scheduled meeting."""
    if not employee.email:
        return False

    start = meeting.start_time
    end = meeting.end_time
    date_str = start.strftime('%A, %B %d, %Y')
    time_str = f"{start.strftime('%I:%M %p')} – {end.strftime('%I:%M %p')}"
    duration_min = int((end - start).total_seconds() / 60)

    context = {
        'employee_name': employee.name,
        'meeting_title': meeting.title,
        'meeting_description': (meeting.description or '')[:300] or None,
        'meeting_url': meeting.meeting_url or None,
        'meeting_location': meeting.location or None,
        'date_str': date_str,
        'time_str': time_str,
        'duration_min': duration_min,
        'frontend_url': _get_frontend_url(),
    }

    html_body = render_to_string('email/meeting_invitation.html', context)

    text_body = (
        f"Hi {employee.name},\n\n"
        f"You're invited to: {meeting.title}\n"
        f"Date: {date_str}\n"
        f"Time: {time_str} ({duration_min} min)\n\n"
        f"View details on the dashboard."
    )

    return send_email(
        to_email=employee.email,
        subject=f"📅 Invitation: {meeting.title} — {date_str}",
        html_body=html_body,
        text_body=text_body,
    )


def send_meeting_created_notification(employee, meeting, created_by_name='Someone'):
    """Send a notification email when a meeting is created with this employee as attendee."""
    if not employee.email:
        return False

    start = meeting.start_time
    date_str = start.strftime('%A, %B %d, %Y')
    time_str = start.strftime('%I:%M %p')

    context = {
        'employee_name': employee.name,
        'meeting_title': meeting.title,
        'created_by_name': created_by_name,
        'date_str': date_str,
        'time_str': time_str,
        'frontend_url': _get_frontend_url(),
    }

    html_body = render_to_string('email/meeting_created.html', context)

    text_body = (
        f"Hi {employee.name},\n\n"
        f"A new meeting has been created: {meeting.title}\n"
        f"Date: {date_str} at {time_str}\n"
        f"Created by {created_by_name}"
    )

    return send_email(
        to_email=employee.email,
        subject=f"🆕 New Meeting: {meeting.title}",
        html_body=html_body,
        text_body=text_body,
    )
