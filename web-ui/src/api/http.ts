import axios from 'axios'

export const http = axios.create({ baseURL: '/api', timeout: 15000 })

http.interceptors.response.use(
  (r) => r.data,
  (err) => Promise.reject(err)
)

export const api = {
  get: <T = any>(url: string, params?: any) => http.get<any, T>(url, { params }),
  post: <T = any>(url: string, data?: any) => http.post<any, T>(url, data),
  put: <T = any>(url: string, data?: any) => http.put<any, T>(url, data),
  del: <T = any>(url: string) => http.delete<any, T>(url),
}
