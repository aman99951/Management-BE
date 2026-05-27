import os
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter

class FixedCallbackGoogleAdapter(GoogleOAuth2Adapter):
    def get_callback_url(self, request, app):
        return os.getenv('BACKEND_URL', 'http://127.0.0.1:8000') + '/accounts/google/login/callback/'
