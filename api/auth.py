from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth.models import User
from django.core.signing import Signer, BadSignature

sso_signer = Signer()

class SSOBearerAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return None
        try:
            value = sso_signer.unsign(auth[7:])
            user = User.objects.get(pk=int(value))
            return (user, None)
        except (BadSignature, ValueError, User.DoesNotExist):
            raise AuthenticationFailed('Invalid or expired token')
