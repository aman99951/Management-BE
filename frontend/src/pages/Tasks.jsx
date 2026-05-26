import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'

const priorityConfig = {
  critical: { label: 'Critical', classes: 'bg-red-50 text-red-700 ring-1 ring-red-600/20', dot: 'bg-red-500' },
  high: { label: 'High', classes: 'bg-orange-50 text-orange-700 ring-1 ring-orange-600/20', dot: 'bg-orange-500' },
  medium: { label: 'Medium', classes: 'bg-blue-50 text-blue-700 ring-1 ring-blue-600/20', dot: 'bg-blue-500' },
  low: { label: 'Low', classes: 'bg-slate-50 text-slate-600 ring-1 ring-slate-400/20', dot: 'bg-slate-400' },
}

const statusConfig = {
  pending: {
    label: 'Pending',
    classes: 'bg-amber-50 text-amber-700 ring-1 ring-amber-600/20',
    bar: 'bg-amber-400',
    icon: (
      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6l4 2" />
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth={2.5} fill="none" />
      </svg>
    ),
  },
  in_progress: {
    label: 'In Progress',
    classes: 'bg-blue-50 text-blue-700 ring-1 ring-blue-600/20',
    bar: 'bg-blue-500',
    icon: (
      <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
    ),
  },
  completed: {
    label: 'Completed',
    classes: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/20',
    bar: 'bg-emerald-500',
    icon: (
      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
      </svg>
    ),
  },
}

export default function Tasks() {
  const [searchParams, setSearchParams] = useSearchParams()
  const meetingFilter = searchParams.get('meeting')
  const [tasks, setTasks] = useState([])
  const [employees, setEmployees] = useState([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(null)
  const [activeFilter, setActiveFilter] = useState('all')
  const [showCreate, setShowCreate] = useState(false)
  const [commentText, setCommentText] = useState({})
  const [commentExpanded, setCommentExpanded] = useState({})
  const [showMentions, setShowMentions] = useState({})
  const [comments, setComments] = useState({})

  useEffect(() => {
    Promise.all([
      api.getTasks(),
      api.getEmployees(),
    ]).then(([tasksData, emps]) => {
      const aiTasks = tasksData.filter(t => t.source === 'ai' || t.source === 'manual')
      setTasks(aiTasks)
      setEmployees(emps)
      setLoading(false)
    })
  }, [])

  const filteredTasks = meetingFilter ? tasks.filter(t => t.meeting === parseInt(meetingFilter)) : tasks

  const displayedTasks = activeFilter === 'all'
    ? filteredTasks
    : filteredTasks.filter(t => t.status === activeFilter)

  const counts = {
    all: filteredTasks.length,
    pending: filteredTasks.filter(t => t.status === 'pending').length,
    in_progress: filteredTasks.filter(t => t.status === 'in_progress').length,
    completed: filteredTasks.filter(t => t.status === 'completed').length,
  }

  const updateStatus = async (id, status) => {
    await api.updateTaskStatus(id, status)
    setTasks(prev => prev.map(t => t.id === id ? { ...t, status } : t))
  }

  const toggleExpand = (id) => setExpanded(expanded === id ? null : id)

  const reassignTask = async (id, employeeId) => {
    const val = employeeId ? parseInt(employeeId) : null
    await api.updateTask(id, { assigned_to: val })
    setTasks(prev => prev.map(t =>
      t.id === id ? { ...t, assigned_to: val, assigned_to_name: val ? employees.find(e => e.id === val)?.name : null } : t
    ))
  }

  const toggleComments = async (id) => {
    const next = !commentExpanded[id]
    setCommentExpanded(prev => ({ ...prev, [id]: next }))
    if (next && !comments[id]) {
      const data = await api.getTaskComments(id)
      setComments(prev => ({ ...prev, [id]: data }))
    }
  }

  const addComment = async (taskId) => {
    const text = commentText[taskId]?.trim()
    if (!text) return
    const newComment = await api.addTaskComment(taskId, { text })
    setComments(prev => ({ ...prev, [taskId]: [...(prev[taskId] || []), newComment] }))
    setCommentText(prev => ({ ...prev, [taskId]: '' }))
  }

  if (loading) {
    return (
      <div className="animate-fade-in space-y-6">
        <div className="flex items-center justify-between">
          <div className="space-y-2">
            <div className="h-7 w-24 bg-gray-100 rounded-lg animate-pulse" />
            <div className="h-4 w-48 bg-gray-100 rounded-lg animate-pulse" />
          </div>
          <div className="h-10 w-32 bg-gray-100 rounded-xl animate-pulse" />
        </div>
        <div className="grid grid-cols-4 gap-3">
          {[1,2,3,4].map(i => <div key={i} className="h-20 bg-gray-100 rounded-2xl animate-pulse" />)}
        </div>
        <div className="space-y-3">
          {[1,2,3,4].map(i => <div key={i} className="h-24 bg-gray-100 rounded-2xl animate-pulse" />)}
        </div>
      </div>
    )
  }

  return (
    <div className="animate-fade-in space-y-6">

      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            {meetingFilter && (
              <button
                onClick={() => setSearchParams({})}
                className="inline-flex items-center gap-1 text-xs text-[var(--color-primary-600)] hover:text-[var(--color-primary-700)] font-medium transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
                All Tasks
              </button>
            )}
          </div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)] tracking-tight">
            {meetingFilter ? 'Meeting Tasks' : 'Tasks'}
          </h1>
          <p className="text-sm text-[var(--color-text-secondary)] mt-0.5">
            {meetingFilter
              ? `Showing ${filteredTasks.length} tasks for this meeting`
              : 'Manage and track all your action items'}
          </p>
        </div>

        <button
          onClick={() => setShowCreate(true)}
          className="inline-flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-[var(--color-primary-600)] to-[var(--color-primary-500)] text-white text-sm font-semibold rounded-xl hover:from-[var(--color-primary-700)] hover:to-[var(--color-primary-600)] transition-all shadow-md shadow-[var(--color-primary-500)]/25 active:scale-95 shrink-0"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          New Task
        </button>
      </div>

      {/* ── Stat Cards ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { key: 'all', label: 'Total', color: 'from-[var(--color-primary-500)] to-[var(--color-primary-600)]', light: 'bg-[var(--color-primary-50)]', text: 'text-[var(--color-primary-600)]' },
          { key: 'pending', label: 'Pending', color: 'from-amber-400 to-amber-500', light: 'bg-amber-50', text: 'text-amber-600' },
          { key: 'in_progress', label: 'In Progress', color: 'from-blue-400 to-blue-600', light: 'bg-blue-50', text: 'text-blue-600' },
          { key: 'completed', label: 'Completed', color: 'from-emerald-400 to-emerald-600', light: 'bg-emerald-50', text: 'text-emerald-600' },
        ].map(({ key, label, color, light, text }) => (
          <button
            key={key}
            onClick={() => setActiveFilter(key)}
            className={`relative group rounded-2xl p-4 text-left transition-all duration-200 border ${
              activeFilter === key
                ? 'bg-white border-[var(--color-card-border)] shadow-lg shadow-black/5 scale-[1.02]'
                : 'bg-white border-[var(--color-card-border)] hover:shadow-md hover:scale-[1.01]'
            }`}
          >
            {activeFilter === key && (
              <span className={`absolute inset-x-0 bottom-0 h-0.5 rounded-b-2xl bg-gradient-to-r ${color}`} />
            )}
            <div className={`inline-flex items-center justify-center w-8 h-8 rounded-xl bg-gradient-to-br ${color} mb-3 shadow-sm`}>
              {key === 'all' && <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 10h16M4 14h16M4 18h16"/></svg>}
              {key === 'pending' && <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><circle cx="12" cy="12" r="9"/><path strokeLinecap="round" d="M12 7v5l3 3"/></svg>}
              {key === 'in_progress' && <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>}
              {key === 'completed' && <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7"/></svg>}
            </div>
            <p className="text-2xl font-bold text-[var(--color-text-primary)]">{counts[key]}</p>
            <p className={`text-xs font-medium mt-0.5 ${activeFilter === key ? text : 'text-[var(--color-text-muted)]'}`}>{label}</p>
          </button>
        ))}
      </div>

      {/* ── Task List ── */}
      {displayedTasks.length === 0 ? (
        <div className="bg-white border border-[var(--color-card-border)] rounded-2xl p-16 text-center shadow-sm">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[var(--color-primary-100)] to-[var(--color-primary-200)] flex items-center justify-center mx-auto mb-4 shadow-inner">
            <svg className="w-8 h-8 text-[var(--color-primary-500)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
            </svg>
          </div>
          <p className="text-base font-semibold text-[var(--color-text-primary)]">No tasks found</p>
          <p className="text-sm text-[var(--color-text-muted)] mt-1 max-w-xs mx-auto leading-relaxed">
            {meetingFilter
              ? 'Click "Generate Tasks" on the meeting card to create tasks from its transcript.'
              : activeFilter !== 'all'
              ? `No ${activeFilter.replace('_', ' ')} tasks yet.`
              : 'Go to Meetings and click "Generate Tasks" to create tasks from transcripts.'}
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {displayedTasks.map((t, index) => {
            const isExpanded = expanded === t.id
            const status = statusConfig[t.status] || statusConfig.pending
            const priority = priorityConfig[t.priority] || priorityConfig.medium

            return (
              <div
                key={t.id}
                className="group bg-white border border-[var(--color-card-border)] rounded-2xl overflow-hidden shadow-sm hover:shadow-lg hover:border-[var(--color-primary-200)] transition-all duration-300"
                style={{ animationDelay: `${index * 40}ms` }}
              >
                {/* Priority accent bar */}
                <div className={`h-0.5 w-full ${priority.dot}`} />

                <div className="p-4 sm:p-5">
                  <div className="flex items-start gap-3 sm:gap-4">

                    {/* Status dot / checkbox area */}
                    <div className="shrink-0 mt-0.5">
                      <button
                        onClick={() => updateStatus(t.id, t.status === 'completed' ? 'pending' : 'completed')}
                        className={`w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all duration-200 ${
                          t.status === 'completed'
                            ? 'bg-emerald-500 border-emerald-500'
                            : 'border-gray-300 hover:border-[var(--color-primary-400)]'
                        }`}
                        title={t.status === 'completed' ? 'Mark as pending' : 'Mark as complete'}
                      >
                        {t.status === 'completed' && (
                          <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                      </button>
                    </div>

                    {/* Main content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        <p className={`text-sm font-semibold text-[var(--color-text-primary)] leading-snug ${t.status === 'completed' ? 'line-through opacity-50' : ''}`}>
                          {t.title}
                        </p>
                        {t.source === 'ai' && (
                          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-[var(--color-primary-600)] bg-[var(--color-primary-50)] px-1.5 py-0.5 rounded-full ring-1 ring-[var(--color-primary-200)] shrink-0">
                            <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
                            AI
                          </span>
                        )}
                        {t.source === 'manual' && (
                          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded-full ring-1 ring-emerald-200 shrink-0">
                            <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
                            Manual
                          </span>
                        )}
                      </div>

                      {/* Description toggle */}
                      {t.description && (
                        <div>
                          <button
                            onClick={() => toggleExpand(t.id)}
                            className="inline-flex items-center gap-1 text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-primary-600)] transition-colors font-medium mt-0.5"
                          >
                            <svg className={`w-3 h-3 transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                            </svg>
                            {isExpanded ? 'Hide details' : 'View details'}
                          </button>
                          {isExpanded && (
                            <div className="mt-2.5 p-3.5 bg-gray-50 rounded-xl border border-gray-100">
                              <pre className="text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap font-sans leading-relaxed">{t.description}</pre>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Meta row */}
                      <div className="flex flex-wrap items-center gap-2 sm:gap-3 mt-3">

                        {/* Assignee (reassignable) */}
                        <div className="relative">
                          <select
                            value={t.assigned_to || ''}
                            onChange={e => reassignTask(t.id, e.target.value)}
                            className="text-[11px] font-medium pl-6 pr-5 py-1 rounded-lg border border-[var(--color-card-border)] bg-white cursor-pointer appearance-none hover:border-[var(--color-primary-300)] transition-colors"
                          >
                            <option value="">Unassigned</option>
                            {employees.map(e => (
                              <option key={e.id} value={e.id}>{e.name}</option>
                            ))}
                          </select>
                          <svg className="absolute left-1.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--color-text-muted)] pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
                          </svg>
                          <svg className="absolute right-1 top-1/2 -translate-y-1/2 w-3 h-3 text-[var(--color-text-muted)] pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                          </svg>
                        </div>

                        {t.meeting_title && (
                          <>
                            <span className="text-gray-200 text-xs hidden sm:inline">•</span>
                            <span className="text-[11px] text-[var(--color-text-muted)] flex items-center gap-1 min-w-0">
                              <svg className="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
                              <span className="truncate max-w-[120px] sm:max-w-[160px]">{t.meeting_title}</span>
                            </span>
                          </>
                        )}

                        {t.created_at && (
                          <>
                            <span className="text-gray-200 text-xs hidden sm:inline">•</span>
                            <span className="text-[11px] text-[var(--color-text-muted)] flex items-center gap-1">
                              <svg className="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
                              {new Date(t.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                            </span>
                          </>
                        )}

                        <span className="text-gray-200 text-xs hidden sm:inline">•</span>
                        <button
                          onClick={() => toggleComments(t.id)}
                          className="text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-primary-600)] transition-colors flex items-center gap-1 font-medium"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                          </svg>
                          {commentExpanded[t.id] ? 'Hide' : 'Comments'}
                        </button>
                      </div>
                    </div>

                    {/* Right side controls */}
                    <div className="flex flex-col items-end gap-2 shrink-0 ml-2">
                      {t.priority && (
                        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-lg ${priority.classes}`}>
                          {priority.label}
                        </span>
                      )}

                      <div className="relative">
                        <select
                          value={t.status}
                          onChange={e => updateStatus(t.id, e.target.value)}
                          className={`text-[10px] font-semibold pl-5 pr-2 py-1 rounded-lg border-0 cursor-pointer transition-all appearance-none ${status.classes}`}
                        >
                          <option value="pending">Pending</option>
                          <option value="in_progress">In Progress</option>
                          <option value="completed">Completed</option>
                        </select>
                        <span className="absolute left-1.5 top-1/2 -translate-y-1/2 pointer-events-none">
                          {status.icon}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Comments section */}
                  {commentExpanded[t.id] && (
                    <div className="mt-4 pt-3 border-t border-[var(--color-card-border)]">
                      <div className="flex flex-col gap-2">
                        {/* Existing comments */}
                        {comments[t.id]?.length > 0 && (
                          <div className="flex flex-col gap-2 mb-2">
                            {comments[t.id].map((c) => (
                              <div key={c.id} className="flex items-start gap-2 bg-gray-50 p-2 rounded-lg">
                                <div className="w-6 h-6 rounded-full bg-[var(--color-primary-100)] text-[var(--color-primary-700)] flex items-center justify-center text-[10px] font-bold shrink-0">
                                  {c.author_name?.charAt(0) || '?'}
                                </div>
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span className="text-xs font-semibold text-[var(--color-text-primary)]">{c.author_name || 'Unknown'}</span>
                                    <span className="text-[10px] text-[var(--color-text-muted)]">
                                      {new Date(c.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
                                    </span>
                                  </div>
                                  <p className="text-xs text-[var(--color-text-secondary)] mt-0.5">{c.text}</p>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Comment input with @mention */}
                        <div className="relative">
                          <div className="flex gap-2">
                            <textarea
                              value={commentText[t.id] || ''}
                              onChange={(e) => {
                                const val = e.target.value
                                const lastAt = val.lastIndexOf('@')
                                const hasMentionTrigger = lastAt !== -1 && (val.length - lastAt <= 15) && !val.substring(lastAt + 1).includes(' ')
                                setShowMentions(prev => ({ ...prev, [t.id]: hasMentionTrigger }))
                                setCommentText(prev => ({ ...prev, [t.id]: val }))
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey) {
                                  e.preventDefault()
                                  addComment(t.id)
                                }
                              }}
                              placeholder="Add a comment... @ to mention"
                              rows={2}
                              className="flex-1 text-xs p-2 rounded-lg border border-[var(--color-card-border)] bg-white resize-none focus:outline-none focus:ring-2 focus:ring-[var(--color-primary-300)] transition-shadow"
                            />
                            <button
                              onClick={() => addComment(t.id)}
                              disabled={!commentText[t.id]?.trim()}
                              className="self-end shrink-0 px-3 py-2 text-xs font-semibold text-white bg-[var(--color-primary-500)] hover:bg-[var(--color-primary-600)] disabled:opacity-40 disabled:cursor-not-allowed rounded-lg transition-colors"
                            >
                              Send
                            </button>
                          </div>
                          {showMentions[t.id] && (
                            <div className="absolute bottom-full left-0 mb-1 w-48 bg-white rounded-lg shadow-lg border border-[var(--color-card-border)] z-10 max-h-36 overflow-y-auto">
                              {employees.filter(e => {
                                const atIndex = (commentText[t.id] || '').lastIndexOf('@')
                                const query = (commentText[t.id] || '').substring(atIndex + 1).toLowerCase()
                                return e.name.toLowerCase().includes(query)
                              }).map(e => (
                                <button
                                  key={e.id}
                                  onMouseDown={(ev) => {
                                    ev.preventDefault()
                                    const val = commentText[t.id] || ''
                                    const atIndex = val.lastIndexOf('@')
                                    const after = val.substring(atIndex + 1).replace(/[^\s]*/, '')
                                    const newVal = val.substring(0, atIndex) + '@' + e.name + ' ' + after
                                    setCommentText(prev => ({ ...prev, [t.id]: newVal }))
                                    setShowMentions(prev => ({ ...prev, [t.id]: false }))
                                  }}
                                  className="w-full text-left px-3 py-1.5 text-xs hover:bg-[var(--color-primary-50)] transition-colors flex items-center gap-2"
                                >
                                  <div className="w-5 h-5 rounded-full bg-[var(--color-primary-100)] text-[var(--color-primary-700)] flex items-center justify-center text-[9px] font-bold shrink-0">
                                    {e.name.charAt(0)}
                                  </div>
                                  <span className="font-medium text-[var(--color-text-primary)]">{e.name}</span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {showCreate && (
        <CreateTaskModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false)
            api.getTasks().then(data => {
              setTasks(data.filter(t => t.source === 'ai' || t.source === 'manual'))
            })
          }}
        />
      )}
    </div>
  )
}

function CreateTaskModal({ onClose, onCreated }) {
  const [employees, setEmployees] = useState([])
  const [meetings, setMeetings] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [form, setForm] = useState({
    title: '',
    description: '',
    assigned_to: '',
    meeting: '',
    priority: 'medium',
    status: 'pending',
    due_date: '',
    created_at: new Date().toISOString().split('T')[0],
  })

  useEffect(() => {
    api.getEmployees().then(setEmployees)
    api.getMeetings().then(setMeetings)
  }, [])

  const handleChange = (e) => setForm(prev => ({ ...prev, [e.target.name]: e.target.value }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!form.title.trim()) return
    setSubmitting(true)
    try {
      const body = { ...form, source: 'manual' }
      body.assigned_to = body.assigned_to ? parseInt(body.assigned_to) : null
      body.meeting = body.meeting ? parseInt(body.meeting) : null
      if (!body.due_date) delete body.due_date
      body.created_at = new Date(body.created_at).toISOString()
      await api.createTask(body)
      onCreated()
    } finally {
      setSubmitting(false)
    }
  }

  const inputCls = "w-full px-3.5 py-2.5 bg-gray-50/80 border border-[var(--color-card-border)] rounded-xl text-sm text-[var(--color-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary-400)]/40 focus:border-[var(--color-primary-400)] focus:bg-white transition-all placeholder:text-[var(--color-text-muted)]"
  const selectCls = inputCls + " appearance-none cursor-pointer pr-9"

  return (
    <>
      <div className="fixed inset-0 bg-[var(--color-sidebar)]/30 z-40" onClick={onClose} />
      <div className="fixed top-0 right-0 h-full w-full max-w-lg bg-[var(--color-card-bg)] shadow-2xl z-50 flex flex-col animate-slide-left border-l border-[var(--color-card-border)]" onClick={e => e.stopPropagation()}>
        {/* Panel header */}
        <div className="shrink-0 px-6 pt-6 pb-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[var(--color-primary-500)] to-[var(--color-primary-600)] flex items-center justify-center shadow-md shadow-[var(--color-primary-500)]/30">
                <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
              </div>
              <div>
                <h2 className="text-base font-bold text-[var(--color-text-primary)]">Create New Task</h2>
                <p className="text-xs text-[var(--color-text-muted)]">Add a task manually to your list</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg hover:bg-gray-100 flex items-center justify-center transition-colors text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 pb-6 border-t border-[var(--color-card-border)]">
            <form onSubmit={e => { e.stopPropagation(); handleSubmit(e) }} className="space-y-4 pt-5">

            <div>
              <label className="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1.5 tracking-wide uppercase">Title <span className="text-red-500 ml-0.5">*</span></label>
              <input
                name="title"
                value={form.title}
                onChange={handleChange}
                required
                className={inputCls}
                placeholder="What needs to be done?"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1.5 tracking-wide uppercase">Description</label>
              <textarea
                name="description"
                value={form.description}
                onChange={handleChange}
                rows={3}
                className={inputCls + " resize-none"}
                placeholder="Add more context or notes..."
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1.5 tracking-wide uppercase">Assignee</label>
                <div className="relative">
                  <select name="assigned_to" value={form.assigned_to} onChange={handleChange} className={selectCls}>
                    <option value="">Unassigned</option>
                    {employees.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}
                  </select>
                  <svg className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--color-text-muted)] pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7"/></svg>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1.5 tracking-wide uppercase">Priority</label>
                <div className="relative">
                  <select name="priority" value={form.priority} onChange={handleChange} className={selectCls}>
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                  </select>
                  <svg className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--color-text-muted)] pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7"/></svg>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1.5 tracking-wide uppercase">Status</label>
                <div className="relative">
                  <select name="status" value={form.status} onChange={handleChange} className={selectCls}>
                    <option value="pending">Pending</option>
                    <option value="in_progress">In Progress</option>
                    <option value="completed">Completed</option>
                  </select>
                  <svg className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--color-text-muted)] pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7"/></svg>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1.5 tracking-wide uppercase">Meeting</label>
                <div className="relative">
                  <select name="meeting" value={form.meeting} onChange={handleChange} className={selectCls}>
                    <option value="">None</option>
                    {meetings.map(m => <option key={m.id} value={m.id}>{m.title}</option>)}
                  </select>
                  <svg className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--color-text-muted)] pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7"/></svg>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1.5 tracking-wide uppercase">Due Date</label>
                <div className="relative">
                  <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--color-text-muted)] pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
                  <input type="date" name="due_date" value={form.due_date} onChange={handleChange} className={inputCls + " pl-9"} />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1.5 tracking-wide uppercase">Created Date</label>
                <div className="relative">
                  <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--color-text-muted)] pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                  <input type="date" name="created_at" value={form.created_at} onChange={handleChange} className={inputCls + " pl-9"} />
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-4 border-t border-[var(--color-card-border)]">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2.5 text-sm font-semibold text-[var(--color-text-secondary)] hover:bg-gray-100 rounded-xl transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting || !form.title.trim()}
                className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-[var(--color-primary-600)] to-[var(--color-primary-500)] rounded-xl hover:from-[var(--color-primary-700)] hover:to-[var(--color-primary-600)] transition-all shadow-md shadow-[var(--color-primary-500)]/25 disabled:opacity-50 disabled:cursor-not-allowed active:scale-95"
              >
                {submitting ? (
                  <>
                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                    </svg>
                    Creating...
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4"/>
                    </svg>
                    Create Task
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </>
  )
}