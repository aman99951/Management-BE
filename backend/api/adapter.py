from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter

class FixedCallbackGoogleAdapter(GoogleOAuth2Adapter):
    def get_callback_url(self, request, app):
        return 'http://localhost:5173/accounts/google/login/callback/'
