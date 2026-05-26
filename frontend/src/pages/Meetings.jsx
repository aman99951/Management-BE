import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

const FATHOM_RECORDING_API = '/api/fathom/recording'

export default function Meetings() {
  const navigate = useNavigate()
  const [meetings, setMeetings] = useState([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [linkTitle, setLinkTitle] = useState('')
  const [linkUrl, setLinkUrl] = useState('')
  const [creating, setCreating] = useState(false)
  const [checkingId, setCheckingId] = useState(null)
  const [generatingTaskId, setGeneratingTaskId] = useState(null)
  const [expandedTranscript, setExpandedTranscript] = useState(null)
  const [openingRecording, setOpeningRecording] = useState(null)

  useEffect(() => {
    api.getMeetings().then(data => { setMeetings(data); setLoading(false) })
  }, [])

  const handleSync = async () => {
    setSyncing(true)
    await api.syncFathom()
    const updated = await api.getMeetings()
    setMeetings(updated)
    setSyncing(false)
  }

  const createMeeting = async (e) => {
    e.preventDefault()
    if (!linkUrl) return
    setCreating(true)
    await api.createMeetingWithLink({ title: linkTitle, meeting_url: linkUrl })
    const updated = await api.getMeetings()
    setMeetings(updated)
    setLinkTitle(''); setLinkUrl(''); setShowCreate(false); setCreating(false)
  }

  const checkFathom = async (id) => {
    setCheckingId(id)
    try {
      await api.checkFathomForMeeting(id)
      const updated = await api.getMeetings()
      setMeetings(updated)
    } finally {
      setCheckingId(null)
    }
  }

  const generateTasks = async (id) => {
    setGeneratingTaskId(id)
    try {
      const result = await api.generateTasksForMeeting(id)
      if (result.status === 'exists') {
        navigate(`/tasks?meeting=${id}`)
      } else {
        setTimeout(async () => {
          const updated = await api.getMeetings()
          setMeetings(updated)
          setGeneratingTaskId(null)
        }, 15000)
      }
    } catch {
      setGeneratingTaskId(null)
    }
  }

  const openRecording = async (meetingId, url) => {
    setOpeningRecording(meetingId)
    try {
      const res = await fetch(`${FATHOM_RECORDING_API}/${meetingId}/`, { credentials: 'include' })
      const data = await res.json()
      window.open(data.share_url || data.recording_url || url, '_blank', 'noopener,noreferrer')
    } catch {
      window.open(url, '_blank', 'noopener,noreferrer')
    } finally {
      setOpeningRecording(null)
    }
  }

  const renderSummary = (summary) => {
    const sections = []
    let currentPerson = null
    let currentSection = null
    for (const line of summary.split('\n')) {
      const trimmed = line.trim()
      if (trimmed.startsWith('## ')) {
        currentPerson = { name: trimmed.slice(3), sections: [] }
        sections.push(currentPerson)
        currentSection = null
      } else if (trimmed.startsWith('### ')) {
        currentSection = { title: trimmed.slice(4), items: [] }
        if (currentPerson) currentPerson.sections.push(currentSection)
      } else if (trimmed.startsWith('- ')) {
        const itemText = trimmed.slice(2).replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
        if (currentSection && itemText) currentSection.items.push(itemText)
      }
    }
    return sections.length > 0 ? sections : null
  }

  if (loading) {
    return (
      <div className="animate-fade-in">
        <div className="mb-8"><h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Meetings</h1></div>
        <div className="space-y-3">
          {[1,2,3].map(i => (
            <div key={i} className="bg-white border border-gray-200/60 rounded-2xl p-5 animate-pulse">
              <div className="flex items-center gap-3"><div className="w-9 h-9 rounded-lg bg-gray-200" /><div className="flex-1"><div className="h-4 bg-gray-200 rounded w-48 mb-2" /><div className="h-3 bg-gray-100 rounded w-32" /></div></div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Meetings</h1>
          <p className="text-sm text-[var(--color-text-secondary)] mt-1">Create meetings with Google Meet links or sync from Fathom</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-white border border-gray-200 text-[var(--color-text-primary)] text-sm font-medium rounded-xl hover:bg-gray-50 hover:border-gray-300 transition-all shadow-sm"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Add Meeting
          </button>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-[var(--color-primary-600)] to-[var(--color-primary-500)] text-white text-sm font-medium rounded-xl hover:from-[var(--color-primary-700)] hover:to-[var(--color-primary-600)] disabled:opacity-50 transition-all shadow-sm shadow-[var(--color-primary-500)]/20"
          >
            <svg className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            {syncing ? 'Syncing...' : 'Sync from Fathom'}
          </button>
        </div>
      </div>

      {showCreate && (
        <form onSubmit={createMeeting} className="bg-white border border-gray-200/60 rounded-2xl p-6 mb-6 shadow-sm animate-scale-in">
          <h3 className="text-sm font-semibold text-[var(--color-text-primary)] mb-1">Create Meeting with Link</h3>
          <p className="text-xs text-[var(--color-text-muted)] mb-4">Paste a Google Meet link below. Fathom will automatically record it when the meeting happens.</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <input
              placeholder="Meeting title (e.g. Sprint Planning)"
              value={linkTitle}
              onChange={e => setLinkTitle(e.target.value)}
              required
              className="px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary-400)] focus:border-transparent transition-shadow"
            />
            <input
              placeholder="https://meet.google.com/..."
              value={linkUrl}
              onChange={e => setLinkUrl(e.target.value)}
              required
              className="px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary-400)] focus:border-transparent transition-shadow"
            />
            <div className="flex gap-2">
              <button type="submit" disabled={creating} className="flex-1 px-4 py-2.5 bg-gradient-to-r from-[var(--color-primary-600)] to-[var(--color-primary-500)] text-white text-sm font-medium rounded-xl hover:from-[var(--color-primary-700)] hover:to-[var(--color-primary-600)] disabled:opacity-50 transition-all">
                {creating ? 'Creating...' : 'Create'}
              </button>
              <button type="button" onClick={() => setShowCreate(false)} className="px-4 py-2.5 bg-white border border-gray-200 text-[var(--color-text-secondary)] text-sm font-medium rounded-xl hover:bg-gray-50 transition-all">Cancel</button>
            </div>
          </div>
        </form>
      )}

      {meetings.length === 0 ? (
        <div className="bg-white border border-gray-200/60 rounded-2xl p-16 text-center">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[var(--color-primary-100)] to-emerald-100 flex items-center justify-center mx-auto mb-5">
            <svg className="w-8 h-8 text-[var(--color-primary-600)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
          </div>
          <p className="text-[var(--color-text-secondary)] font-semibold">No meetings yet</p>
          <p className="text-sm text-[var(--color-text-muted)] mt-1 max-w-sm mx-auto">Add a Google Meet link or sync from Fathom to get started with meeting management.</p>
        </div>
      ) : (
        <div className="space-y-3 animate-stagger">
          {meetings.map(m => {
            const hasRecording = !!m.fathom_recording_id
            const parsed = m.summary ? renderSummary(m.summary) : null
            return (
              <div key={m.id} className="group bg-white border border-gray-200/60 rounded-2xl p-5 hover:shadow-lg hover:border-gray-300/80 transition-all duration-200">
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3">
                      <div className={`w-10 h-10 rounded-xl ${hasRecording ? 'bg-gradient-to-br from-emerald-100 to-emerald-50' : 'bg-gradient-to-br from-amber-100 to-amber-50'} flex items-center justify-center shrink-0 shadow-sm`}>
                        <svg className={`w-5 h-5 ${hasRecording ? 'text-emerald-600' : 'text-amber-600'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d={hasRecording ? 'M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z' : 'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1'} />
                        </svg>
                      </div>
                      <div>
                        <h3 className="font-semibold text-[var(--color-text-primary)]">{m.title}</h3>
                        <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)] mt-0.5">
                          {m.meeting_url && !m.meeting_url.includes('fathom.video') && !m.share_url ? (
                            <a href={m.meeting_url} target="_blank" rel="noreferrer" className="text-[var(--color-primary-600)] hover:underline font-medium">Open Meet Link</a>
                          ) : null}
                          {m.recorded_at && (
                            <span>{new Date(m.recorded_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 ml-4">
                    {hasRecording ? (
                      <span className="text-xs bg-emerald-50 text-emerald-700 px-3 py-1 rounded-full font-medium ring-1 ring-emerald-600/20 flex items-center gap-1">
                        <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
                        Recorded
                      </span>
                    ) : (
                      <button
                        onClick={() => checkFathom(m.id)}
                        disabled={checkingId === m.id}
                        className="text-xs bg-amber-50 text-amber-700 px-3 py-1 rounded-full font-medium ring-1 ring-amber-600/20 hover:bg-amber-100 transition-colors disabled:opacity-50"
                      >
                        {checkingId === m.id ? 'Checking...' : 'Check Fathom'}
                      </button>
                    )}
                    {(m.summary || (m.transcript && m.transcript.length > 0)) && (
                      <button
                        onClick={() => generateTasks(m.id)}
                        disabled={generatingTaskId === m.id}
                        className="text-xs bg-indigo-50 text-indigo-700 px-3 py-1 rounded-full font-medium ring-1 ring-indigo-600/20 hover:bg-indigo-100 transition-colors disabled:opacity-50"
                      >
                        {generatingTaskId === m.id ? 'Generating...' : 'Generate Tasks'}
                      </button>
                    )}
                    {m.tasks?.length > 0 && (
                      <span className="text-xs bg-emerald-50 text-emerald-700 px-3 py-1 rounded-full font-medium ring-1 ring-emerald-600/20">{m.tasks.length} tasks</span>
                    )}
                  </div>
                </div>

                {parsed && (
                  <div className="mt-4 ml-13 pl-1">
                    <div className="space-y-3">
                      {parsed.map((person, i) => (
                        <div key={i} className="bg-gray-50/80 rounded-xl p-4 border border-gray-100">
                          <div className="flex items-center gap-2 mb-3">
                            <div className="w-6 h-6 rounded-full bg-[var(--color-primary-100)] text-[var(--color-primary-700)] flex items-center justify-center text-xs font-semibold">
                              {person.name.charAt(0)}
                            </div>
                            <h4 className="text-sm font-semibold text-[var(--color-text-primary)]">{person.name}</h4>
                          </div>
                          {person.sections.map((section, j) => (
                            <div key={j} className="mb-2 last:mb-0">
                              <p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wider mb-1.5">{section.title}</p>
                              {section.items.length > 0 ? (
                                <ul className="space-y-1">
                                  {section.items.map((item, k) => (
                                    <li key={k} className="text-sm text-[var(--color-text-secondary)] flex items-start gap-2">
                                      <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-primary-400)] mt-1.5 shrink-0" />
                                      {item}
                                    </li>
                                  ))}
                                </ul>
                              ) : (
                                <p className="text-sm text-[var(--color-text-muted)] italic">None</p>
                              )}
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {(hasRecording && (m.meeting_url?.includes('fathom.video') || m.share_url)) && (
                  <div className="mt-4 ml-13">
                    <button
                      onClick={() => openRecording(m.id, m.meeting_url)}
                      disabled={openingRecording === m.id}
                      className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-[var(--color-primary-600)] to-[var(--color-primary-500)] text-white text-sm font-medium rounded-xl hover:from-[var(--color-primary-700)] hover:to-[var(--color-primary-600)] disabled:opacity-50 transition-all shadow-sm shadow-[var(--color-primary-500)]/20"
                    >
                      <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
                      {openingRecording === m.id ? 'Opening...' : 'Play Recording'}
                    </button>
                  </div>
                )}

                {m.transcript && m.transcript.length > 0 && (
                  <div className="mt-3 ml-13">
                    <button
                      onClick={() => setExpandedTranscript(expandedTranscript === m.id ? null : m.id)}
                      className="flex items-center gap-1.5 text-xs font-medium text-[var(--color-primary-600)] hover:text-[var(--color-primary-700)] transition-colors"
                    >
                      <svg className={`w-3.5 h-3.5 transition-transform ${expandedTranscript === m.id ? 'rotate-90' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                      </svg>
                      Transcript ({m.transcript.length} lines)
                    </button>
                    {expandedTranscript === m.id && (
                      <div className="mt-2 p-4 bg-gray-50/80 rounded-xl border border-gray-100 max-h-80 overflow-y-auto">
                        <p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wider mb-3">Full Transcript</p>
                        <div className="space-y-3">
                          {m.transcript.map((entry, i) => (
                            <div key={i} className="text-sm flex gap-3">
                              <span className="text-xs text-[var(--color-text-muted)] font-mono whitespace-nowrap mt-0.5">[{entry.timestamp}]</span>
                              <div>
                                <span className="font-semibold text-[var(--color-text-primary)]">{entry.speaker?.display_name || 'Unknown'}:</span>{' '}
                                <span className="text-[var(--color-text-secondary)]">{entry.text}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {hasRecording && (!m.transcript || m.transcript.length === 0) && (
                  <div className="mt-3 ml-13">
                    <button onClick={handleSync} className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-primary-600)] transition-colors underline underline-offset-2">
                      Sync again to load transcript
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
