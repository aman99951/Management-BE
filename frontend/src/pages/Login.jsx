const BACKEND_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

export default function Login() {
  const googleLogin = () => {
    window.location.href = `${BACKEND_URL}/accounts/google/login/`
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0c1222] via-[#134e4a] to-[#0d9488] flex items-center justify-center p-4 relative overflow-hidden font-['Segoe_UI',system-ui,sans-serif]">
      <div className="absolute inset-0 opacity-[0.03] bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iNjAiIHZpZXdCb3g9IjAgMCA2MCA2MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxnIGZpbGw9IiNmZmYiIGZpbGwtb3BhY2l0eT0iMC40Ij48cGF0aCBkPSJNMzYgMzR2LTRoLTJ2NGgtNHYyaDR2NGgyVjM2aDR2LTJoLTR6bTAtMzB2LTRoLTR2NEg4djI4aDR2LTRoMnY0aDRWMjBoMnYtMmgtNHYtNGgyVjEwaC00VjZoLTJ2LTRoLTR2NHoiLz48L2c+PC9nPjwvc3ZnPg==')]" />
      <div className="absolute -top-40 -right-40 w-80 h-80 bg-[var(--color-primary-400)] rounded-full blur-[120px] opacity-20" />
      <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-[var(--color-primary-600)] rounded-full blur-[120px] opacity-20" />

      <div className="w-full max-w-sm animate-scale-in">
        <div className="bg-white/95 backdrop-blur-xl rounded-3xl p-10 shadow-2xl border border-white/20 text-center">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[var(--color-primary-400)] to-[var(--color-primary-600)] flex items-center justify-center mx-auto mb-6 shadow-lg shadow-[var(--color-primary-500)]/20">
            <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)] mb-1">ManagePro</h1>
          <p className="text-sm text-[var(--color-text-secondary)] mb-8">Sign in to manage your meetings and tasks</p>
          <button
            onClick={googleLogin}
            className="w-full flex items-center justify-center gap-3 px-5 py-3 bg-white border border-gray-200 rounded-xl text-sm font-medium text-[var(--color-text-primary)] hover:bg-gray-50 hover:border-gray-300 transition-all shadow-sm hover:shadow-md active:scale-[0.98]"
          >
            <svg className="w-5 h-5 shrink-0" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            Continue with Google
          </button>
          <p className="mt-6 text-xs text-[var(--color-text-muted)]">Secured with Google OAuth 2.0</p>
        </div>
      </div>
    </div>
  )
}
