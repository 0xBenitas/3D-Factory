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

export const repairModel = (id, mode = 'auto') =>
  request(`/api/models/${id}/repair`, {
    method: 'POST',
    body: { mode },
  })

export const suggestSmartRegen = (id) =>
  request(`/api/models/${id}/regen-smart-suggest`, { method: 'POST' })

// ---------------------------------------------------------------------- //
// Recettes (Phase 1.8)
// ---------------------------------------------------------------------- //

export const listRecipes = () => request('/api/recipes')

export const createRecipe = (payload) =>
  request('/api/recipes', { method: 'POST', body: payload })

export const updateRecipe = (id, patch) =>
  request(`/api/recipes/${id}`, { method: 'PUT', body: patch })

export const deleteRecipe = (id) =>
  request(`/api/recipes/${id}`, { method: 'DELETE' })

export const incrementRecipeUsage = (id) =>
  request(`/api/recipes/${id}/use`, { method: 'POST' })

// ---------------------------------------------------------------------- //
// Batch (Phase 1.9)
// ---------------------------------------------------------------------- //

export const createBatch = (payload) =>
  request('/api/batch', { method: 'POST', body: payload })

export const listBatches = ({ signal } = {}) => request('/api/batch', { signal })

export const getBatch = (id, { signal } = {}) =>
  request(`/api/batch/${id}`, { signal })

export const cancelBatch = (id) =>
  request(`/api/batch/${id}/cancel`, { method: 'POST' })

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

// ---------------------------------------------------------------------- //
// Bibliothèque de prompts versionnée (Phase 1.5)
// ---------------------------------------------------------------------- //

export const listPromptLibrary = ({ brickId = null, category = null } = {}) => {
  const qs = new URLSearchParams()
  if (brickId) qs.set('brick_id', brickId)
  if (category) qs.set('category', category)
  const path = `/api/prompts/library${qs.toString() ? `?${qs}` : ''}`
  return request(path)
}

export const createPrompt = (payload) =>
  request('/api/prompts/library', { method: 'POST', body: payload })

export const updatePromptInLibrary = (id, patch) =>
  request(`/api/prompts/library/${id}`, { method: 'PUT', body: patch })

export const deletePrompt = (id) =>
  request(`/api/prompts/library/${id}`, { method: 'DELETE' })

export const activatePrompt = (id) =>
  request(`/api/prompts/library/${id}/activate`, { method: 'POST' })
