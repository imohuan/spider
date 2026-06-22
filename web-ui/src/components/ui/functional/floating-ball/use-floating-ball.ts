import { computed, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import type { DockSide, FloatingBallPrefs } from './types'

const DRAG_MOVE_THRESHOLD = 4
const CLOSE_SIZE = 16
const TOOLBAR_LEAVE_DELAY_MS = 200

export function useFloatingBall(
  prefs: Ref<FloatingBallPrefs>,
  options?: { settingsOpen?: Ref<boolean> },
  sizeNormal = 36,
  sizeSmall = 30,
  gap = 8,
) {
  const expanded = ref(false)
  const visible = computed(() => !prefs.value.hidden)
  const shrunk = computed(() => prefs.value.shrunk)
  const dockSide = ref<DockSide>('right')
  const isDragging = ref(false)
  const dragMoved = ref(false)

  const closeSide = computed<'left' | 'right'>(() => {
    if (dockSide.value === 'left' || dockSide.value === 'right') {
      return dockSide.value
    }
    const centerX = pos.value.x + btnSize.value / 2
    return centerX < window.innerWidth / 2 ? 'left' : 'right'
  })

  const pos = ref({ x: 16, y: 200 })
  const dragOffset = ref({ x: 0, y: 0 })
  const pointerStart = ref({ x: 0, y: 0 })
  let hoverLeaveTimer: ReturnType<typeof setTimeout> | null = null

  const btnSize = computed(() => (shrunk.value ? sizeSmall : sizeNormal))

  const toolbarHitAreaStyle = computed(() => {
    if (!expanded.value) return {}
    return closeSide.value === 'right'
      ? { paddingLeft: '12px' }
      : { paddingRight: '12px' }
  })

  const collapsedHeight = computed(() => btnSize.value)
  const expandedHeight = computed(() => btnSize.value * 2 + gap)
  const stackHeight = computed(() => (expanded.value ? expandedHeight.value : collapsedHeight.value))

  const toolbarStyle = computed(() => {
    if (dockSide.value === 'left') {
      return { left: '0px', top: `${pos.value.y}px`, right: 'auto' }
    }
    if (dockSide.value === 'right') {
      return { right: '0px', top: `${pos.value.y}px`, left: 'auto' }
    }
    return { left: `${pos.value.x}px`, top: `${pos.value.y}px`, right: 'auto' }
  })

  function btnTop(index: 0 | 1) {
    if (index === 0) return 0
    return btnSize.value + gap
  }

  const closeTop = computed(() => {
    const mainCenter = btnTop(0) + btnSize.value / 2
    const settingsCenter = btnTop(1) + btnSize.value / 2
    return (mainCenter + settingsCenter) / 2 - CLOSE_SIZE / 2
  })

  function syncPosFromDock() {
    if (dockSide.value === 'left') {
      pos.value.x = 0
    } else if (dockSide.value === 'right') {
      pos.value.x = Math.max(0, window.innerWidth - btnSize.value)
    }
  }

  function onPointerDown(event: PointerEvent) {
    const target = event.target as HTMLElement
    if (target.closest('[data-no-drag]')) return

    isDragging.value = true
    dragMoved.value = false
    pointerStart.value = { x: event.clientX, y: event.clientY }

    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
    dragOffset.value = {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    }

    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  }

  function onPointerMove(event: PointerEvent) {
    if (!isDragging.value) return
    if (!dragMoved.value) {
      const dx = Math.abs(event.clientX - pointerStart.value.x)
      const dy = Math.abs(event.clientY - pointerStart.value.y)
      if (dx <= DRAG_MOVE_THRESHOLD && dy <= DRAG_MOVE_THRESHOLD) return

      dragMoved.value = true
      syncPosFromDock()
      dockSide.value = 'none'
    }

    const maxX = window.innerWidth - btnSize.value
    const maxY = window.innerHeight - stackHeight.value

    pos.value = {
      x: Math.max(0, Math.min(event.clientX - dragOffset.value.x, maxX)),
      y: Math.max(0, Math.min(event.clientY - dragOffset.value.y, maxY)),
    }
  }

  function onPointerUp(event: PointerEvent) {
    if (!isDragging.value) return
    isDragging.value = false
    ;(event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId)

    if (dragMoved.value) {
      const centerX = pos.value.x + btnSize.value / 2
      dockSide.value = centerX < window.innerWidth / 2 ? 'left' : 'right'
    }
  }

  function onToolbarEnter() {
    if (!visible.value || isDragging.value) return
    if (hoverLeaveTimer) {
      clearTimeout(hoverLeaveTimer)
      hoverLeaveTimer = null
    }
    expanded.value = true
  }

  function onToolbarLeave() {
    if (isDragging.value || options?.settingsOpen?.value) return
    if (hoverLeaveTimer) clearTimeout(hoverLeaveTimer)
    hoverLeaveTimer = setTimeout(() => {
      expanded.value = false
      hoverLeaveTimer = null
    }, TOOLBAR_LEAVE_DELAY_MS)
  }

  watch(
    () => options?.settingsOpen?.value,
    (open) => {
      if (open) {
        if (hoverLeaveTimer) {
          clearTimeout(hoverLeaveTimer)
          hoverLeaveTimer = null
        }
        expanded.value = true
      }
    },
  )

  onMounted(() => {
    pos.value.y = Math.max(100, window.innerHeight * 0.35)
  })

  onUnmounted(() => {
    isDragging.value = false
    if (hoverLeaveTimer) {
      clearTimeout(hoverLeaveTimer)
      hoverLeaveTimer = null
    }
  })

  return {
    expanded,
    visible,
    shrunk,
    dockSide,
    isDragging,
    dragMoved,
    closeSide,
    pos,
    btnSize,
    stackHeight,
    toolbarStyle,
    toolbarHitAreaStyle,
    btnTop,
    closeTop,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onToolbarEnter,
    onToolbarLeave,
  }
}
