import { useState, useEffect } from 'react'
import { api } from '../api'

export default function Employees() {
  const [employees, setEmployees] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [team, setTeam] = useState('')

  useEffect(() => {
    api.getEmployees().then(data => { setEmployees(data); setLoading(false) })
  }, [])

  const add = async (e) => {
    e.preventDefault()
    const emp = await api.createEmployee({ name, email, team })
    setEmployees(prev => [...prev, emp])
    setName(''); setEmail(''); setTeam('')
    setShowForm(false)
  }

  const remove = async (id) => {
    await api.deleteEmployee(id)
    setEmployees(prev => prev.filter(e => e.id !== id))
  }

  if (loading) {
    return (
      <div className="animate-fade-in">
        <div className="mb-8"><h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Employees</h1></div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1,2,3].map(i => (
            <div key={i} className="bg-white border border-gray-200/60 rounded-2xl p-5 animate-pulse">
              <div className="flex items-center gap-3"><div className="w-12 h-12 rounded-full bg-gray-200" /><div className="flex-1"><div className="h-4 bg-gray-200 rounded w-24 mb-2" /><div className="h-3 bg-gray-100 rounded w-32" /></div></div>
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
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Employees</h1>
          <p className="text-sm text-[var(--color-text-secondary)] mt-1">Manage team members and their task assignments</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="inline-flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-[var(--color-primary-600)] to-[var(--color-primary-500)] text-white text-sm font-medium rounded-xl hover:from-[var(--color-primary-700)] hover:to-[var(--color-primary-600)] transition-all shadow-sm shadow-[var(--color-primary-500)]/20"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Add Employee
        </button>
      </div>

      {showForm && (
        <form onSubmit={add} className="bg-white border border-gray-200/60 rounded-2xl p-6 mb-6 shadow-sm animate-scale-in">
          <h3 className="text-sm font-semibold text-[var(--color-text-primary)] mb-4">New Employee</h3>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            <input placeholder="Full name" value={name} onChange={e => setName(e.target.value)} required
              className="px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary-400)] focus:border-transparent transition-shadow" />
            <input placeholder="Email address" type="email" value={email} onChange={e => setEmail(e.target.value)} required
              className="px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary-400)] focus:border-transparent transition-shadow" />
            <input placeholder="Team (optional)" value={team} onChange={e => setTeam(e.target.value)}
              className="px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary-400)] focus:border-transparent transition-shadow" />
            <div className="flex gap-2">
              <button type="submit" className="flex-1 px-4 py-2.5 bg-gradient-to-r from-[var(--color-primary-600)] to-[var(--color-primary-500)] text-white text-sm font-medium rounded-xl hover:from-[var(--color-primary-700)] hover:to-[var(--color-primary-600)] transition-all">Save</button>
              <button type="button" onClick={() => setShowForm(false)} className="px-4 py-2.5 bg-white border border-gray-200 text-[var(--color-text-secondary)] text-sm font-medium rounded-xl hover:bg-gray-50 transition-all">Cancel</button>
            </div>
          </div>
        </form>
      )}

      {employees.length === 0 ? (
        <div className="bg-white border border-gray-200/60 rounded-2xl p-16 text-center">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-purple-100 to-pink-100 flex items-center justify-center mx-auto mb-5">
            <svg className="w-8 h-8 text-purple-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197m13.5-9a2.5 2.5 0 11-5 0 2.5 2.5 0 015 0z" />
            </svg>
          </div>
          <p className="text-[var(--color-text-secondary)] font-semibold">No employees yet</p>
          <p className="text-sm text-[var(--color-text-muted)] mt-1 max-w-sm mx-auto">Add team members so they can be assigned tasks from meeting action items.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 animate-stagger">
          {employees.map(e => {
            const initials = e.name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2)
            return (
              <div key={e.id} className="group bg-white border border-gray-200/60 rounded-2xl p-5 hover:shadow-lg hover:border-gray-300/80 transition-all duration-200">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-full bg-gradient-to-br from-[var(--color-primary-400)] to-[var(--color-primary-600)] text-white flex items-center justify-center text-sm font-semibold shadow-sm group-hover:scale-105 transition-transform">
                      {initials}
                    </div>
                    <div>
                      <p className="font-semibold text-[var(--color-text-primary)]">{e.name}</p>
                      <p className="text-sm text-[var(--color-text-secondary)]">{e.email}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => remove(e.id)}
                    className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-[var(--color-text-muted)] hover:text-[var(--color-danger)] hover:bg-red-50 transition-all"
                    title="Remove employee"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
                {e.team && (
                  <div className="mt-3">
                    <span className="inline-flex items-center gap-1 text-xs bg-[var(--color-primary-50)] text-[var(--color-primary-700)] px-2.5 py-1 rounded-full font-medium ring-1 ring-[var(--color-primary-600)]/20">
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                      </svg>
                      {e.team}
                    </span>
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
