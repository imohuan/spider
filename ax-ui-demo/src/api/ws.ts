import { io, type Socket } from 'socket.io-client'
import { ref, onMounted, onBeforeUnmount } from 'vue'

let socket: Socket | null = null

export function getSocket(): Socket {
  if (!socket) {
    socket = io({ path: '/socket.io', transports: ['websocket', 'polling'] })
  }
  return socket
}

export function useWebSocket() {
  const connected = ref(false)
  const logs = ref<Array<{ level: string; module: string; message: string; timestamp: string }>>([])

  let s: Socket
  onMounted(() => {
    s = getSocket()
    // 如果挂载时 socket 已经连接，立即同步状态（否则 connect 事件不会再触发）
    if (s.connected) connected.value = true
    s.on('connect', () => { connected.value = true })
    s.on('disconnect', () => { connected.value = false })
    s.on('log', (data) => {
      logs.value.push(data)
      if (logs.value.length > 500) logs.value.shift()
    })
  })
  onBeforeUnmount(() => {
    s?.off('connect'); s?.off('disconnect'); s?.off('log')
  })

  return { connected, logs }
}
