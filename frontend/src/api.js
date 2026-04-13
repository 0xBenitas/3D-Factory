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

async function request(path, { method = 'GET', body = null, headers = {} } = {}) {
  const opts = {
    method,
    credentials: 'same-origin',
    headers: { ...headers },
  }
  if (body !== null && body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const resp = await fetch(path, opts)
  const isJson = (resp.headers.get('content-type') || '').includes('application/json')
  const payload = isJson ? await resp.json().catch(() => null) : null
  if (!resp.ok) {
    const detail =
      (payload && (payload.detail?.[0]?.msg || payload.detail)) ||
      resp.statusText ||
      'Request failed'
    throw new ApiError(resp.status, detail, payload)
  }
  return payload
}

// ---------------------------------------------------------------------- //
// Pipeline
// ---------------------------------------------------------------------- //

export const startPipeline = (payload) =>
  request('/api/pipeline/run', { method: 'POST', body: payload })

export const getPipelineStatus = (modelId) =>
  request(`/api/pipeline/status/${modelId}`)

// ---------------------------------------------------------------------- //
// Models
// ---------------------------------------------------------------------- //

export const listModels = ({ validation = 'all', sort = 'date_desc' } = {}) => {
  const qs = new URLSearchParams({ validation, sort }).toString()
  return request(`/api/models?${qs}`)
}

export const getModel = (id) => request(`/api/models/${id}`)

export const getGlbUrl = (id) => `/api/models/${id}/glb`

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
