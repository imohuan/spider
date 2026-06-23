import axios from 'axios'

export const http = axios.create({ baseURL: '/api', timeout: 15000 })

http.interceptors.response.use(
  (r) => r.data,
  (err) => {
    // 提取后端返回的具体错误信息
    const data = err.response?.data
    if (data) {
      const msg = data.error || data.message || data.detail || err.message
      err.message = msg
    }
    return Promise.reject(err)
  }
)

export const api = {
  get: <T = any>(url: string, params?: any, config?: any) => http.get<any, T>(url, { params, ...config }),
  post: <T = any>(url: string, data?: any, config?: any) => http.post<any, T>(url, data, config),
  put: <T = any>(url: string, data?: any) => http.put<any, T>(url, data),
  del: <T = any>(url: string) => http.delete<any, T>(url),
}
