const API = import.meta.env.VITE_API_URL || ''

function getCSRFToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/)
  return match ? decodeURIComponent(match[1]) : ''
}

async function request(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const headers = { 'Content-Type': 'application/json', ...options.headers }
  if (method !== 'GET') {
    headers['X-CSRFToken'] = getCSRFToken()
  }
  const res = await fetch(`${API}${path}`, {
    headers,
    credentials: 'include',
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

export const api = {
  getSession: () => request('/api/auth/session/'),
  logout: () => request('/api/auth/logout/', { method: 'POST' }),
  getFathomOAuthUrl: () => request('/api/fathom/oauth/url/'),
  fathomOAuthCallback: (code) =>
    request('/api/fathom/oauth/callback/', { method: 'POST', body: JSON.stringify({ code }) }),

  getDashboardStats: () => request('/api/dashboard/stats/'),

  getMeetings: () => request('/api/meetings/'),
  getMeeting: (id) => request(`/api/meetings/${id}/`),
  createMeetingWithLink: (data) =>
    request('/api/meetings/create_with_link/', { method: 'POST', body: JSON.stringify(data) }),
  checkFathomForMeeting: (id) =>
    request(`/api/meetings/${id}/check_fathom/`, { method: 'POST' }),
  generateTasksForMeeting: (id) =>
    request(`/api/meetings/${id}/generate_tasks/`, { method: 'POST' }),

  getTasks: () => request('/api/tasks/'),
  updateTaskStatus: (id, status) =>
    request(`/api/tasks/${id}/status/`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  updateTask: (id, data) =>
    request(`/api/tasks/${id}/`, { method: 'PATCH', body: JSON.stringify(data) }),
  getTaskComments: (id) => request(`/api/tasks/${id}/comments/`),
  addTaskComment: (id, data) =>
    request(`/api/tasks/${id}/comments/`, { method: 'POST', body: JSON.stringify(data) }),
  createTask: (data) =>
    request('/api/tasks/', { method: 'POST', body: JSON.stringify(data) }),

  getEmployees: () => request('/api/employees/'),
  createEmployee: (data) =>
    request('/api/employees/', { method: 'POST', body: JSON.stringify(data) }),
  deleteEmployee: (id) =>
    request(`/api/employees/${id}/`, { method: 'DELETE' }),

  getFathomConfig: () => request('/api/fathom/config/'),
  saveFathomConfig: (data) =>
    request('/api/fathom/config/', { method: 'POST', body: JSON.stringify(data) }),
  syncFathom: () =>
    request('/api/fathom/sync/', { method: 'POST' }),
  generateAITasks: () =>
    request('/api/tasks/generate-ai/', { method: 'POST' }),
}
