<script setup lang="ts">
import { ref, computed, reactive, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useMagicKeys } from '@vueuse/core'
import { Toaster } from 'vue-sonner'
import { useNotify } from '../hooks/useNotify'
import ComponentsView from './ComponentsView.vue'
import SettingsDialog from './SettingsDialog.vue'
import DemoView from './DemoView.vue'
import type { AppSettings } from './SettingsView.vue'
import AxInput from '../AxInput.vue'

interface SubMenuItem {
  id: string
  name: string
  sectionId: string
}

interface NavItem {
  id: string
  name: string
  icon: string
  badge: string | null
  expanded: boolean
  subMenus: SubMenuItem[]
}

const activeTab = ref<string>('components')
const navItems = ref<NavItem[]>([
  {
    id: 'components',
    name: 'UI 组件列表',
    icon: 'widgets',
    badge: '15 个组件',
    expanded: true,
    subMenus: [
      { id: 'btn', name: 'Button 按钮', sectionId: 'section-btn' },
      { id: 'input', name: 'Input 输入框', sectionId: 'section-input' },
      { id: 'slider', name: 'Slider 滑块', sectionId: 'section-slider' },
      { id: 'switch', name: 'Switch 开关', sectionId: 'section-switch' },
      { id: 'alert', name: 'Alert 提示', sectionId: 'section-alert' },
      { id: 'select', name: 'Select 选择器', sectionId: 'section-select' },
      { id: 'tooltip', name: 'Tooltip 气泡', sectionId: 'section-tooltip' },
      { id: 'dropdown', name: 'Dropdown 下拉', sectionId: 'section-dropdown' },
      { id: 'popover', name: 'Popover 弹出', sectionId: 'section-popover' },
      { id: 'dialog', name: 'Dialog 对话框', sectionId: 'section-dialog' },
      { id: 'notify', name: 'Notify 通知', sectionId: 'section-notify' },
      { id: 'floating-ball', name: 'FloatingBall 悬浮球', sectionId: 'section-floating-ball' },
      { id: 'image', name: 'Image 图片', sectionId: 'section-image' },
      { id: 'json-viewer', name: 'JsonViewer JSON树', sectionId: 'section-json-viewer' },
      { id: 'image-viewer', name: 'ImageViewer 图片查看器', sectionId: 'section-image-viewer' },
    ],
  },
  {
    id: 'demo',
    name: 'DEMO 展示',
    icon: 'analytics',
    badge: null,
    expanded: false,
    subMenus: [
      { id: 'overview', name: 'Overview 控制台概览', sectionId: 'section-overview' },
      { id: 'metrics', name: 'Metrics 指标卡片', sectionId: 'section-metrics' },
      { id: 'nav-cards', name: 'Quick Nav 快捷导航', sectionId: 'section-nav-cards' },
      { id: 'settings-groups', name: 'Settings Groups 设置分组', sectionId: 'section-settings-groups' },
      { id: 'faq', name: 'FAQ 常见问题', sectionId: 'section-faq' },
      { id: 'activities', name: 'Activities 最近活动', sectionId: 'section-activities' },
    ],
  },
])

const activeTabTitle = computed(() => navItems.value.find((i) => i.id === activeTab.value)?.name ?? '工作台')

/** 手风琴单开：仅保留指定项的展开状态，其余全部收起 */
const setExpandedNav = (itemId: string, expanded: boolean) => {
  navItems.value.forEach((nav) => {
    nav.expanded = nav.id === itemId && expanded
  })
}

const handleParentClick = (item: NavItem) => {
  if (activeTab.value !== item.id) {
    activeTab.value = item.id
    setExpandedNav(item.id, true)
  } else {
    setExpandedNav(item.id, !item.expanded)
  }
}

const handleSubClick = (item: NavItem, sectionId: string) => {
  if (activeTab.value !== item.id) {
    activeTab.value = item.id
    setExpandedNav(item.id, true)
  }
  // 等待 DOM 更新后滚动
  nextTick(() => {
    const element = document.getElementById(sectionId)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  })
}

const { activeNotificationCount, notificationHistory, triggerNotify, clearLogs } = useNotify()

const liveTime = ref('')
let timer: ReturnType<typeof setInterval> | null = null
const updateTime = () => {
  const n = new Date()
  liveTime.value = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')} ${String(n.getHours()).padStart(2, '0')}:${String(n.getMinutes()).padStart(2, '0')}:${String(n.getSeconds()).padStart(2, '0')}`
}

const latencyHistory = ref([21, 24, 18, 15, 23, 26, 29, 32, 28, 22, 19, 17, 21, 25, 22])
const latestLatency = computed(() => latencyHistory.value[latencyHistory.value.length - 1] ?? 0)
let sparklineTimer: ReturnType<typeof setInterval> | null = null

const backupEnabled = ref(true)
const cpuLimit = ref(45)
const selectedClearance = ref('level-2')
const clearanceOptions = [
  { value: 'level-0', label: 'Public / 无级别公开限制' },
  { value: 'level-1', label: 'Restricted (Level 1) / 敏感等级' },
  { value: 'level-2', label: 'Confidential (Level 2) / 保密限制级' },
  { value: 'level-3', label: 'Secret (Level 3) / 核心机密层' },
  { value: 'level-4', label: 'Top Secret (Level 4) / 最高物理防御' },
]
const selectedClearanceKey = computed(
  () => clearanceOptions.find((i) => i.value === selectedClearance.value)?.label.split(' / ')[0] ?? 'CONFIDENTIAL',
)
const selectedClearanceLevel = computed(() => parseInt(selectedClearance.value.split('-')[1] ?? '0') || 0)

const updateLatency = () => {
  const base = 12 + Math.floor(cpuLimit.value * 0.15)
  const next = Math.max(5, base + Math.floor((Math.random() - 0.5) * 12))
  latencyHistory.value.push(next)
  if (latencyHistory.value.length > 25) latencyHistory.value.shift()
}

const sparklinePath = computed(() => {
  const data = latencyHistory.value
  const mx = Math.max(...data, 25)
  const mn = Math.min(...data, 5)
  const rng = mx - mn || 1
  return data
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${((i / (data.length - 1)) * 100).toFixed(1)} ${(28 - ((v - mn) / rng) * 24).toFixed(1)}`)
    .join(' ')
})
const sparklineAreaPath = computed(() => (sparklinePath.value ? `${sparklinePath.value} L 100 30 L 0 30 Z` : ''))

const settings = reactive<AppSettings>({
  language: 'zh',
  timezone: 'asia-shanghai',
  consoleName: 'Axiom Console',
  theme: 'light',
  autoSave: true,
  workerCount: '4',
  hwAccel: true,
  sessionTimeout: 30,
  twoFactor: false,
  ipWhitelist: false,
  ipList: '',
  dbAddress: 'mongodb+srv://axiom-cluster-prod.internal.net:27017/core-system',
  startupScript: '',
  debugMode: false,
  notifications: {
    cpuAlert: true,
    securityAlert: true,
    backupComplete: true,
    loginAlert: false,
    updateAvailable: true,
  },
})

const resetSettings = () => {
  Object.assign(settings, {
    language: 'zh',
    timezone: 'asia-shanghai',
    consoleName: 'Axiom Console',
    theme: 'light',
    autoSave: true,
    workerCount: '4',
    hwAccel: true,
    sessionTimeout: 30,
    twoFactor: false,
    ipWhitelist: false,
    ipList: '',
    debugMode: false,
  })
  triggerNotify('所有设置已重置为出厂默认值。', 'info', '设置已重置')
}
const saveSettings = () => triggerNotify('系统配置已成功持久化保存至磁盘。', 'success', '设置已保存')

const showDialog = ref(false)
const showSimpleDialog = ref(false)
const dialogConfirmText = ref('')
const dialogSliderVal = ref(50)
const confirmInput = ref<InstanceType<typeof AxInput> | null>(null)

const openDialog = () => {
  showDialog.value = true
  dialogConfirmText.value = ''
  nextTick(() => confirmInput.value?.focus?.())
}
const onDialogClose = () => {
  dialogConfirmText.value = ''
}
const executeSystemReset = () => {
  if (dialogConfirmText.value !== 'CONFIRM') return
  cpuLimit.value = dialogSliderVal.value
  backupEnabled.value = false
  selectedClearance.value = 'level-1'
  showDialog.value = false
  triggerNotify('系统重构回滚规程已成功灌入物理芯片。核心参数已被强制重置。', 'error', '核心重置成功')
}

const showProfileDropdown = ref(false)
const settingsDialogRef = ref<InstanceType<typeof SettingsDialog> | null>(null)
const settingsActiveTab = ref('general')
const settingsNavItems = [
  { id: 'general',       label: '通用设置',     icon: 'settings' },
  { id: 'performance',   label: '性能与算力',   icon: 'speed' },
  { id: 'security',      label: '安全与权限',   icon: 'security' },
  { id: 'notifications', label: '通知与告警',   icon: 'notifications' },
  { id: 'advanced',      label: '高级配置',     icon: 'build' },
]
const settingsBottomNavItems = [
  { id: 'help',   label: '帮助文档', icon: 'help_outline' },
  { id: 'status', label: '系统状态', icon: 'analytics' },
]
const triggerDropdownAction = (action: string) => {
  if (action === 'export') triggerNotify('正在压缩状态并导出为 JSON。', 'info', '导出状态包')
  else if (action === 'logs') clearLogs()
  else if (action === 'reset') {
    backupEnabled.value = true
    cpuLimit.value = 45
    selectedClearance.value = 'level-2'
    triggerNotify('控制台联动数据已恢复出厂状态配置。', 'success', '系统复位')
  }
}

const showNotificationsPanel = ref(false)
const searchQuery = ref('')
const globalSearchInput = ref<InstanceType<typeof AxInput> | null>(null)
const focusSearch = () => globalSearchInput.value?.focus?.()

const keys = useMagicKeys()
watch([keys['Meta+K'], keys['Control+K'], keys['/']], (v) => {
  if (v.some(Boolean)) focusSearch()
})

const handleGlobalKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    if (showDialog.value) showDialog.value = false
    if (showSimpleDialog.value) showSimpleDialog.value = false
    if (showProfileDropdown.value) showProfileDropdown.value = false
    if (showNotificationsPanel.value) showNotificationsPanel.value = false
  }
}

onMounted(() => {
  updateTime()
  timer = setInterval(updateTime, 1000)
  sparklineTimer = setInterval(updateLatency, 1500)
  setTimeout(() => triggerNotify('Axiom UI 组件展示台已就绪，视图已拆分为独立组件。', 'success', '系统唤醒'), 400)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (sparklineTimer) clearInterval(sparklineTimer)
})
</script>

<template>
  <div class="flex h-screen w-screen overflow-hidden" @keydown="handleGlobalKeydown">
    <Toaster
      position="bottom-right"
      :toast-options="{ style: { background: 'transparent', border: 'none', boxShadow: 'none', padding: '0px' } }"
    />

    <aside class="w-60 bg-surface-container-lowest border-r border-outline-variant flex flex-col justify-between py-ax-md px-ax-sm select-none z-10 shrink-0">
      <div class="space-y-ax-lg">
        <div class="flex items-center gap-ax-sm px-2">
          <div class="h-7 w-7 rounded-lg bg-primary flex items-center justify-center text-on-primary">
            <span class="material-symbols-outlined text-[18px]" style="font-variation-settings: 'FILL' 1">auto_fix_high</span>
          </div>
          <div>
            <h2 class="font-headline-sm text-headline-sm text-primary tracking-tight">Axiom Console</h2>
            <div class="flex items-center gap-ax-xs">
              <span class="inline-block w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></span>
              <span class="font-label-md text-[10px] text-secondary">v1.0.5-BETA</span>
            </div>
          </div>
        </div>

        <div class="px-2">
          <div
            class="flex items-center justify-between bg-surface-container-low border border-outline-variant hover:border-outline rounded-lg px-ax-sm py-1.5 cursor-pointer transition-colors"
            @click="focusSearch"
          >
            <div class="flex items-center gap-ax-xs text-secondary">
              <span class="material-symbols-outlined text-[16px]">search</span>
              <span class="font-body-sm text-body-sm">搜索组件...</span>
            </div>
            <kbd class="font-label-md text-[10px] bg-surface-container border border-outline-variant px-1 rounded shadow-sm text-secondary">⌘K</kbd>
          </div>
        </div>

        <nav class="space-y-ax-xs">
          <p class="font-label-md text-[10px] text-secondary uppercase tracking-wider px-2 pb-1">主要视图</p>
          <div v-for="item in navItems" :key="item.id">
            <!-- 父级菜单项 — 点击整行可折叠/展开 -->
            <div
              :class="[
                activeTab === item.id
                  ? 'bg-secondary-container text-on-secondary-container font-medium'
                  : 'text-secondary hover:bg-surface-container-low',
              ]"
              class="flex items-center justify-between rounded-xl py-1.5 px-2 font-label-md text-label-md transition-all duration-100 cursor-pointer select-none"
              @click="handleParentClick(item)"
            >
              <div class="flex items-center gap-ax-sm">
                <span
                  class="material-symbols-outlined"
                  :style="{ fontVariationSettings: activeTab === item.id ? '\'FILL\' 1' : '\'FILL\' 0' }"
                >{{ item.icon }}</span>
                <span>{{ item.name }}</span>
              </div>
              <div class="flex items-center gap-ax-xs">
                <span
                  v-if="item.badge"
                  class="font-label-md text-[10px] px-1.5 py-0.5 rounded bg-surface-container font-medium text-primary border border-outline-variant"
                >{{ item.badge }}</span>
                <span
                  class="material-symbols-outlined text-[14px] text-secondary transition-transform duration-200 shrink-0"
                  :class="item.expanded ? 'rotate-180' : ''"
                >expand_more</span>
              </div>
            </div>

            <!-- 子菜单列表（手风琴单开） -->
            <div
              class="grid transition-[grid-template-rows] duration-200 ease-out"
              :class="item.expanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'"
            >
              <div class="overflow-hidden">
                <div class="ml-4 mt-ax-xs space-y-ax-xs border-l-2 border-outline-variant/60 pl-2">
                  <a
                    v-for="sub in item.subMenus"
                    :key="sub.id"
                    href="#"
                    class="flex items-center gap-ax-sm rounded-lg py-1 px-2 font-body-sm text-body-sm text-secondary hover:bg-surface-container-low hover:text-primary transition-colors duration-100"
                    @click.prevent="handleSubClick(item, sub.sectionId)"
                  >
                    <span class="h-1 w-1 rounded-full bg-outline shrink-0"></span>
                    <span>{{ sub.name }}</span>
                  </a>
                </div>
              </div>
            </div>
          </div>
        </nav>
      </div>

      <div class="space-y-ax-sm">
        <AxButton
          variant="ghost"
          block
          icon="settings"
          icon-size="16px"
          @click="settingsDialogRef?.open()"
        >设置界面</AxButton>

        <div class="border-t border-outline-variant pt-ax-md flex items-center justify-between px-2">
          <div class="flex items-center justify-between w-full">
          <div class="flex items-center gap-ax-sm">
            <div class="h-8 w-8 rounded-full bg-surface-container border border-outline-variant flex items-center justify-center text-primary font-semibold text-body-md font-label-md">
              AM
            </div>
            <div class="overflow-hidden w-24">
              <h4 class="font-body-sm text-[12px] font-semibold text-primary truncate leading-tight">Alex Mercer</h4>
              <p class="font-body-sm text-[10px] text-secondary truncate">System Architect</p>
            </div>
          </div>
          <AxDropdown v-model="showProfileDropdown" placement="top-start">
            <template #trigger>
              <AxButton variant="ghost"  size="lg" icon="more_vert" icon-size="16px" />
            </template>
            <template #default="{ close }">
              <div class="py-1 w-44">
                <button class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-primary hover:bg-surface-container-low rounded-lg transition-colors" @click="triggerDropdownAction('export'); close()">
                  <span class="material-symbols-outlined text-[16px]">download</span><span>导出系统配置</span>
                </button>
                <button class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-primary hover:bg-surface-container-low rounded-lg transition-colors" @click="triggerDropdownAction('logs'); close()">
                  <span class="material-symbols-outlined text-[16px]">history</span><span>清空日志队列</span>
                </button>
                <div class="my-1 border-t border-outline-variant"></div>
                <button class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-error hover:bg-error-container hover:text-on-error-container rounded-lg transition-colors" @click="triggerDropdownAction('reset'); close()">
                  <span class="material-symbols-outlined text-[16px]">restart_alt</span><span>复位仪表盘</span>
                </button>
              </div>
            </template>
          </AxDropdown>
          </div>
        </div>
      </div>
    </aside>

    <div class="flex-1 flex flex-col overflow-hidden bg-background">
      <header class="h-14 bg-surface-container-lowest border-b border-outline-variant flex items-center justify-between px-margin select-none shrink-0 z-10">
        <div class="flex items-center gap-ax-sm">
          <span class="font-body-sm text-body-sm text-secondary">工作空间</span>
          <span class="text-outline-variant font-light">/</span>
          <span class="font-body-sm text-body-sm text-secondary">控制台</span>
          <span class="text-outline-variant font-light">/</span>
          <span class="font-body-sm text-body-sm text-primary font-medium">{{ activeTabTitle }}</span>
        </div>
        <div class="flex items-center gap-ax-md">
          <div class="font-label-md text-label-md text-secondary border border-outline-variant bg-surface-container-low rounded-lg px-2.5 py-1 flex items-center gap-ax-xs">
            <span class="material-symbols-outlined text-[14px]">schedule</span>
            <span>{{ liveTime }}</span>
          </div>
          <div class="relative">
            <AxInput ref="globalSearchInput" v-model="searchQuery" size="lg" placeholder="快速搜索..." class="w-44" @keydown.esc="searchQuery = ''">
              <template #prefix><span class="material-symbols-outlined text-[14px]">search</span></template>
            </AxInput>
          </div>
          <AxTooltip content="系统通知日志" placement="bottom">
            <AxButton
              variant="ghost"
               size="lg"
              icon="notifications"
              class="border border-outline-variant"
              @click="showNotificationsPanel = !showNotificationsPanel"
            >
              <template #suffix>
                <span
                  v-if="activeNotificationCount > 0"
                  class="absolute -top-1 -right-1 h-3.5 w-3.5 rounded-full bg-primary text-[9px] text-on-primary font-bold flex items-center justify-center"
                >{{ activeNotificationCount }}</span>
              </template>
            </AxButton>
          </AxTooltip>
        </div>
      </header>

      <main class="flex-1 overflow-y-auto p-margin space-y-ax-lg scrollbar-hide">
        <ComponentsView
          v-if="activeTab === 'components'"
          @open-dialog="openDialog"
          @open-simple-dialog="showSimpleDialog = true"
        />
        <DemoView
          v-else-if="activeTab === 'demo'"
          :cpu-limit="cpuLimit"
          :backup-enabled="backupEnabled"
          :selected-clearance-key="selectedClearanceKey"
          :selected-clearance-level="selectedClearanceLevel"
          :latest-latency="latestLatency"
          :latency-history="latencyHistory"
          :sparkline-path="sparklinePath"
          :sparkline-area-path="sparklineAreaPath"
        />
      </main>

      <Transition
        enter-active-class="transition ease-out duration-300 transform"
        enter-from-class="translate-x-full"
        enter-to-class="translate-x-0"
        leave-active-class="transition ease-in duration-200 transform"
        leave-from-class="translate-x-0"
        leave-to-class="translate-x-full"
      >
        <div
          v-show="showNotificationsPanel"
          class="fixed inset-y-0 right-0 w-80 bg-surface-container-lowest border-l border-outline-variant shadow-2xl z-40 p-ax-md flex flex-col justify-between"
        >
          <div>
            <div class="flex items-center justify-between border-b border-outline-variant pb-ax-sm mb-ax-md">
              <h3 class="font-headline-sm text-body-md font-semibold text-primary">系统通知历史队列</h3>
              <AxButton variant="ghost"  size="lg" icon="close" icon-size="16px" @click="showNotificationsPanel = false" />
            </div>
            <div class="space-y-ax-sm overflow-y-auto max-h-[70vh] pr-1">
              <div v-for="log in notificationHistory" :key="log.id" class="border border-outline-variant rounded-lg p-ax-sm bg-surface-container-low">
                <div class="flex items-center justify-between">
                  <span class="font-label-md text-[10px] text-secondary">{{ log.time }}</span>
                  <span
                    class="font-label-md text-[9px] px-1 rounded uppercase font-semibold"
                    :class="{
                      'bg-surface-container text-primary border border-outline': log.type === 'info',
                      'bg-error-container text-on-error-container': log.type === 'error',
                      'bg-secondary-container text-on-secondary-container': log.type === 'secondary',
                      'bg-secondary-container text-primary': log.type === 'success',
                    }"
                  >{{ log.type }}</span>
                </div>
                <h5 class="font-body-sm text-[11px] font-semibold text-primary mt-1">{{ log.title }}</h5>
                <p class="font-body-sm text-[10px] text-on-surface-variant leading-relaxed mt-0.5">{{ log.message }}</p>
              </div>
              <div v-if="notificationHistory.length === 0" class="py-12 text-center text-secondary font-body-sm text-body-sm">当前尚无系统交互历史记录</div>
            </div>
          </div>
          <AxButton size="lg"
            variant="outline"
            block
            icon="delete_sweep"
            :disabled="notificationHistory.length === 0"
            @click="clearLogs"
          >清空所有日志</AxButton>
        </div>
      </Transition>

      <footer class="h-12 bg-surface-container-lowest border-t border-outline-variant flex items-center justify-between px-margin select-none shrink-0 text-body-sm text-secondary">
        <div class="flex items-center gap-ax-md">
          <div class="flex items-center gap-ax-xs">
            <span class="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            <span>核心系统: 正常运行 (Operational)</span>
          </div>
          <span class="text-outline-variant">|</span>
          <span class="font-label-md text-[11px]">API 往返延时: {{ latestLatency }}ms</span>
        </div>
        <div class="flex items-center gap-ax-sm">
          <span>Axiom Studio © 2026</span>
          <span class="text-outline-variant">•</span>
          <a href="#" class="text-primary font-label-md hover:underline flex items-center gap-ax-xs text-[11px]">
            <span>系统架构白皮书</span>
            <span class="material-symbols-outlined text-[12px]">arrow_forward</span>
          </a>
        </div>
      </footer>
    </div>

    <AxDialog v-model="showDialog" title="高危底层重置规程 (Security Authorization)" icon="lock_open" @close="onDialogClose">
      <AxAlert type="error" :dismissible="false" title="高风险行为警告">
        您正试图执行系统核心重构恢复方案。这会直接洗刷掉所有内存缓存历史日志，并重置控制台内的一切算力及安全防御设置。请保证已备份完毕。
      </AxAlert>
      <div class="space-y-ax-sm">
        <label class="font-label-md text-label-md font-semibold text-primary block">第一步：在输入框内确认您的重置声明书</label>
        <p class="font-body-sm text-[11px] text-secondary">
          请精确键入 "<span class="font-label-md font-bold text-primary select-text">CONFIRM</span>" 来开启下方的二次确认授权锁定。
        </p>
        <AxInput size="lg" ref="confirmInput" v-model="dialogConfirmText" placeholder="CONFIRM" />
      </div>
      <div class="space-y-ax-xs">
        <label class="font-label-md text-label-md font-semibold text-primary block">第二步：确定重置后分配给初始化进程的限制等级</label>
        <div class="bg-surface-container-low rounded-lg p-ax-sm border border-outline-variant">
          <AxSlider v-model="dialogSliderVal" :min="5" :max="95" show-value :value-label="dialogSliderVal + '%'" />
        </div>
      </div>
      <template #footer="{ close }">
        <AxButton size="lg" variant="outline" @click="close">取消物理回退</AxButton>
        <AxButton size="lg" icon="security" :disabled="dialogConfirmText !== 'CONFIRM'" @click="executeSystemReset">执行系统回滚</AxButton>
      </template>
    </AxDialog>

    <AxDialog v-model="showSimpleDialog" title="系统提示" icon="info" max-width="max-w-sm">
      <p class="font-body-sm text-body-sm text-on-surface-variant leading-relaxed">这是一个简单的提示对话框，仅包含文字内容。点击关闭按钮或按 ESC 键即可关闭。</p>
      <template #footer="{ close }">
        <AxButton size="lg" @click="close">知道了</AxButton>
      </template>
    </AxDialog>

    <!-- 方式二：对话框式设置面板 -->
    <SettingsDialog
      ref="settingsDialogRef"
      v-model:active-tab="settingsActiveTab"
      :nav-items="settingsNavItems"
      :bottom-nav-items="settingsBottomNavItems"
      title="系统设置中心"
      subtitle="管理系统运行参数"
      @save="saveSettings"
      @cancel="resetSettings"
      @nav-click="(item) => triggerNotify(`「${item.label}」页面正在开发中`, 'info', '功能提示')"
    />
  </div>
</template>
