export type Project = { id: string; name: string; kind: string; revision: number; data: string; created_at: string; updated_at: string }
export const parseData = (p: Project): Record<string, unknown> => { try { return JSON.parse(p.data || '{}') } catch { return {} } }
export const BASE = (import.meta.env.BASE_URL || '/').replace(/\/$/, '')
export const withBase = (path: string) => (path.startsWith('/') ? `${BASE}${path}` : path)
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(withBase(path), { credentials: 'include', headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) }, ...init })
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m } catch { /* keep */ } throw new Error(m) }
  return r.json() as Promise<T>
}
export const api = {
  me: () => req<{ user: { id: number; email: string }; plan: unknown }>('/api/auth/me'),
  login: (email: string, password: string) => req('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  register: (email: string, password: string) => req('/api/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) }),
  logout: () => req('/api/auth/logout', { method: 'POST', body: '{}' }),
  listProjects: () => req<{ projects: Project[] }>('/api/projects'),
  createProject: (name: string, kind = 'video', data: Record<string, unknown> = {}) => req<Project>('/api/projects', { method: 'POST', body: JSON.stringify({ name, kind, data }) }),
  getProject: (id: string) => req<Project>(`/api/projects/${id}`),
  patchProject: (id: string, name: string | undefined, data: Record<string, unknown>, revision: number) => req<Project>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify({ name, data, revision }) }),
  duplicate: (id: string) => req<Project>(`/api/projects/${id}/duplicate`, { method: 'POST', body: '{}' }),
  remove: (id: string) => req(`/api/projects/${id}`, { method: 'DELETE' }),
  timings: (id: string, mode: string, total: number, script: string, locked: Record<string, number>) => req<{ durations: number[] }>(`/api/projects/${id}/timings`, { method: 'POST', body: JSON.stringify({ mode, total, script, locked }) }),
  putSubtitles: (id: string, content: string, format: string) => req<{ cues: unknown[] }>(`/api/projects/${id}/subtitles`, { method: 'PUT', body: JSON.stringify({ content, format }) }),
  render: (id: string, durations: number[]) => req<{ job_id: string }>(`/api/projects/${id}/render`, { method: 'POST', body: JSON.stringify({ durations, resolution_w: 1920, resolution_h: 1080, fps: 30 }) }),
  job: (id: string) => req<{ status: string; status_pt: string; progress: number; message: string; error: string | null; download_url: string | null }>(`/api/jobs/${id}`),
  cancelJob: (id: string) => req(`/api/jobs/${id}`, { method: 'DELETE' }),
  jobs: () => req<{ jobs: Record<string, unknown>[] }>('/api/jobs'),
  exports: () => req<{ exports: Record<string, unknown>[] }>('/api/exports'),
  prefs: () => req<Record<string, unknown>>('/api/preferences'),
  putPref: (key: string, value: unknown) => req(`/api/preferences/${key}`, { method: 'PUT', body: JSON.stringify({ value }) }),
  studioUploadPdf: async (id: string, slot: number, pdf: File) => {
    const fd = new FormData(); fd.append('pdf_file', pdf)
    const r = await fetch(withBase(`/api/projects/${id}/studio/pdfs/${slot}`), { method: 'POST', credentials: 'include', body: fd })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Falha no envio do PDF')
    return r.json() as Promise<{ slot: number; page_count: number; title: string }>
  },
  studioConvert: async (id: string, blob: Blob) => {
    const fd = new FormData(); fd.append('recording', blob, 'gravacao.webm')
    const r = await fetch(withBase(`/api/projects/${id}/studio/recording`), { method: 'POST', credentials: 'include', body: fd })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Falha na conversão')
    return r.json() as Promise<{ download_url: string }>
  },
  upload: async (pdf: File, audio: File) => {
    const fd = new FormData(); fd.append('pdf_file', pdf); fd.append('audio_file', audio)
    const r = await fetch(withBase('/api/upload'), { method: 'POST', credentials: 'include', body: fd })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Falha no envio')
    return r.json() as Promise<{ project_id: string; page_count: number; audio_duration: number; slides: { index: number; thumbnail_url: string; duration: number }[] }>
  },
}
export const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
