import os
from django.contrib.auth import login
from django.http import HttpResponseRedirect
from django.core.signing import Signer
from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

sso_signer = Signer()

class CustomAccountAdapter(DefaultAccountAdapter):
    def get_login_redirect_url(self, request):
        frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:5173')
        token = sso_signer.sign(str(request.user.pk))
        return f'{frontend_url}/?sso={token}'

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    pass
