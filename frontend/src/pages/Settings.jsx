import { useState, useEffect } from 'react'
import { api } from '../api'

export default function Settings() {
  const [apiKey, setApiKey] = useState('')
  const [configured, setConfigured] = useState(false)
  const [saved, setSaved] = useState(false)
  const [session, setSession] = useState(null)

  useEffect(() => {
    api.getSession().then(setSession)
    api.getFathomConfig().then(data => setConfigured(data.configured))
  }, [])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    if (code) {
      api.fathomOAuthCallback(code).then(() => {
        window.history.replaceState({}, '', '/settings')
        window.location.reload()
      })
    }
  }, [])

  const save = async (e) => {
    e.preventDefault()
    await api.saveFathomConfig({ api_key: apiKey })
    setConfigured(true)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
    setApiKey('')
  }

  return (
    <div className="max-w-2xl animate-fade-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Settings</h1>
        <p className="text-sm text-[var(--color-text-secondary)] mt-1">Manage your Fathom integration and account settings</p>
      </div>

      <div className="space-y-4">
        <div className="bg-white border border-gray-200/60 rounded-2xl p-6 hover:shadow-md transition-shadow">
          <div className="flex items-center gap-4 mb-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-[var(--color-primary-100)] to-emerald-100 flex items-center justify-center shadow-sm">
              <svg className="w-6 h-6 text-[var(--color-primary-600)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
              </svg>
            </div>
            <div>
              <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Account</h2>
              <p className="text-sm text-[var(--color-text-secondary)]">Signed in with Google</p>
            </div>
          </div>
          <div className="flex items-center gap-3 bg-gray-50/80 rounded-xl px-4 py-3 border border-gray-100">
            <div className="w-9 h-9 rounded-full bg-gradient-to-br from-[var(--color-primary-400)] to-[var(--color-primary-600)] text-white flex items-center justify-center text-sm font-semibold shadow-sm">
              {session?.user?.name?.charAt(0)?.toUpperCase() || 'U'}
            </div>
            <div>
              <p className="text-sm font-medium text-[var(--color-text-primary)]">{session?.user?.name || 'User'}</p>
              <p className="text-xs text-[var(--color-text-muted)]">{session?.user?.email || ''}</p>
            </div>
            {session?.user?.google_connected && (
              <span className="ml-auto text-xs bg-emerald-50 text-emerald-700 px-3 py-1 rounded-full font-medium ring-1 ring-emerald-600/20 flex items-center gap-1">
                <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
                Connected
              </span>
            )}
          </div>
        </div>

        <div className="bg-white border border-gray-200/60 rounded-2xl p-6 hover:shadow-md transition-shadow">
          <div className="flex items-center gap-4 mb-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-100 to-indigo-100 flex items-center justify-center shadow-sm">
              <svg className="w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
            </div>
            <div>
              <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Fathom Connection</h2>
              <p className="text-sm text-[var(--color-text-secondary)]">Connect your Fathom account via OAuth or API key</p>
            </div>
          </div>
          {session?.user?.fathom_connected ? (
            <div className="flex items-center gap-2 bg-emerald-50 text-emerald-700 px-4 py-2.5 rounded-xl text-sm border border-emerald-200">
              <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Fathom account is connected via OAuth
            </div>
          ) : (
            <div>
              <p className="text-sm text-[var(--color-text-secondary)] mb-3">Authorize with Fathom to automatically sync your meetings.</p>
              <button
                onClick={async () => {
                  try {
                    const data = await api.getFathomOAuthUrl()
                    if (data.url) window.location.href = data.url
                  } catch {
                    alert('Fathom OAuth is not available. Use the API key below to connect.')
                  }
                }}
                className="px-5 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 text-white text-sm font-medium rounded-xl hover:from-blue-700 hover:to-indigo-700 transition-all shadow-sm shadow-blue-600/20"
              >
                Connect Fathom Account
              </button>
            </div>
          )}
        </div>

        <div className="bg-white border border-gray-200/60 rounded-2xl p-6 hover:shadow-md transition-shadow">
          <div className="flex items-center gap-4 mb-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-[var(--color-primary-100)] to-emerald-100 flex items-center justify-center shadow-sm">
              <svg className="w-6 h-6 text-[var(--color-primary-600)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </div>
            <div>
              <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Fathom API Key</h2>
              <p className="text-sm text-[var(--color-text-secondary)]">API key for syncing meetings and action items</p>
            </div>
          </div>

          {configured && (
            <div className="flex items-center gap-2 bg-emerald-50 text-emerald-700 px-4 py-2.5 rounded-xl mb-4 text-sm border border-emerald-200">
              <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Fathom API is configured and active
            </div>
          )}

          <form onSubmit={save}>
            <label className="block text-sm font-medium text-[var(--color-text-primary)] mb-1.5">API Key</label>
            <div className="flex gap-2">
              <input
                placeholder={configured ? 'Enter new key to update...' : 'Enter your Fathom API key'}
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                required
                className="flex-1 px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary-400)] focus:border-transparent transition-shadow"
              />
              <button type="submit" className="px-5 py-2.5 bg-gradient-to-r from-[var(--color-primary-600)] to-[var(--color-primary-500)] text-white text-sm font-medium rounded-xl hover:from-[var(--color-primary-700)] hover:to-[var(--color-primary-600)] transition-all shadow-sm shadow-[var(--color-primary-500)]/20">
                {configured ? 'Update' : 'Save'}
              </button>
            </div>
            {saved && (
              <p className="mt-2 flex items-center gap-1.5 text-sm text-emerald-600 font-medium">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                Saved successfully
              </p>
            )}
          </form>
        </div>

        <div className="bg-white border border-gray-200/60 rounded-2xl p-6 hover:shadow-md transition-shadow">
          <div className="flex items-center gap-4 mb-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-gray-100 to-slate-100 flex items-center justify-center shadow-sm">
              <svg className="w-6 h-6 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
            </div>
            <div>
              <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Webhook URL</h2>
              <p className="text-sm text-[var(--color-text-secondary)]">Configure this URL in Fathom to receive real-time updates</p>
            </div>
          </div>
          <div className="bg-gray-50/80 border border-gray-200 rounded-xl px-4 py-3 flex items-center justify-between gap-4">
            <code className="text-sm text-[var(--color-text-secondary)] break-all font-mono">
              {(import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000') + '/api/fathom/webhook/'}
            </code>
            <button
              onClick={() => navigator.clipboard.writeText(`${import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'}/api/fathom/webhook/`)}
              className="shrink-0 px-3 py-1.5 text-xs font-medium bg-white border border-gray-200 rounded-lg hover:bg-gray-50 hover:border-gray-300 transition-all"
            >
              Copy
            </button>
          </div>
        </div>

        <div className="bg-white border border-gray-200/60 rounded-2xl p-6 hover:shadow-md transition-shadow">
          <div className="flex items-center gap-4 mb-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-100 to-indigo-100 flex items-center justify-center shadow-sm">
              <svg className="w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <h2 className="text-base font-semibold text-[var(--color-text-primary)]">How it works</h2>
              <p className="text-sm text-[var(--color-text-secondary)]">End-to-end integration flow</p>
            </div>
          </div>
          <ol className="space-y-3 text-sm text-[var(--color-text-secondary)]">
            {[
              'Get your API key from Fathom Settings \u2192 API Access (fathom.video/customize)',
              'Enter the key above \u2014 it will be used to authenticate with Fathom\'s API',
              'Option A: Click "Sync from Fathom" on the Meetings page to pull all recorded meetings',
              'Option B: Set up the webhook URL in Fathom for real-time meeting data delivery',
              'When a meeting is processed, its action items become tasks assigned to matching employees',
              'Track and update task status on the Tasks page',
            ].map((step, i) => (
              <li key={i} className="flex items-start gap-3">
                <span className="w-6 h-6 rounded-full bg-gradient-to-br from-[var(--color-primary-400)] to-[var(--color-primary-600)] text-white flex items-center justify-center text-xs font-medium shrink-0 mt-0.5 shadow-sm">{i + 1}</span>
                <span className="pt-0.5">{step}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  )
}
