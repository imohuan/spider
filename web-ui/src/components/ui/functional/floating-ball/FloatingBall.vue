<script setup lang="ts">
import { computed, ref, toRef, watch } from 'vue'
import { onKeyStroke } from '@vueuse/core'
import { useFloatingBall } from './use-floating-ball'
import type { FloatingBallPrefs, FloatingBallTheme } from './types'
import { AxButton } from '../..'

const props = withDefaults(
  defineProps<{
    prefs: FloatingBallPrefs
    settingsOpen?: boolean
  }>(),
  {
    settingsOpen: false,
  },
)

const emit = defineEmits<{
  openSettings: []
  openBallSettings: []
  mainClick: []
  savePrefs: [prefs: FloatingBallPrefs]
}>()

const prefsRef = toRef(props, 'prefs')

const {
  expanded,
  visible,
  dockSide,
  isDragging,
  dragMoved,
  closeSide,
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
} = useFloatingBall(prefsRef, { settingsOpen: toRef(props, 'settingsOpen') })

// ---- Settings Dialog (using AxDialog) ----
const showBallSettings = ref(false)

function openBallSettingsDialog() {
  showBallSettings.value = true
}

// Draft prefs for settings form
const draftPrefs = ref<FloatingBallPrefs>({
  shrunk: props.prefs.shrunk,
  hidden: props.prefs.hidden,
  theme: props.prefs.theme,
  label: props.prefs.label,
})

function initDraft() {
  draftPrefs.value = {
    shrunk: props.prefs.shrunk,
    hidden: props.prefs.hidden,
    theme: props.prefs.theme,
    label: props.prefs.label,
  }
}

function saveSettings() {
  emit('savePrefs', { ...draftPrefs.value })
  showBallSettings.value = false
}

// Init draft when dialog opens
watch(showBallSettings, (open) => {
  if (open) initDraft()
})

onKeyStroke('Escape', () => {
  if (showBallSettings.value) showBallSettings.value = false
})

// ---- Computed classes ----
const slideOffset = computed(() => 0)
const isDarkTheme = computed(() => props.prefs.theme === 'dark')
const label = computed(() => props.prefs.label ?? 'FB')


const stackClass = computed(() => {
  const base = 'relative overflow-visible cursor-grab transition-[height,transform] duration-300 ease-out'
  const drag = isDragging.value ? ' cursor-grabbing' : ''
  const exp = expanded.value ? ' !translate-x-0' : ''
  return base + drag + exp
})

const fabBase =
  'absolute left-0 m-0 box-border flex items-center justify-center rounded-full border-0 p-0 outline-none transition-[opacity,box-shadow,background-color,border-color] duration-200 ease-out [-webkit-tap-highlight-color:transparent]'

const fabSoftClasses = `${fabBase} z-[2] cursor-pointer bg-transparent shadow-none`

const settingsIconClasses =
  'flex items-center justify-center rounded-full border border-gray-100/90 bg-white text-ball shadow-md shadow-black/10 [&_svg]:size-[18px]'

const fabMainClasses = computed(() => {
  const drag = isDragging.value ? 'cursor-grabbing' : 'cursor-grab'
  let radius = 'rounded-full'
  if (dockSide.value === 'left') radius = 'rounded-l-md rounded-r-full'
  else if (dockSide.value === 'right') radius = 'rounded-r-md rounded-l-full'

  if (isDarkTheme.value) {
    return `${fabBase} z-[2] shadow-md border border-white/12 bg-zinc-800 shadow-black/40 ${drag} ${radius}`
  }
  return `${fabBase} z-[2] shadow-md border border-gray-100/90 bg-white shadow-black/10 ${drag} ${radius}`
})

const fabCloseClasses = computed(() => {
  const side = closeSide.value === 'left' ? 'right-[-8px] left-auto' : 'left-[-8px]'
  return `${fabBase} z-[3] !size-4 cursor-pointer bg-zinc-400 text-white shadow-sm hover:bg-zinc-500 [&_svg]:size-2 ${side}`
})

function fabStyle(slot: 'main' | 'settings') {
  const index = slot === 'main' ? 0 : 1
  const show = !expanded.value ? slot === 'main' : true
  const hiddenSideOffset = 12
  const settingsTranslateX =
    slot === 'settings' && !expanded.value
      ? dockSide.value === 'left'
        ? -hiddenSideOffset
        : hiddenSideOffset
      : 0
  const dockInset = slot === 'main' && dockSide.value !== 'none' ? 2 : 0
  const mainLeft = slot === 'main' && dockSide.value === 'right' ? -dockInset : 0

  return {
    top: `${btnTop(index)}px`,
    width: `${btnSize.value + dockInset}px`,
    height: `${btnSize.value}px`,
    left: `${mainLeft}px`,
    opacity: show ? 1 : 0,
    pointerEvents: show ? ('auto' as const) : ('none' as const),
    transform: `translateX(${settingsTranslateX}px)`,
    transition: 'opacity 220ms ease, transform 220ms ease',
  } as const
}

function onMainPointerUp() {
  if (!dragMoved.value) emit('mainClick')
}

function settingsIconStyle() {
  return { width: `${btnSize.value}px`, height: `${btnSize.value}px` } as const
}

function innerBallStyle() {
  const innerSize = Math.max(0, btnSize.value - 6)
  if (dockSide.value === 'left') {
    return { width: `${innerSize}px`, height: `${innerSize}px`, marginRight: '3px', marginLeft: 'auto' } as const
  }
  if (dockSide.value === 'right') {
    return { width: `${innerSize}px`, height: `${innerSize}px`, marginLeft: '3px', marginRight: 'auto' } as const
  }
  return { width: `${innerSize}px`, height: `${innerSize}px` } as const
}

function themeCardClass(theme: FloatingBallTheme) {
  const selected = draftPrefs.value.theme === theme
  return selected
    ? 'border-primary bg-surface-container-low'
    : 'border-outline-variant bg-white hover:border-outline'
}
</script>

<template>
  <!-- The floating ball -->
  <Transition
    enter-active-class="transition-opacity duration-200"
    leave-active-class="transition-opacity duration-200"
    enter-from-class="opacity-0"
    leave-to-class="opacity-0"
  >
    <div
      v-if="visible"
      class="fixed z-[9999] touch-none select-none"
      :style="[toolbarStyle, toolbarHitAreaStyle]"
      @mouseenter="onToolbarEnter"
      @mouseleave="onToolbarLeave"
    >
      <div
        :class="stackClass"
        :style="{
          width: `${btnSize}px`,
          height: `${stackHeight}px`,
          transform: `translateX(${slideOffset}px)`,
        }"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
      >
        <!-- Main ball button -->
        <button
          type="button"
          :class="fabMainClasses"
          :style="fabStyle('main')"
          aria-label="Floating Ball"
          @pointerup="onMainPointerUp"
        >
          <span
            class="relative flex items-center justify-center rounded-full bg-gradient-to-br from-ball-light to-ball text-white shadow-sm shadow-ball/40"
            :style="innerBallStyle()"
            aria-hidden="true"
          >
            <span
              class="font-extrabold italic leading-none tracking-tight text-white"
              :class="prefs.shrunk ? 'text-[9px]' : 'text-[11px]'"
            >{{ label }}</span>
          </span>
        </button>

        <!-- Settings button -->
        <button
          type="button"
          data-no-drag
          :class="fabSoftClasses"
          :style="fabStyle('settings')"
          aria-label="设置"
          @click.stop="emit('openSettings')"
        >
          <span
            :class="settingsIconClasses"
            :style="settingsIconStyle()"
            aria-hidden="true"
          >
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M6 9h12M8 14h8M10 19h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
              <circle cx="6" cy="9" r="1.5" fill="currentColor" />
              <circle cx="16" cy="14" r="1.5" fill="currentColor" />
              <circle cx="12" cy="19" r="1.5" fill="currentColor" />
            </svg>
          </span>
        </button>

        <!-- Close / ball settings button -->
        <button
          v-show="expanded"
          type="button"
          data-no-drag
          :class="fabCloseClasses"
          :style="{ top: `${closeTop}px` }"
          aria-label="悬浮球设置"
          @click="openBallSettingsDialog"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  </Transition>

  <AxDialog
    v-model="showBallSettings"
    title="悬浮球设置"
    icon="tune"
    max-width="max-w-md"
    @close="showBallSettings = false"
  >
    <div class="space-y-ax-md">
      <div>
        <h2 class="font-headline-sm text-headline-sm text-primary">外观与行为</h2>
        <p class="font-body-sm text-body-sm text-on-surface-variant mt-1">配置悬浮球的显示样式与交互选项。</p>
      </div>

      <section class="rounded-lg border border-outline-variant bg-white p-ax-md">
        <label class="font-label-md text-label-md font-semibold text-primary">主题样式</label>
        <p class="font-body-sm text-body-sm text-on-surface-variant mt-ax-xs mb-ax-sm">选择悬浮球的外观配色方案</p>
        <div class="grid grid-cols-2 gap-ax-sm">
          <button
            type="button"
            :class="themeCardClass('light')"
            class="flex flex-col items-center gap-ax-sm rounded-lg border p-ax-md transition-all duration-200"
            aria-label="亮色"
            @click="draftPrefs.theme = 'light'"
          >
            <span class="flex size-9 items-center justify-center rounded-full border border-gray-100/90 bg-white shadow-sm shadow-black/10">
              <span
                class="flex size-7 items-center justify-center rounded-full bg-gradient-to-br from-ball-light to-ball text-[10px] font-extrabold italic text-white shadow-sm shadow-ball/40"
              >FB</span>
            </span>
            <span class="font-label-md text-label-md text-primary">亮色</span>
          </button>
          <button
            type="button"
            :class="themeCardClass('dark')"
            class="flex flex-col items-center gap-ax-sm rounded-lg border p-ax-md transition-all duration-200"
            aria-label="暗色"
            @click="draftPrefs.theme = 'dark'"
          >
            <span class="flex size-9 items-center justify-center rounded-full border border-white/12 bg-zinc-800 shadow-sm shadow-black/40">
              <span
                class="flex size-7 items-center justify-center rounded-full bg-gradient-to-br from-ball-light to-ball text-[10px] font-extrabold italic text-white shadow-sm shadow-ball/40"
              >FB</span>
            </span>
            <span class="font-label-md text-label-md text-primary">暗色</span>
          </button>
        </div>
      </section>

      <section class="divide-y divide-outline-variant/40 rounded-lg border border-outline-variant bg-white">
        <div class="flex items-center justify-between p-ax-md">
          <div class="flex flex-col gap-ax-xs">
            <label for="ball-shrunk" class="font-label-md text-label-md font-semibold text-primary">缩小悬浮球</label>
            <p class="font-body-sm text-body-sm text-on-surface-variant">切换更小的悬浮球尺寸，节省屏幕空间</p>
          </div>
          <button
            id="ball-shrunk"
            type="button"
            role="switch"
            :aria-checked="draftPrefs.shrunk"
            :class="draftPrefs.shrunk ? 'bg-primary' : 'bg-outline'"
            class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200 focus:outline-none"
            @click="draftPrefs.shrunk = !draftPrefs.shrunk"
          >
            <span
              :class="draftPrefs.shrunk ? 'translate-x-4' : 'translate-x-0'"
              class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out"
            />
          </button>
        </div>

        <div class="flex items-center justify-between p-ax-md">
          <div class="flex flex-col gap-ax-xs">
            <label for="ball-hidden" class="font-label-md text-label-md font-semibold text-primary">隐藏悬浮球</label>
            <p class="font-body-sm text-body-sm text-on-surface-variant">完全隐藏悬浮球，可在设置中恢复显示</p>
          </div>
          <button
            id="ball-hidden"
            type="button"
            role="switch"
            :aria-checked="draftPrefs.hidden"
            :class="draftPrefs.hidden ? 'bg-primary' : 'bg-outline'"
            class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200 focus:outline-none"
            @click="draftPrefs.hidden = !draftPrefs.hidden"
          >
            <span
              :class="draftPrefs.hidden ? 'translate-x-4' : 'translate-x-0'"
              class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out"
            />
          </button>
        </div>
      </section>
    </div>

    <template #footer="{ close }">
      <AxButton size="lg" variant="outline" @click="close">取消</AxButton>
      <AxButton size="lg" @click="saveSettings()">保存</AxButton>
    </template>
  </AxDialog>
</template>
