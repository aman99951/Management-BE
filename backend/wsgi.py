import os, sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django
django.setup()

from django.core.management import call_command
from django.contrib.sites.models import Site
from django.db import connection
from allauth.socialaccount.models import SocialApp

try:
    connection.ensure_connection()
    call_command('migrate', '--no-input', stdout=None, stderr=None)
    Site.objects.update_or_create(
        pk=1,
        defaults={
            'domain': os.environ.get('SITE_DOMAIN', 'management-be-eight.vercel.app'),
            'name': 'ManagePro',
        },
    )
    client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET', '')
    if client_id and 'your-google' not in client_id and client_secret and 'your-google' not in client_secret:
        app, _ = SocialApp.objects.update_or_create(
            provider='google',
            name='Google',
            defaults={
                'client_id': client_id,
                'secret': client_secret,
            },
        )
        app.sites.add(1)
except Exception:
    pass

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
app = application
