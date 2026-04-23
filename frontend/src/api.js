// Wrapper fetch() avec credentials + gestion d'erreur centralisée.
// Basic Auth : le navigateur garde les creds en cache après la popup initiale,
// donc `credentials: 'same-origin'` suffit à les transmettre.

export class ApiError extends Error {
  constructor(status, detail, payload) {
    super(`${status}: ${detail}`)
    this.status = status
    this.detail = detail
    this.payload = payload
  }
}

// Extrait un message lisible du champ `detail` de FastAPI qui peut prendre
// trois formes :
//  - string                → HTTPException(detail="...")
//  - [{msg, loc, type}, …] → erreur de validation Pydantic
//  - {msg|message, …}      → exception custom sérialisée en dict
// On renvoie null si rien d'utilisable pour qu'on puisse retomber sur
// `resp.statusText`.
function extractDetail(payload) {
  if (!payload) return null
  const d = payload.detail
  if (d == null) return null
  if (typeof d === 'string') return d
  if (Array.isArray(d)) {
    const first = d[0]
    if (!first) return null
    return first.msg || first.message || JSON.stringify(first)
  }
  if (typeof d === 'object') {
    return d.msg || d.message || JSON.stringify(d)
  }
  return String(d)
}

async function request(path, { method = 'GET', body = null, headers = {}, signal = null } = {}) {
  const opts = {
    method,
    credentials: 'same-origin',
    headers: { ...headers },
  }
  if (signal) opts.signal = signal
  if (body !== null && body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const resp = await fetch(path, opts)
  const isJson = (resp.headers.get('content-type') || '').includes('application/json')
  const payload = isJson ? await resp.json().catch(() => null) : null
  if (!resp.ok) {
    const detail = extractDetail(payload) || resp.statusText || 'Request failed'
    throw new ApiError(resp.status, detail, payload)
  }
  return payload
}

// ---------------------------------------------------------------------- //
// Pipeline
// ---------------------------------------------------------------------- //

export const startPipeline = (payload) =>
  request('/api/pipeline/run', { method: 'POST', body: payload })

export const getPipelineStatus = (modelId, { signal } = {}) =>
  request(`/api/pipeline/status/${modelId}`, { signal })

export const cancelPipeline = (modelId) =>
  request(`/api/pipeline/${modelId}/cancel`, { method: 'POST' })

// ---------------------------------------------------------------------- //
// Models
// ---------------------------------------------------------------------- //

export const listModels = ({ validation = 'all', sort = 'date_desc', signal = null } = {}) => {
  const qs = new URLSearchParams({ validation, sort }).toString()
  return request(`/api/models?${qs}`, { signal })
}

export const getModel = (id, { signal } = {}) => request(`/api/models/${id}`, { signal })

export const getGlbUrl = (id) => `/api/models/${id}/glb`

export const getInputImageUrl = (id) => `/api/models/${id}/input-image`

export const getThumbUrl = (id) => `/api/models/${id}/thumb`

export const validateModel = (id, action, reason = null) =>
  request(`/api/models/${id}/validate`, {
    method: 'PUT',
    body: { action, reason },
  })

export const regenerateModel = (id, promptOverride = null) =>
  request(`/api/models/${id}/regenerate`, {
    method: 'POST',
    body: { prompt_override: promptOverride },
  })

export const remeshModel = (id, targetPolycount = 30000) =>
  request(`/api/models/${id}/remesh`, {
    method: 'POST',
    body: { target_polycount: targetPolycount },
  })

// ---------------------------------------------------------------------- //
// Services
// ---------------------------------------------------------------------- //

export const listEngines = () => request('/api/engines')

export const listImageEngines = () => request('/api/image-engines')

export const listTemplates = () => request('/api/templates')

// ---------------------------------------------------------------------- //
// Exports
// ---------------------------------------------------------------------- //

export const generateExport = (payload) =>
  request('/api/exports/generate', { method: 'POST', body: payload })

export const patchExport = (id, patch) =>
  request(`/api/exports/${id}`, { method: 'PATCH', body: patch })

export const listExports = (modelId) =>
  request(`/api/exports?model_id=${modelId}`)

export const getExportZipUrl = (id) => `/api/exports/${id}/zip`

export const getExportListingUrl = (id) => `/api/exports/${id}/listing`

// ---------------------------------------------------------------------- //
// Settings + Stats
// ---------------------------------------------------------------------- //

export const getSettings = () => request('/api/settings')

export const updateSettings = (patch) =>
  request('/api/settings', { method: 'PUT', body: patch })

export const getStats = () => request('/api/stats')

export const getCostHints = () => request('/api/costs/hints')

export const getCredits = ({ refresh = false } = {}) =>
  request(`/api/credits${refresh ? '?refresh=1' : ''}`)

// ---------------------------------------------------------------------- //
// Prompts (system prompts éditables par brique)
// ---------------------------------------------------------------------- //

export const listPrompts = () => request('/api/prompts')

export const updatePrompt = (brickId, override) =>
  request(`/api/prompts/${brickId}`, {
    method: 'PUT',
    body: { override },
  })

export const resetPrompt = (brickId) =>
  request(`/api/prompts/${brickId}`, { method: 'DELETE' })
