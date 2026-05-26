import { useState, useEffect } from 'react'
import { api } from '../api'

const cardConfig = [
  {
    label: 'Total Meetings', key: 'total_meetings',
    icon: 'M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z',
    gradient: 'from-emerald-500 to-teal-600',
    lightBg: 'bg-emerald-50', lightColor: 'text-emerald-600',
  },
  {
    label: 'Total Tasks', key: 'total_tasks',
    icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4',
    gradient: 'from-indigo-500 to-purple-600',
    lightBg: 'bg-indigo-50', lightColor: 'text-indigo-600',
  },
  {
    label: 'Pending Tasks', key: 'pending_tasks',
    icon: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z',
    gradient: 'from-amber-500 to-orange-600',
    lightBg: 'bg-amber-50', lightColor: 'text-amber-600',
  },
  {
    label: 'Completed', key: 'completed_tasks',
    icon: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z',
    gradient: 'from-emerald-500 to-green-600',
    lightBg: 'bg-emerald-50', lightColor: 'text-emerald-600',
  },
  {
    label: 'Employees', key: 'total_employees',
    icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197m13.5-9a2.5 2.5 0 11-5 0 2.5 2.5 0 015 0z',
    gradient: 'from-purple-500 to-pink-600',
    lightBg: 'bg-purple-50', lightColor: 'text-purple-600',
  },
]

export default function Dashboard() {
  const [stats, setStats] = useState(null)

  useEffect(() => { api.getDashboardStats().then(setStats) }, [])

  return (
    <div className="animate-fade-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Dashboard</h1>
        <p className="text-sm text-[var(--color-text-secondary)] mt-1">Overview of your workspace activity</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4 animate-stagger">
        {cardConfig.map(c => {
          const value = stats?.[c.key]
          return (
            <div key={c.key}
              className="group bg-white border border-gray-200/60 rounded-2xl p-5 hover:shadow-lg hover:border-gray-300/80 transition-all duration-200 cursor-default"
            >
              <div className={`w-11 h-11 rounded-xl ${c.lightBg} flex items-center justify-center mb-3 group-hover:scale-110 transition-transform duration-200`}>
                <svg className={`w-5 h-5 ${c.lightColor}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d={c.icon} />
                </svg>
              </div>
              <p className="text-3xl font-bold text-[var(--color-text-primary)] tabular-nums">{value ?? '—'}</p>
              <p className="text-sm text-[var(--color-text-secondary)] mt-1">{c.label}</p>
            </div>
          )
        })}
      </div>

      <div className="mt-8 grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white border border-gray-200/60 rounded-2xl p-6 animate-slide-up">
          <h2 className="text-lg font-semibold text-[var(--color-text-primary)] mb-4">Quick Actions</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <a href="/meetings"
              className="flex items-center gap-4 p-4 rounded-xl bg-gradient-to-r from-[var(--color-primary-50)] to-emerald-50 border border-[var(--color-primary-200)]/50 hover:shadow-md hover:border-[var(--color-primary-300)] transition-all duration-200 group">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[var(--color-primary-400)] to-[var(--color-primary-600)] flex items-center justify-center shadow-sm group-hover:scale-110 transition-transform">
                <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-[var(--color-text-primary)]">Sync Meetings</p>
                <p className="text-xs text-[var(--color-text-secondary)]">Pull latest from Fathom</p>
              </div>
            </a>
            <a href="/meetings"
              className="flex items-center gap-4 p-4 rounded-xl bg-gradient-to-r from-indigo-50 to-blue-50 border border-indigo-200/50 hover:shadow-md hover:border-indigo-300/70 transition-all duration-200 group">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-sm group-hover:scale-110 transition-transform">
                <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-[var(--color-text-primary)]">Add Meeting</p>
                <p className="text-xs text-[var(--color-text-secondary)]">Create with Meet link</p>
              </div>
            </a>
            <a href="/tasks"
              className="flex items-center gap-4 p-4 rounded-xl bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-200/50 hover:shadow-md hover:border-amber-300/70 transition-all duration-200 group">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center shadow-sm group-hover:scale-110 transition-transform">
                <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-[var(--color-text-primary)]">View Tasks</p>
                <p className="text-xs text-[var(--color-text-secondary)]">Review action items</p>
              </div>
            </a>
            <a href="/settings"
              className="flex items-center gap-4 p-4 rounded-xl bg-gradient-to-r from-gray-50 to-slate-50 border border-gray-200/60 hover:shadow-md hover:border-gray-300/80 transition-all duration-200 group">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-gray-500 to-slate-600 flex items-center justify-center shadow-sm group-hover:scale-110 transition-transform">
                <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-[var(--color-text-primary)]">Settings</p>
                <p className="text-xs text-[var(--color-text-secondary)]">Configure integrations</p>
              </div>
            </a>
          </div>
        </div>

        <div className="bg-white border border-gray-200/60 rounded-2xl p-6 animate-slide-up">
          <h2 className="text-lg font-semibold text-[var(--color-text-primary)] mb-4">At a Glance</h2>
          <div className="space-y-4">
            {[
              { label: 'Meetings recorded', value: stats?.total_meetings ?? 0, total: Math.max(stats?.total_meetings ?? 0, 1), color: 'bg-[var(--color-primary-500)]' },
              { label: 'Tasks completed', value: stats?.completed_tasks ?? 0, total: Math.max(stats?.total_tasks ?? 0, 1), color: 'bg-emerald-500' },
              { label: 'Team members', value: stats?.total_employees ?? 0, total: Math.max(stats?.total_employees ?? 0, 1), color: 'bg-purple-500' },
            ].map(item => {
              const pct = Math.min(Math.round((item.value / item.total) * 100), 100)
              return (
                <div key={item.label}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-[var(--color-text-secondary)]">{item.label}</span>
                    <span className="font-semibold text-[var(--color-text-primary)]">{item.value}</span>
                  </div>
                  <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full transition-all duration-500 ${item.color}`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
