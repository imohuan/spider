/** 测试 URL 历史记录管理 — localStorage 持久化。 */
import { ref, computed } from 'vue'

const STORAGE_KEY = 'crawler_test_history'

export interface TestHistoryItem {
  id: string
  url: string
  mode: 'browser' | 'http'
  method: 'GET' | 'POST' | 'PUT'
  headers: string       // JSON string or key:value pairs
  cookies: string
  bodyType: 'none' | 'raw' | 'form-data' | 'json'
  bodyContent: string
  label?: string        // 自动生成的短标签
  createdAt: number     // timestamp
}

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
}

function loadFromStorage(): TestHistoryItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveToStorage(items: TestHistoryItem[]): void {
  try {
    // 最多保留 50 条
    const trimmed = items.slice(0, 50)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed))
  } catch {
    // localStorage 满则清空旧记录
  }
}

function makeLabel(url: string, method: string): string {
  try {
    const u = new URL(url)
    return `${method} ${u.hostname}${u.pathname.slice(0, 30)}`
  } catch {
    return `${method} ${url.slice(0, 40)}`
  }
}

export function useTestHistory() {
  const items = ref<TestHistoryItem[]>(loadFromStorage())

  const options = computed(() =>
    items.value.map((h) => ({
      value: h.id,
      label: h.label || makeLabel(h.url, h.method),
    }))
  )

  /** 添加一条历史记录。返回新记录的 id。 */
  function add(item: Omit<TestHistoryItem, 'id' | 'label' | 'createdAt'>): string {
    const id = generateId()
    const entry: TestHistoryItem = {
      ...item,
      id,
      label: makeLabel(item.url, item.method),
      createdAt: Date.now(),
    }
    items.value.unshift(entry)
    saveToStorage(items.value)
    return id
  }

  /** 按 id 删除 */
  function remove(id: string): void {
    items.value = items.value.filter((h) => h.id !== id)
    saveToStorage(items.value)
  }

  /** 清空全部 */
  function clearAll(): void {
    items.value = []
    saveToStorage([])
  }

  /** 按 id 查找 */
  function getById(id: string): TestHistoryItem | undefined {
    return items.value.find((h) => h.id === id)
  }

  return { items, options, add, remove, clearAll, getById }
}
