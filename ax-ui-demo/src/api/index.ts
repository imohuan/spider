import { api } from './http'

export const dashboardApi = {
  getMetrics: () => api.get('/dashboard/metrics'),
  getProgress: (hours = 24) => api.get('/dashboard/progress', { hours }),
  getRecent: (limit = 20) => api.get('/dashboard/recent', { limit }),
}

export const crawlerApi = {
  start: () => api.post('/crawler/start'),
  pause: () => api.post('/crawler/pause'),
  stop: () => api.post('/crawler/stop'),
  status: () => api.get('/crawler/status'),
}

export const queueApi = {
  stats: () => api.get('/queue/stats'),
  list: (p: { page?: number; size?: number; status?: string; parser?: string; search?: string }) => api.get('/queue', p),
  retry: (id: number) => api.post(`/queue/${id}/retry`),
  retryBlocked: () => api.post('/queue/retry-blocked'),
  create: (payload: { url: string; parser_name?: string; fetch_mode?: string; request_config?: Record<string, any> }) => api.post('/queue', payload),
}

export const dataApi = {
  tables: () => api.get('/data/tables'),
  query: (table: string, p: { page?: number; size?: number }) => api.get(`/data/${table}`, p),
  exportUrl: (table: string) => `/api/data/${table}/export?format=csv`,
}

export const proxyApi = {
  stats: () => api.get('/proxy/stats'),
  list: (p: { page?: number; size?: number; status?: string }) => api.get('/proxy', p),
  fetch: (num = 10) => api.post(`/proxy/fetch?num=${num}`),
  healthCheck: () => api.post('/proxy/health-check'),
  kill: (id: number) => api.del(`/proxy/${id}`),
}

export const captchaApi = {
  stats: () => api.get('/captcha/stats'),
  list: (p: { page?: number; size?: number }) => api.get('/captcha', p),
}

export const configApi = {
  getAll: () => api.get('/config'),
  update: (data: Record<string, string>) => api.put('/config', data),
  reset: () => api.post('/config/reset'),
  /** 测试 URL — browser 模式或 http 模式 */
  testUrl: (payload: {
    url: string
    mode: 'browser' | 'http'
    method?: string
    headers?: Record<string, string>
    cookies?: string
    body_type?: string
    body_content?: string
  }) => api.post('/config/test-url', payload),
}

export const logsApi = {
  getAll: () => api.get('/logs', { size: -1 }),
}

export const parsersApi = {
  list: () => api.get('/parsers'),
  toggle: (name: string) => api.post(`/parsers/${name}/toggle`),
  rescan: () => api.post('/parsers/rescan'),
  test: (name: string, url: string) => api.post(`/parsers/${name}/test`, { url }),
}
