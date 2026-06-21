<script setup lang="ts">
import { ref, watch } from 'vue'
import type { PropPanelSchemaItem } from '../types'
import { FloatingBall } from '../functional'
import type { FloatingBallPrefs } from '../functional'
import { useNotify } from '../hooks/useNotify'

const emit = defineEmits<{
  'open-dialog': []
  'open-simple-dialog': []
}>()

const btnProps = ref({
  variant: 'primary' as const,
  size: 'md' as const,
  rounded: 'md',
  disabled: false,
  showIcon: false,
  loading: false,
  block: false,
  label: '操作按钮',
})
const btnSchema: PropPanelSchemaItem[] = [
  { key: 'variant', label: '变体', type: 'segmented', options: [{ value: 'primary', label: 'Primary' }, { value: 'outline', label: 'Outline' }, { value: 'ghost', label: 'Ghost' }, { value: 'danger', label: 'Danger' }] },
  { key: 'size', label: '尺寸', type: 'segmented', options: [{ value: 'xs', label: 'XS' }, { value: 'sm', label: 'SM' }, { value: 'md', label: 'MD' }, { value: 'lg', label: 'LG' }, { value: 'xl', label: 'XL' }, { value: 'icon', label: 'Icon' }, { value: 'icon-lg', label: 'Icon-lg' }] },
  { key: 'rounded', label: '圆角', type: 'segmented', options: [{ value: 'none', label: 'None' }, { value: 'xs', label: 'XS' }, { value: 'sm', label: 'SM' }, { value: 'md', label: 'MD' }, { value: 'lg', label: 'LG' }, { value: 'xl', label: 'XL' }, { value: 'full', label: 'Full' }] },
  { key: 'label', label: '文案', type: 'textarea', placeholder: '按钮文字' },
  { key: 'showIcon', label: '显示图标', description: '在按钮左侧显示 bolt 图标', type: 'switch' },
  { key: 'loading', label: '加载状态', description: '展示旋转加载动画', type: 'switch' },
  { key: 'disabled', label: '禁用', description: '点击无响应，透明度降低', type: 'switch' },
  { key: 'block', label: '块级', description: '宽度撑满父容器', type: 'switch' },
]

const inputProps = ref({ value: '', size: 'md' as const, rounded: 'md', disabled: false, showPrefix: false, showSuffix: false, showPassword: false, placeholder: '请输入内容...', showMultiline: false, inputRows: 3, resize: 'vertical' as 'none' | 'vertical' | 'horizontal' | 'both' })
watch(inputProps, (v) => { console.log('[INPUTPROPS] resize =', JSON.stringify(v.resize), '| showMultiline =', v.showMultiline) }, { immediate: true, deep: true })
const inputIconSize: Record<string, string> = { xs: '!text-[12px]', sm: '!text-[14px]', md: '!text-[16px]', lg: '!text-[18px]' }
const inputSchema: PropPanelSchemaItem[] = [
  { key: 'size', label: '尺寸', type: 'segmented', options: [{ value: 'xs', label: 'XS' }, { value: 'sm', label: 'SM' }, { value: 'md', label: 'MD' }, { value: 'lg', label: 'LG' }, { value: 'xl', label: 'XL' }] },
  { key: 'rounded', label: '圆角', type: 'segmented', options: [{ value: 'none', label: 'None' }, { value: 'xs', label: 'XS' }, { value: 'sm', label: 'SM' }, { value: 'md', label: 'MD' }, { value: 'lg', label: 'LG' }, { value: 'xl', label: 'XL' }, { value: 'full', label: 'Full' }] },
  { key: 'showMultiline', label: '多行模式', description: '切换为 textarea 多行文本输入', type: 'switch' },
  { key: 'placeholder', label: '占位符', type: 'textarea', placeholder: '占位文本' },
  { key: 'inputRows', label: '行数', description: 'textarea 显示行数', type: 'slider', min: 1, max: 10 },
  { key: 'resize', label: 'Resize', description: 'textarea 拖拽缩放方向', type: 'segmented', options: [{ value: 'vertical', label: '纵向' }, { value: 'horizontal', label: '横向' }, { value: 'both', label: '双向' }, { value: 'none', label: '禁用' }] },
  { key: 'showPassword', label: '密码模式', description: '显示密码显隐切换小眼睛（仅单行）', type: 'switch' },
  { key: 'showPrefix', label: '前缀图标', description: '在输入框左侧显示图标（仅单行）', type: 'switch' },
  { key: 'showSuffix', label: '后置图标', description: '在输入框右侧显示图标（仅单行）', type: 'switch' },
  { key: 'disabled', label: '禁用', description: '不可输入状态', type: 'switch' },
]

const sliderProps = ref({ value: 50, min: 0, max: 100, showLabels: true, showValue: true, labelPosition: 'top' as 'top' | 'right' })
const sliderSchema: PropPanelSchemaItem[] = [
  { key: 'value', label: '当前值', type: 'slider', min: 0, max: 100 },
  { key: 'min', label: '最小值', type: 'slider', min: 0, max: 50 },
  { key: 'max', label: '最大值', type: 'slider', min: 50, max: 200 },
  { key: 'labelPosition', label: '标签位置', type: 'segmented', options: [{ value: 'top', label: '上方' }, { value: 'right', label: '右侧' }] },
  { key: 'showLabels', label: '显示标签', description: '左右端点标签文字', type: 'switch' },
  { key: 'showValue', label: '显示数值', description: '滑块上方数值气泡', type: 'switch' },
]

const switchProps = ref({ checked: true, disabled: false, size: 'md' as string })
const switchSchema: PropPanelSchemaItem[] = [
  { key: 'size', label: '尺寸', type: 'segmented', options: [{ value: 'xs', label: 'XS' }, { value: 'sm', label: 'SM' }, { value: 'md', label: 'MD' }, { value: 'lg', label: 'LG' }, { value: 'xl', label: 'XL' }] },
  { key: 'checked', label: '开关', description: '开关状态，支持 v-model', type: 'switch' },
  { key: 'disabled', label: '禁用', description: '不可交互状态，半透明显示', type: 'switch' },
]

const alertProps = ref({
  type: 'info' as const,
  title: '系统通知',
  message: '核心集群控制链已就绪，当前各项数据运行处于标准健康状态。',
  dismissible: true,
})
const alertSchema: PropPanelSchemaItem[] = [
  { key: 'type', label: '类型', type: 'segmented', options: [{ value: 'info', label: 'Info' }, { value: 'success', label: 'Success' }, { value: 'warning', label: 'Warning' }, { value: 'error', label: 'Error' }] },
  { key: 'title', label: '标题', type: 'input', placeholder: '警示标题' },
  { key: 'message', label: '内容', type: 'textarea', placeholder: '警示内容', rows: 5 },
  { key: 'dismissible', label: '可关闭', description: '显示右上角关闭按钮', type: 'switch' },
]

const demoSelectOptions = [
  { value: 'opt1', label: 'Vue 3 — 渐进式框架' },
  { value: 'opt2', label: 'React — UI 组件库' },
  { value: 'opt3', label: 'Angular — 全量框架' },
  { value: 'opt4', label: 'Svelte — 编译时框架' },
  { value: 'opt5', label: 'Solid.js — 细粒度响应' },
]
const selectProps = ref({ value: 'opt1' as unknown, size: 'md' as string, rounded: 'md', searchable: false, multiple: false, placeholder: '请选择框架...', placement: 'bottom-start', dropdownWidth: 'auto' as string, dropdownMaxWidth: '' as string, tagMaxWidth: '120px' as string, triggerWidth: '' as string, triggerMaxWidth: '' as string })
const selectSchema: PropPanelSchemaItem[] = [
  { key: 'size', label: '尺寸', type: 'segmented', options: [{ value: 'xs', label: 'XS' }, { value: 'sm', label: 'SM' }, { value: 'md', label: 'MD' }, { value: 'lg', label: 'LG' }, { value: 'xl', label: 'XL' }] },
  { key: 'rounded', label: '圆角', type: 'segmented', options: [{ value: 'none', label: 'None' }, { value: 'xs', label: 'XS' }, { value: 'sm', label: 'SM' }, { value: 'md', label: 'MD' }, { value: 'lg', label: 'LG' }, { value: 'xl', label: 'XL' }, { value: 'full', label: 'Full' }] },
  { key: 'placeholder', label: '占位符', type: 'textarea', placeholder: '占位文本' },
  { key: 'searchable', label: '可搜索', description: '点击下拉后按钮变为搜索输入框', type: 'switch' },
  { key: 'multiple', label: '多选', description: '支持勾选多项，已选项以标签展示', type: 'switch' },
  {
    key: 'placement',
    label: '弹出方向',
    type: 'input',
    placeholder: '如 bottom-start、top',
  },
  {
    key: 'dropdownWidth',
    label: '下拉最小宽度',
    type: 'input',
    placeholder: 'match / auto / 200px',
  },
  {
    key: 'dropdownMaxWidth',
    label: '下拉最大宽度',
    type: 'input',
    placeholder: '如 320px（留空=不限制）',
  },
  {
    key: 'tagMaxWidth',
    label: '标签最大宽度',
    type: 'input',
    placeholder: '如 120px（留空=不限制）',
  },
  {
    key: 'triggerWidth',
    label: '触发框最小宽度',
    type: 'input',
    placeholder: '如 200px（留空=自适应）',
  },
  {
    key: 'triggerMaxWidth',
    label: '触发框最大宽度',
    type: 'input',
    placeholder: '如 320px（留空=不限制）',
  },
]

const tooltipProps = ref({ content: '这是一条 Tooltip 提示文字', placement: 'top' as const, arrow: true, offset: 8 })
const tooltipSchema: PropPanelSchemaItem[] = [
  { key: 'content', label: '提示文字', type: 'textarea', placeholder: 'Tooltip 内容' },
  {
    key: 'placement',
    label: '方向',
    type: 'select',
    options: [
      { value: 'top', label: 'top' },
      { value: 'bottom', label: 'bottom' },
      { value: 'left', label: 'left' },
      { value: 'right', label: 'right' },
      { value: 'top-start', label: 'top-start' },
      { value: 'top-end', label: 'top-end' },
      { value: 'bottom-start', label: 'bottom-start' },
      { value: 'bottom-end', label: 'bottom-end' },
    ],
  },
  { key: 'offset', label: '距离', type: 'slider', min: 0, max: 32 },
  { key: 'arrow', label: '显示箭头', description: '指向触发元素的小三角箭头', type: 'switch' },
]

const showDropdownDemo1 = ref(false)
const showDropdownDemo2 = ref(false)

const popoverProps = ref({
  title: '通知详情',
  icon: 'notifications',
  placement: 'bottom-start' as const,
  offset: 6,
  trigger: 'click' as const,
  hoverCloseDelay: 150,
  width: '',
  maxWidth: '',
  teleport: true,
})
const popoverSchema: PropPanelSchemaItem[] = [
  { key: 'title', label: '标题', type: 'input', placeholder: 'Popover 标题' },
  { key: 'icon', label: '图标名', type: 'input', placeholder: 'Material Symbol 图标名' },
  {
    key: 'trigger',
    label: '触发方式',
    type: 'segmented',
    options: [
      { value: 'click', label: '左键点击' },
      { value: 'hover', label: '悬停' },
      { value: 'contextmenu', label: '右键' },
    ],
  },
  { key: 'hoverCloseDelay', label: '悬停关闭延迟', description: 'hover 模式下鼠标离开后等待关闭的毫秒数', type: 'slider', min: 0, max: 500 },
  {
    key: 'placement',
    label: '弹出方向',
    type: 'select',
    options: [
      { value: 'bottom-start', label: '左下 (bottom-start)' },
      { value: 'bottom', label: '下方 (bottom)' },
      { value: 'bottom-end', label: '右下 (bottom-end)' },
      { value: 'top-start', label: '左上 (top-start)' },
      { value: 'top', label: '上方 (top)' },
      { value: 'top-end', label: '右上 (top-end)' },
      { value: 'left-start', label: '左对齐 (left-start)' },
      { value: 'left', label: '左侧 (left)' },
      { value: 'left-end', label: '左下对齐 (left-end)' },
      { value: 'right-start', label: '右对齐 (right-start)' },
      { value: 'right', label: '右侧 (right)' },
      { value: 'right-end', label: '右下对齐 (right-end)' },
    ],
  },
  { key: 'offset', label: '偏移距离', type: 'slider', min: 0, max: 24 },
  { key: 'width', label: '面板最小宽度', type: 'input', placeholder: '如: 260px' },
  { key: 'maxWidth', label: '面板最大宽度', type: 'input', placeholder: '如: 400px' },
  { key: 'teleport', label: '传送至 body', description: '将面板渲染到 body 元素下', type: 'switch' },
]

const showPopoverDemo1 = ref(false)
const showPopoverDemo2 = ref(false)
const showPopoverDemo3 = ref(false)

const dropdownProps = ref({
  placement: 'bottom-start' as const,
  offset: 6,
  matchWidth: false,
  trigger: 'click' as const,
  menuWidth: '',
  menuMaxWidth: '',
  teleport: true,
})
const dropdownSchema: PropPanelSchemaItem[] = [
  {
    key: 'trigger',
    label: '触发方式',
    type: 'segmented',
    options: [
      { value: 'click', label: '左键点击' },
      { value: 'hover', label: '悬停' },
      { value: 'contextmenu', label: '右键' },
    ],
  },
  {
    key: 'placement',
    label: '弹出方向',
    type: 'select',
    options: [
      { value: 'bottom-start', label: '左下 (bottom-start)' },
      { value: 'bottom', label: '下方 (bottom)' },
      { value: 'bottom-end', label: '右下 (bottom-end)' },
      { value: 'top-start', label: '左上 (top-start)' },
      { value: 'top', label: '上方 (top)' },
      { value: 'top-end', label: '右上 (top-end)' },
      { value: 'left-start', label: '左对齐 (left-start)' },
      { value: 'left', label: '左侧 (left)' },
      { value: 'left-end', label: '左下对齐 (left-end)' },
      { value: 'right-start', label: '右对齐 (right-start)' },
      { value: 'right', label: '右侧 (right)' },
      { value: 'right-end', label: '右下对齐 (right-end)' },
    ],
  },
  { key: 'offset', label: '偏移距离', type: 'slider', min: 0, max: 24 },
  { key: 'matchWidth', label: '匹配宽度', description: '菜单宽度与触发元素一致', type: 'switch' },
  { key: 'menuWidth', label: '菜单宽度', type: 'input', placeholder: '如: 200px' },
  { key: 'menuMaxWidth', label: '最大宽度', type: 'input', placeholder: '如: 320px' },
  { key: 'teleport', label: '传送至 body', description: '将菜单渲染到 body 元素下', type: 'switch' },
]

// ---- FloatingBall ----
const ballPrefs = ref<FloatingBallPrefs>({ theme: 'light', shrunk: false, hidden: false, label: 'FB' })
const showBall = ref(false)
const ballSchema: PropPanelSchemaItem[] = [
  {
    key: 'theme',
    label: '主题',
    type: 'segmented',
    options: [
      { value: 'light', label: '亮色' },
      { value: 'dark', label: '暗色' },
    ],
  },
  { key: 'label', label: '标签文字', type: 'input', placeholder: '悬浮球内文字' },
  { key: 'shrunk', label: '缩小', description: '切换更小的悬浮球尺寸', type: 'switch' },
  { key: 'hidden', label: '隐藏', description: '完全隐藏悬浮球', type: 'switch' },
]

// ---- AxImage ----
const imageProps = ref({
  src: 'https://picsum.photos/seed/ax-demo/600/400',
  alt: '示例图片',
  objectFit: 'cover' as 'cover' | 'contain',
  adaptiveAspect: false,
})
const imageSchema: PropPanelSchemaItem[] = [
  { key: 'src', label: '图片 URL', type: 'input', placeholder: 'https://...' },
  { key: 'alt', label: '替代文字', type: 'input', placeholder: '图片描述' },
  { key: 'objectFit', label: '填充模式', type: 'segmented', options: [{ value: 'cover', label: 'Cover' }, { value: 'contain', label: 'Contain' }] },
  { key: 'adaptiveAspect', label: '自适应宽高比', description: '加载前正方形占位', type: 'switch' },
]

// ---- AxJsonViewer ----
const jsonViewerProps = ref({
  expandLevel: 0,
  wrapEnabled: true,
})
const sampleJson = {
  name: 'WorkBuddy',
  version: '2.4.0',
  description: 'WorkBuddy 是一款强大的 AI 编程助手，支持代码生成、智能问答、项目分析、自动化任务、多模态内容理解等多种功能。它能够深入理解复杂的项目结构，提供精准的代码建议和问题解决方案，是开发者的全能工作伙伴。',
  modules: ['core', 'ui', 'connector', 'plugin-system', 'task-scheduler'],
  dependencies: {
    production: { vue: '^3.5.0', typescript: '^5.7.0', tailwindcss: '^4.1.0', vite: '^6.3.0', 'vue-router': '^4.5.0', pinia: '^3.0.0', '@vueuse/core': '^12.0.0', axios: '^1.7.0', zod: '^3.24.0' },
    dev: { vitest: '^2.1.0', playwright: '^1.50.0', eslint: '^9.0.0', prettier: '^3.5.0' },
  },
  settings: {
    theme: 'auto',
    language: 'zh-CN',
    apiEndpoint: 'https://api.workbuddy.internal.example.com/v2/graphql/pipeline/execute?timeout=30000&retry=3&region=ap-guangzhou',
    features: { ai: true, automation: true, search: false, collaboration: true, versionControl: true, realtimeSync: false, darkMode: 'auto' },
  },
  changelog: 'v2.4.0 版本新增了多模态图片理解能力，支持在对话中直接上传截图并进行分析。同时优化了 TypeScript 和 Vue 3 项目中的代码生成准确率，修复了若干影响稳定性的关键问题，性能提升了约 35%。',
  releaseNotes: `## 新增功能
- 支持多模态图片理解与 OCR 识别
- 新增自动化任务调度引擎
- 优化大文件代码索引速度

## 问题修复
- 修复组件递归渲染时的内存泄漏
- 修复长文本截断显示异常

## 性能优化
- 构建速度提升约 40%
- 首屏加载体积减少 25%`,
  stats: { users: 12800, uptime: 99.98, active: true, avgResponseMs: 120, peakQps: 3800 },
  config: null,
  tags: ['vue', 'typescript', 'tailwind', 'ai', 'productivity', 'developer-tools'],
}
const jsonViewerSchema: PropPanelSchemaItem[] = [
  { key: 'expandLevel', label: '展开级别', description: '-1=全部折叠  0=全部展开  1=第一层  2/3=更深层级', type: 'slider', min: -1, max: 3, step: 1 },
  { key: 'wrapEnabled', label: '自动换行', description: '长文本自动换行而非截断', type: 'switch' },
]

// ---- AxImageViewer ----
const showImageViewer = ref(false)
const demoImages = [
  'https://picsum.photos/seed/viewer1/1200/800',
  'https://picsum.photos/seed/viewer2/1200/800',
  'https://picsum.photos/seed/viewer3/1200/800',
  'https://picsum.photos/seed/viewer4/1200/800',
  'https://picsum.photos/seed/viewer5/1200/800',
]

// ---- Notify ----
const notify = useNotify()
const notifyProps = ref({ type: 'info' as 'info' | 'success' | 'error' | 'secondary', title: '系统通知', message: '核心集群控制链已就绪，当前各项数据运行处于标准健康状态。', showActions: false })
const notifySchema: PropPanelSchemaItem[] = [
  { key: 'type', label: '类型', type: 'segmented', options: [{ value: 'info', label: 'Info' }, { value: 'success', label: 'Success' }, { value: 'error', label: 'Error' }, { value: 'secondary', label: 'Secondary' }] },
  { key: 'title', label: '标题', type: 'input', placeholder: '通知标题' },
  { key: 'message', label: '消息内容', type: 'textarea', placeholder: '通知内容', rows: 3 },
  { key: 'showActions', label: '显示操作区', description: '展示角标数量和日志统计', type: 'switch' },
]

function handleNotifyShow() {
  notify.triggerNotify(notifyProps.value.message, notifyProps.value.type, notifyProps.value.title)
}

function handleBallSave(prefs: FloatingBallPrefs) {
  ballPrefs.value = prefs
}
</script>

<template>
  <div class="space-y-ax-lg">
    <div class="border-b border-outline-variant pb-ax-md">
      <h2 class="font-headline-sm text-headline-md text-primary">UI 组件列表</h2>
      <p class="font-body-sm text-body-sm text-on-surface-variant mt-1">展示所有组件的每一种状态变体。左侧预览区，右侧属性配置面板，实时联动。</p>
    </div>

    <div id="section-btn"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div
        class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">Button</span>
        <span class="font-body-sm text-[11px] text-secondary">按钮组件 — 支持 4 种变体、3 种尺寸、图标、加载态、禁用态</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[200px]">
        <div class="flex-1 p-ax-lg comp-preview flex flex-col gap-ax-lg items-start justify-center">
          <div class="flex flex-wrap items-center gap-ax-sm">
            <AxButton :variant="btnProps.variant" :size="btnProps.size" :rounded="btnProps.rounded" :disabled="btnProps.disabled"
              :icon="btnProps.showIcon ? 'bolt' : ''" :block="btnProps.block" :loading="btnProps.loading">
              {{ btnProps.label }}
            </AxButton>
          </div>
          <div class="flex flex-wrap gap-ax-xs">
            <span class="font-label-md text-[10px] text-secondary mr-1">所有变体：</span>
            <AxButton variant="primary"  size="lg">Primary</AxButton>
            <AxButton variant="outline"  size="lg">Outline</AxButton>
            <AxButton variant="ghost"  size="lg">Ghost</AxButton>
            <AxButton variant="danger"  size="lg">Danger</AxButton>
            <AxButton variant="primary"  size="lg" icon="bolt">带图标</AxButton>
            <AxButton variant="primary"  size="lg" icon="settings" />
            <AxButton variant="outline"  size="lg" disabled>禁用</AxButton>
          </div>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto">
          <AxPropPanel v-model="btnProps" :schema="btnSchema" title="按钮属性" />
        </div>
      </div>
    </div>

    <div id="section-input"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div
        class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">Input</span>
        <span class="font-body-sm text-[11px] text-secondary">输入框 — 支持单行/多行切换、3 种尺寸、前缀图标、密码模式、禁用态</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[260px]">
        <div class="flex-1 p-ax-lg comp-preview flex flex-col gap-ax-md items-start justify-center">
          <form class="w-64 relative" autocomplete="off" @submit.prevent>
            <input v-if="inputProps.showPassword" type="text" name="username" autocomplete="username" tabindex="-1"
              aria-hidden="true"
              class="absolute w-px h-px p-0 -m-px overflow-hidden whitespace-nowrap border-0 opacity-0 pointer-events-none"
              value="">
            <AxInput v-model="inputProps.value" :size="inputProps.size" :rounded="inputProps.rounded" :placeholder="inputProps.placeholder"
              :disabled="inputProps.disabled" :password="inputProps.showPassword && !inputProps.showMultiline"
              :multiline="inputProps.showMultiline" :rows="inputProps.inputRows" :resize="inputProps.resize">
              <template v-if="inputProps.showPrefix && !inputProps.showMultiline && !inputProps.showPassword"
                #prefix><span class="material-symbols-outlined"
                  :class="inputIconSize[inputProps.size]">search</span></template>
              <template v-if="inputProps.showSuffix && !inputProps.showMultiline && !inputProps.showPassword"
                #suffix><span class="material-symbols-outlined"
                  :class="inputIconSize[inputProps.size]">close</span></template>
            </AxInput>
          </form>
          <div class="flex flex-wrap gap-ax-sm">
            <span class="font-label-md text-[10px] text-secondary self-center">所有尺寸：</span>
            <AxInput  size="lg" placeholder="Small" class="w-28" />
            <AxInput  size="lg" placeholder="Medium" class="w-28" />
            <AxInput size="lg" placeholder="Large" class="w-28" />
          </div>
          <div class="flex flex-wrap gap-ax-sm">
            <span class="font-label-md text-[10px] text-secondary self-center">带图标：</span>
            <AxInput size="lg" placeholder="带前缀" class="w-40">
              <template #prefix><span class="material-symbols-outlined !text-[16px]">person</span></template>
            </AxInput>
            <AxInput size="lg" placeholder="带后缀" class="w-40">
              <template #suffix><span class="material-symbols-outlined !text-[16px]">close</span></template>
            </AxInput>
            <AxInput size="lg" placeholder="禁用状态" class="w-36" disabled />
          </div>
          <form class="relative flex flex-wrap gap-ax-sm items-center" autocomplete="off" @submit.prevent>
            <input type="text" name="username" autocomplete="username" tabindex="-1" aria-hidden="true"
              class="absolute w-px h-px p-0 -m-px overflow-hidden whitespace-nowrap border-0 opacity-0 pointer-events-none"
              value="">
            <span class="font-label-md text-[10px] text-secondary self-center">密码模式：</span>
            <AxInput size="lg" placeholder="请输入密码" class="w-44" password />
            <AxInput size="lg" placeholder="密码已输入" class="w-44" password model-value="Admin@2026"
              autocomplete="current-password" />
          </form>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto">
          <AxPropPanel v-model="inputProps" :schema="inputSchema" title="输入框属性" />
        </div>
      </div>
    </div>

    <div id="section-slider"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div
        class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">Slider</span>
        <span class="font-body-sm text-[11px] text-secondary">滑块组件 — 支持自定义范围、标签、数值显示</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[180px]">
        <div class="flex-1 p-ax-lg comp-preview flex flex-col gap-ax-lg items-start justify-center">
          <div class="w-72">
            <AxSlider v-model="sliderProps.value" :min="sliderProps.min" :max="sliderProps.max"
              :show-labels="sliderProps.showLabels" :show-value="sliderProps.showValue"
              :label-position="sliderProps.labelPosition" label-left="最小" label-right="最大"
              :value-label="sliderProps.value + '%'" />
          </div>
          <div class="w-full space-y-ax-sm max-w-sm">
            <span class="font-label-md text-[10px] text-secondary">带标签与数值：</span>
            <AxSlider :model-value="72" :min="0" :max="100" show-labels show-value label-left="空载" label-right="满载"
              value-label="72%" />
            <span class="font-label-md text-[10px] text-secondary">标签右侧模式：</span>
            <AxSlider :model-value="72" :min="0" :max="100" show-labels show-value label-left="空载" label-right="满载"
              value-label="72%" label-position="right" />
            <span class="font-label-md text-[10px] text-secondary">无标签简洁模式：</span>
            <AxSlider :model-value="40" :min="0" :max="100" />
          </div>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto">
          <AxPropPanel v-model="sliderProps" :schema="sliderSchema" title="滑块属性" />
        </div>
      </div>
    </div>

    <div id="section-switch"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div
        class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">Switch</span>
        <span class="font-body-sm text-[11px] text-secondary">开关组件 — 支持 v-model、禁用态、aria 可访问性</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[180px]">
        <div class="flex-1 p-ax-lg comp-preview flex flex-col gap-ax-lg items-start justify-center">
          <div class="flex items-center gap-ax-md">
            <span class="font-label-md text-[10px] text-secondary">动态预览：</span>
            <AxSwitch :model-value="switchProps.checked" :disabled="switchProps.disabled" :size="switchProps.size"
              @update:model-value="switchProps.checked = $event" />
            <span class="font-body-sm text-[12px] text-primary ml-ax-sm">{{ switchProps.checked ? '开启' : '关闭' }}</span>
          </div>
          <div class="w-full space-y-ax-sm max-w-sm">
            <span class="font-label-md text-[10px] text-secondary">所有状态：</span>
            <div class="flex flex-wrap items-center gap-ax-md">
              <div class="flex items-center gap-ax-sm">
                <AxSwitch size="lg" :model-value="true" />
                <span class="font-body-sm text-[11px] text-secondary">开启</span>
              </div>
              <div class="flex items-center gap-ax-sm">
                <AxSwitch size="lg" :model-value="false" />
                <span class="font-body-sm text-[11px] text-secondary">关闭</span>
              </div>
              <div class="flex items-center gap-ax-sm">
                <AxSwitch size="lg" :model-value="true" disabled />
                <span class="font-body-sm text-[11px] text-secondary">禁用-开</span>
              </div>
              <div class="flex items-center gap-ax-sm">
                <AxSwitch size="lg" :model-value="false" disabled />
                <span class="font-body-sm text-[11px] text-secondary">禁用-关</span>
              </div>
            </div>
          </div>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto">
          <AxPropPanel v-model="switchProps" :schema="switchSchema" title="开关属性" />
        </div>
      </div>
    </div>

    <div id="section-alert"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div
        class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">Alert</span>
        <span class="font-body-sm text-[11px] text-secondary">警示横幅 — 4 种语义、可关闭、带标题</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[180px]">
        <div class="flex-1 p-ax-lg comp-preview flex flex-col gap-ax-sm items-start justify-center">
          <AxAlert :type="alertProps.type" :title="alertProps.title" :dismissible="alertProps.dismissible" model-value>
            {{
              alertProps.message }}</AxAlert>
          <div class="w-full max-w-md space-y-ax-xs mt-2">
            <span class="font-label-md text-[10px] text-secondary">所有类型：</span>
            <AxAlert type="info" title="信息" model-value :dismissible="false">这是一条系统信息提示。</AxAlert>
            <AxAlert type="success" title="成功" model-value :dismissible="false">操作已成功完成。</AxAlert>
            <AxAlert type="warning" title="警告" model-value :dismissible="false">请注意当前系统资源使用情况。</AxAlert>
            <AxAlert type="error" title="错误" model-value :dismissible="false">核心服务连接已中断。</AxAlert>
          </div>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto">
          <AxPropPanel v-model="alertProps" :schema="alertSchema" title="警示属性" />
        </div>
      </div>
    </div>

    <div id="section-select"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div
        class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">Select</span>
        <span class="font-body-sm text-[11px] text-secondary">自定义下拉选择 — 支持搜索过滤</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[180px]">
        <div class="flex-1 p-ax-lg comp-preview flex flex-col gap-ax-lg items-start justify-center">
          <div>
            <AxSelect v-model="selectProps.value" :size="selectProps.size" :rounded="selectProps.rounded" :options="demoSelectOptions"
              :searchable="selectProps.searchable" :multiple="selectProps.multiple"
              :placeholder="selectProps.placeholder" :placement="selectProps.placement"
              :dropdown-width="selectProps.dropdownWidth" :dropdown-max-width="selectProps.dropdownMaxWidth"
              :tag-max-width="selectProps.tagMaxWidth" :trigger-width="selectProps.triggerWidth"
              :trigger-max-width="selectProps.triggerMaxWidth" />
          </div>
          <div class="flex  items-center gap-2">
            <span class="font-label-md text-[10px] text-secondary">带搜索的选择器：</span>
            <AxSelect size="lg" model-value="opt2" :options="demoSelectOptions" searchable placeholder="选择框架..." />
          </div>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto">
          <AxPropPanel v-model="selectProps" :schema="selectSchema" title="下拉选择属性" />
        </div>
      </div>
    </div>

    <div id="section-tooltip"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div
        class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">Tooltip</span>
        <span class="font-body-sm text-[11px] text-secondary">悬停提示气泡 — 8 个方向，Floating UI 精准定位</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[180px]">
        <div class="flex-1 p-ax-lg comp-preview flex flex-col gap-ax-lg items-center justify-center">
          <AxTooltip :content="tooltipProps.content" :placement="tooltipProps.placement" :arrow="tooltipProps.arrow"
            :offset="tooltipProps.offset">
            <AxButton size="lg" variant="outline">悬停此处查看效果</AxButton>
          </AxTooltip>
          <div class="flex flex-wrap gap-ax-sm justify-center">
            <AxTooltip content="top 提示" placement="top">
              <AxButton variant="ghost"  size="lg">上方</AxButton>
            </AxTooltip>
            <AxTooltip content="bottom 提示" placement="bottom">
              <AxButton variant="ghost"  size="lg">下方</AxButton>
            </AxTooltip>
            <AxTooltip content="left 提示" placement="left">
              <AxButton variant="ghost"  size="lg">左侧</AxButton>
            </AxTooltip>
            <AxTooltip content="right 提示" placement="right">
              <AxButton variant="ghost"  size="lg">右侧</AxButton>
            </AxTooltip>
            <AxTooltip content="top-start 提示" placement="top-start">
              <AxButton variant="ghost"  size="lg">左上角</AxButton>
            </AxTooltip>
            <AxTooltip content="top-end 提示" placement="top-end">
              <AxButton variant="ghost"  size="lg">右上角</AxButton>
            </AxTooltip>
          </div>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto">
          <AxPropPanel v-model="tooltipProps" :schema="tooltipSchema" title="气泡属性" />
        </div>
      </div>
    </div>

    <div id="section-dropdown"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div
        class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">Dropdown</span>
        <span class="font-body-sm text-[11px] text-secondary">上下文菜单 — 任意 Slot 内容，Floating UI 定位</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[180px]">
        <div class="flex-1 p-ax-lg comp-preview flex items-center justify-center gap-ax-xl">
          <div class="flex flex-col items-center gap-ax-sm">
            <span class="font-label-md text-[10px] text-secondary">功能菜单</span>
            <AxDropdown v-model="showDropdownDemo1" :trigger="dropdownProps.trigger"
              :placement="dropdownProps.placement" :offset="dropdownProps.offset"
              :match-width="dropdownProps.matchWidth" :menu-width="dropdownProps.menuWidth"
              :menu-max-width="dropdownProps.menuMaxWidth" :teleport="dropdownProps.teleport"
              :menu-class="dropdownProps.menuWidth || dropdownProps.matchWidth ? '' : 'w-44'">
              <template #trigger>
                <AxButton size="lg">打开菜单<template #suffix><span
                      class="material-symbols-outlined text-[16px]">expand_more</span></template>
                </AxButton>
              </template>
              <template #default="{ close }">
                <div class="py-1">
                  <button
                    class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-primary hover:bg-surface-container-low rounded-lg transition-colors"
                    @click="close()"><span
                      class="material-symbols-outlined text-[16px]">download</span><span>导出配置</span></button>
                  <button
                    class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-primary hover:bg-surface-container-low rounded-lg transition-colors"
                    @click="close()"><span
                      class="material-symbols-outlined text-[16px]">edit</span><span>编辑设置</span></button>
                  <div class="my-1 border-t border-outline-variant"></div>
                  <button
                    class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-error hover:bg-error-container hover:text-on-error-container rounded-lg transition-colors"
                    @click="close()"><span
                      class="material-symbols-outlined text-[16px]">delete</span><span>删除</span></button>
                </div>
              </template>
            </AxDropdown>
          </div>
          <div class="flex flex-col items-center gap-ax-sm">
            <span class="font-label-md text-[10px] text-secondary">图标按钮触发</span>
            <AxDropdown v-model="showDropdownDemo2" placement="bottom-end" menu-class="w-40">
              <template #trigger>
                <AxButton variant="outline"  size="lg"><span
                    class="material-symbols-outlined text-[16px]">more_vert</span></AxButton>
              </template>
              <template #default="{ close }">
                <div class="py-1">
                  <button
                    class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-primary hover:bg-surface-container-low rounded-lg transition-colors"
                    @click="close()"><span
                      class="material-symbols-outlined text-[16px]">info</span><span>查看详情</span></button>
                  <button
                    class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-primary hover:bg-surface-container-low rounded-lg transition-colors"
                    @click="close()"><span
                      class="material-symbols-outlined text-[16px]">share</span><span>分享链接</span></button>
                </div>
              </template>
            </AxDropdown>
          </div>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto">
          <AxPropPanel v-model="dropdownProps" :schema="dropdownSchema" title="下拉菜单属性" />
        </div>
      </div>
    </div>

    <div id="section-popover"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div
        class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">Popover</span>
        <span class="font-body-sm text-[11px] text-secondary">通用浮层容器 — 支持 click/hover/contextmenu 三种触发，内容完全由 Slot
          自定义</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[220px]">
        <div class="flex-1 p-ax-lg comp-preview flex items-center justify-center gap-ax-xl">
          <!-- 通知卡片 (click) -->
          <div class="flex flex-col items-center gap-ax-sm">
            <span class="font-label-md text-[10px] text-secondary">通知卡片</span>
            <AxDropdown v-model="showPopoverDemo1" :trigger="popoverProps.trigger" :placement="popoverProps.placement"
              :offset="popoverProps.offset" :teleport="popoverProps.teleport"
              :menu-width="popoverProps.width || undefined" :menu-max-width="popoverProps.maxWidth || undefined"
              :panel-class="popoverProps.width ? 'p-0' : 'p-0 w-64'">
              <template #trigger>
                <AxButton size="lg" variant="outline">
                  <template #prefix><span class="material-symbols-outlined text-[16px]">notifications</span></template>
                  查看通知
                </AxButton>
              </template>
              <template #default="{ close }">
                <!-- 标题栏（纯 slot 实现） -->
                <div
                  class="flex items-center justify-between px-ax-md py-ax-sm border-b border-outline-variant bg-surface-container-low">
                  <div class="flex items-center gap-ax-sm">
                    <span class="material-symbols-outlined text-[16px] text-primary">{{ popoverProps.icon }}</span>
                    <span class="font-headline-sm text-[13px] font-semibold text-primary">{{ popoverProps.title
                      }}</span>
                  </div>
                  <button
                    class="w-6 h-6 flex items-center justify-center text-secondary hover:bg-surface-container-low rounded-lg transition-colors"
                    @click="close()"><span class="material-symbols-outlined text-[14px]">close</span></button>
                </div>
                <!-- 内容 -->
                <div class="p-ax-md space-y-ax-sm">
                  <div class="flex items-start gap-ax-sm p-ax-sm bg-surface-container-low rounded-lg">
                    <span class="material-symbols-outlined text-[16px] text-primary mt-0.5">info</span>
                    <div class="min-w-0">
                      <p class="font-body-sm text-[12px] font-semibold text-primary">系统更新 v2.4.0</p>
                      <p class="font-body-sm text-[11px] text-secondary leading-relaxed">新增 Popover 组件，支持富内容展示。</p>
                    </div>
                  </div>
                  <div class="flex items-start gap-ax-sm p-ax-sm bg-surface-container-low rounded-lg">
                    <span class="material-symbols-outlined text-[16px] text-primary mt-0.5">schedule</span>
                    <div class="min-w-0">
                      <p class="font-body-sm text-[12px] font-semibold text-primary">定时备份完成</p>
                      <p class="font-body-sm text-[11px] text-secondary leading-relaxed">数据库已于 02:00 自动备份至云端。</p>
                    </div>
                  </div>
                  <button
                    class="w-full border border-outline-variant text-primary rounded-md py-1.5 font-label-md text-label-md hover:bg-surface-container-low transition-colors"
                    @click="close()">查看全部通知</button>
                </div>
              </template>
            </AxDropdown>
          </div>

          <!-- 悬停触发 -->
          <div class="flex flex-col items-center gap-ax-sm">
            <span class="font-label-md text-[10px] text-secondary">悬停触发</span>
            <AxDropdown v-model="showPopoverDemo2" trigger="hover" placement="bottom" panel-class="p-ax-md">
              <template #trigger>
                <AxButton variant="outline"  size="lg">悬停此处</AxButton>
              </template>
              <template #default="{ close }">
                <div class="w-48 space-y-ax-sm">
                  <p class="font-body-sm text-[12px] text-on-surface-variant leading-relaxed">鼠标悬停即可展示。移入面板后不会关闭。</p>
                  <div class="flex gap-ax-xs justify-end">
                    <AxButton variant="outline"  size="lg" @click="close()">知道了</AxButton>
                  </div>
                </div>
              </template>
            </AxDropdown>
          </div>

          <!-- 右键菜单 -->
          <div class="flex flex-col items-center gap-ax-sm">
            <span class="font-label-md text-[10px] text-secondary">右键菜单 (AxDropdown)</span>
            <AxDropdown v-model="showPopoverDemo3" trigger="contextmenu" placement="bottom-start" panel-class="p-0.5">
              <template #trigger>
                <div
                  class="px-4 py-2 border border-dashed border-outline-variant rounded-lg flex items-center gap-ax-sm text-secondary font-label-md text-[11px] cursor-context-menu select-none">
                  <span class="material-symbols-outlined text-[16px]">mouse</span>
                  <span>在此区域右键点击</span>
                </div>
              </template>
              <template #default="{ close }">
                <div class="w-44 py-1">
                  <button
                    class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-primary hover:bg-surface-container-low rounded-lg transition-colors"
                    @click="close()">
                    <span class="material-symbols-outlined text-[16px]">arrow_back</span><span>向后</span>
                    <kbd class="ml-auto font-label-md text-[10px] text-outline">⌘[</kbd>
                  </button>
                  <button
                    class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-primary hover:bg-surface-container-low rounded-lg transition-colors opacity-40 pointer-events-none">
                    <span class="material-symbols-outlined text-[16px]">arrow_forward</span><span>向前</span>
                    <kbd class="ml-auto font-label-md text-[10px] text-outline">⌘]</kbd>
                  </button>
                  <button
                    class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-primary hover:bg-surface-container-low rounded-lg transition-colors"
                    @click="close()">
                    <span class="material-symbols-outlined text-[16px]">refresh</span><span>重新加载</span>
                    <kbd class="ml-auto font-label-md text-[10px] text-outline">⌘R</kbd>
                  </button>
                  <div class="my-1 border-t border-outline-variant"></div>
                  <button
                    class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-primary hover:bg-surface-container-low rounded-lg transition-colors"
                    @click="close()">
                    <span class="material-symbols-outlined text-[16px]">save_alt</span><span>另存为...</span>
                    <kbd class="ml-auto font-label-md text-[10px] text-outline">⌘S</kbd>
                  </button>
                  <div class="my-1 border-t border-outline-variant"></div>
                  <button
                    class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-primary hover:bg-surface-container-low rounded-lg transition-colors"
                    @click="close()">
                    <span class="material-symbols-outlined text-[16px]">print</span><span>打印...</span>
                    <kbd class="ml-auto font-label-md text-[10px] text-outline">⌘P</kbd>
                  </button>
                  <button
                    class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-primary hover:bg-surface-container-low rounded-lg transition-colors"
                    @click="close()">
                    <span class="material-symbols-outlined text-[16px]">cast</span><span>投射...</span>
                  </button>
                  <div class="my-1 border-t border-outline-variant"></div>
                  <button
                    class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-[12px] text-primary hover:bg-surface-container-low rounded-lg transition-colors"
                    @click="close()">
                    <span class="material-symbols-outlined text-[16px]">check</span><span>查找...</span>
                  </button>
                  <button
                    class="flex w-full items-center gap-ax-sm px-3 py-1.5 text-left font-label-md text-label-md text-primary hover:bg-surface-container-low rounded-lg transition-colors"
                    @click="close()">
                    <span class="w-4"></span><span>更多工具</span>
                    <span class="ml-auto material-symbols-outlined text-[16px] text-secondary">chevron_right</span>
                  </button>
                </div>
              </template>
            </AxDropdown>
          </div>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto">
          <AxPropPanel v-model="popoverProps" :schema="popoverSchema" title="气泡卡片属性" />
        </div>
      </div>
    </div>

    <div id="section-dialog"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div
        class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">Dialog</span>
        <span class="font-body-sm text-[11px] text-secondary">模态弹窗 — 焦点陷阱、ESC 关闭、遮罩关闭</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[180px]">
        <div class="flex-1 p-ax-lg comp-preview flex flex-col gap-ax-md items-center justify-center">
          <div class="flex gap-ax-sm flex-wrap justify-center">
            <AxButton size="lg" @click="emit('open-dialog')">打开确认对话框</AxButton>
            <AxButton size="lg" variant="outline" @click="emit('open-simple-dialog')">打开简单提示框</AxButton>
          </div>
          <p class="font-body-sm text-[11px] text-secondary">点击上方按钮打开对话框，可通过 ESC 键或点击遮罩关闭。</p>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto flex items-center">
          <p class="font-body-sm text-[11px] text-secondary leading-relaxed">
            Dialog 支持 <code class="bg-surface-container px-1 rounded text-primary">#header</code>、
            <code class="bg-surface-container px-1 rounded text-primary">#default</code>、
            <code class="bg-surface-container px-1 rounded text-primary">#footer</code> 三个插槽。Footer 槽的 close
            参数可直接关闭弹窗。焦点锁定通过 Tab 键循环限制在对话框内部。
          </p>
        </div>
      </div>
    </div>

    <!-- Notify -->
    <div id="section-notify"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div
        class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">Notify</span>
        <span class="font-body-sm text-[11px] text-secondary">通知气泡 — 4 种语义、自动关闭、关闭按钮、日志记录</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[320px]">
        <div class="flex-1 p-ax-lg comp-preview flex flex-col gap-ax-lg items-start justify-center">
          <!-- Static preview: all 4 types -->
          <div class="w-full space-y-ax-sm">
            <span class="font-label-md text-[10px] text-secondary">所有类型静态预览：</span>
            <!-- Info -->
            <div
              class="flex items-start gap-ax-sm bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md pro-shadow w-80 text-left">
              <span class="material-symbols-outlined mt-0.5 text-primary text-[18px]">info</span>
              <div class="flex-1">
                <h4 class="font-headline-sm text-body-md font-semibold text-primary mb-0.5">信息通知</h4>
                <p class="font-body-sm text-body-sm text-on-surface-variant leading-normal">系统服务已启动，运行状态正常。</p>
              </div>
              <button
                class="w-6 h-6 flex items-center justify-center text-secondary hover:bg-surface-container-low rounded-lg transition-colors shrink-0">
                <span class="material-symbols-outlined text-[16px]">close</span>
              </button>
            </div>
            <!-- Success -->
            <div
              class="flex items-start gap-ax-sm bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md pro-shadow w-80 text-left">
              <span class="material-symbols-outlined mt-0.5 text-primary text-[18px]">check_circle</span>
              <div class="flex-1">
                <h4 class="font-headline-sm text-body-md font-semibold text-primary mb-0.5">操作成功</h4>
                <p class="font-body-sm text-body-sm text-on-surface-variant leading-normal">配置已成功保存至云端，将在下次启动时自动加载。</p>
              </div>
              <button
                class="w-6 h-6 flex items-center justify-center text-secondary hover:bg-surface-container-low rounded-lg transition-colors shrink-0">
                <span class="material-symbols-outlined text-[16px]">close</span>
              </button>
            </div>
            <!-- Error -->
            <div
              class="flex items-start gap-ax-sm bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md pro-shadow w-80 text-left">
              <span class="material-symbols-outlined mt-0.5 text-error text-[18px]">error</span>
              <div class="flex-1">
                <h4 class="font-headline-sm text-body-md font-semibold text-primary mb-0.5">连接中断</h4>
                <p class="font-body-sm text-body-sm text-on-surface-variant leading-normal">核心服务连接已断开，请检查网络后重试。</p>
              </div>
              <button
                class="w-6 h-6 flex items-center justify-center text-secondary hover:bg-surface-container-low rounded-lg transition-colors shrink-0">
                <span class="material-symbols-outlined text-[16px]">close</span>
              </button>
            </div>
            <!-- Secondary -->
            <div
              class="flex items-start gap-ax-sm bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md pro-shadow w-80 text-left">
              <span class="material-symbols-outlined mt-0.5 text-secondary text-[18px]">settings</span>
              <div class="flex-1">
                <h4 class="font-headline-sm text-body-md font-semibold text-primary mb-0.5">系统设置</h4>
                <p class="font-body-sm text-body-sm text-on-surface-variant leading-normal">数据缓存清理完毕，释放空间 12.8 MB。</p>
              </div>
              <button
                class="w-6 h-6 flex items-center justify-center text-secondary hover:bg-surface-container-low rounded-lg transition-colors shrink-0">
                <span class="material-symbols-outlined text-[16px]">close</span>
              </button>
            </div>
          </div>

          <!-- Interactive triggers -->
          <div class="flex items-center gap-ax-md">
            <span class="font-label-md text-[10px] text-secondary self-center">动态触发：</span>
            <AxButton  size="lg" @click="handleNotifyShow">
              <template #prefix><span class="material-symbols-outlined text-[16px]">notifications</span></template>
              发送通知
            </AxButton>
          </div>

          <!-- Stats area -->
          <div v-if="notifyProps.showActions" class="flex flex-wrap gap-ax-md w-full max-w-md">
            <div class="flex items-center gap-ax-sm bg-surface-container-low rounded-lg px-3 py-2">
              <span class="font-body-sm text-[11px] text-secondary">活跃通知数：</span>
              <span class="font-headline-sm text-[14px] text-primary">{{ notify.activeNotificationCount }}</span>
            </div>
            <div class="flex items-center gap-ax-sm bg-surface-container-low rounded-lg px-3 py-2">
              <span class="font-body-sm text-[11px] text-secondary">日志总数：</span>
              <span class="font-headline-sm text-[14px] text-primary">{{ notify.notificationHistory.value.length }}</span>
            </div>
            <AxButton variant="outline"  size="lg" @click="notify.clearLogs()">
              <template #prefix><span class="material-symbols-outlined text-[16px]">delete</span></template>
              清空日志
            </AxButton>
          </div>
          <p class="font-body-sm text-[11px] text-secondary">通知 4 秒后自动关闭，也可点 × 手动关闭。基于 <code
              class="bg-surface-container px-1 rounded text-primary">vue-sonner</code> 的 <code
              class="bg-surface-container px-1 rounded text-primary">toast.custom()</code> 渲染。</p>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto">
          <AxPropPanel v-model="notifyProps" :schema="notifySchema" title="通知属性" />
        </div>
      </div>
    </div>

    <!-- FloatingBall -->
    <div id="section-floating-ball"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div
        class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">FloatingBall</span>
        <span class="font-body-sm text-[11px] text-secondary">可拖拽悬浮球 — 支持贴边、展开菜单、亮暗主题、缩小模式</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[280px]">
        <div class="flex-1 p-ax-lg comp-preview flex flex-col gap-ax-md items-center justify-center">
          <!-- Static preview balls -->
          <div class="flex flex-wrap items-center gap-ax-xl">
            <!-- Normal size -->
            <div class="flex flex-col items-center gap-ax-sm">
              <span class="font-label-md text-[10px] text-secondary">标准尺寸</span>
              <div
                class="size-[36px] flex items-center justify-center rounded-full shadow-md border border-gray-100/90 bg-white shadow-black/10"
                :class="ballPrefs.hidden ? 'opacity-30' : ''">
                <span
                  class="relative flex items-center justify-center rounded-full bg-gradient-to-br from-ball-light to-ball text-white shadow-sm shadow-ball/40"
                  :style="{ width: '30px', height: '30px' }">
                  <span class="text-[11px] font-extrabold italic leading-none tracking-tight text-white">{{
                    ballPrefs.label
                    || 'FB' }}</span>
                </span>
              </div>
            </div>
            <!-- Shrunk -->
            <div class="flex flex-col items-center gap-ax-sm">
              <span class="font-label-md text-[10px] text-secondary">缩小模式</span>
              <div
                class="size-[30px] flex items-center justify-center rounded-full shadow-md border border-gray-100/90 bg-white shadow-black/10">
                <span
                  class="relative flex items-center justify-center rounded-full bg-gradient-to-br from-ball-light to-ball text-white shadow-sm shadow-ball/40"
                  :style="{ width: '24px', height: '24px' }">
                  <span class="text-[9px] font-extrabold italic leading-none tracking-tight text-white">{{
                    ballPrefs.label
                    || 'FB' }}</span>
                </span>
              </div>
            </div>
            <!-- Expanded with settings -->
            <div class="flex flex-col items-center gap-ax-sm">
              <span class="font-label-md text-[10px] text-secondary">展开态（带设置按钮）</span>
              <div class="relative flex flex-col items-center gap-ax-xs">
                <div
                  class="size-[36px] flex items-center justify-center rounded-full shadow-md border border-gray-100/90 bg-white shadow-black/10">
                  <span
                    class="relative flex items-center justify-center rounded-full bg-gradient-to-br from-ball-light to-ball text-white shadow-sm shadow-ball/40"
                    :style="{ width: '30px', height: '30px' }">
                    <span class="text-[11px] font-extrabold italic leading-none tracking-tight text-white">{{
                      ballPrefs.label || 'FB' }}</span>
                  </span>
                </div>
                <div
                  class="size-[36px] flex items-center justify-center rounded-full shadow-sm border border-gray-100/80 bg-white text-gray-500">
                  <svg viewBox="0 0 24 24" fill="none" class="size-[18px] text-ball">
                    <rect x="3" y="3" width="18" height="18" rx="4" stroke="currentColor" stroke-width="1.5" />
                    <path d="M6 9h12M8 14h8M10 19h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                    <circle cx="6" cy="9" r="1.5" fill="currentColor" />
                    <circle cx="16" cy="14" r="1.5" fill="currentColor" />
                    <circle cx="12" cy="19" r="1.5" fill="currentColor" />
                  </svg>
                </div>
              </div>
            </div>
            <!-- Dark theme -->
            <div class="flex flex-col items-center gap-ax-sm">
              <span class="font-label-md text-[10px] text-secondary">暗色主题</span>
              <div
                class="size-[36px] flex items-center justify-center rounded-full shadow-md border border-white/12 bg-zinc-800 shadow-black/40">
                <span
                  class="relative flex items-center justify-center rounded-full bg-gradient-to-br from-ball-light to-ball text-white shadow-sm shadow-ball/40"
                  :style="{ width: '30px', height: '30px' }">
                  <span class="text-[11px] font-extrabold italic leading-none tracking-tight text-white">{{
                    ballPrefs.label
                    || 'FB' }}</span>
                </span>
              </div>
            </div>
          </div>

          <!-- Control buttons -->
          <div class="flex gap-ax-sm mt-ax-md">
            <button
              class="relative overflow-hidden inline-flex items-center justify-center gap-ax-xs font-label-md rounded-md transition-colors outline-none border-0 shrink-0 bg-primary text-on-primary hover:opacity-90 px-4 py-1.5 text-label-md cursor-pointer"
              @click="showBall = !showBall">
              {{ showBall ? '隐藏页面悬浮球' : '在页面上展示悬浮球' }}
            </button>
          </div>
          <p class="font-body-sm text-[11px] text-secondary">点击上方按钮将悬浮球渲染到页面中（固定定位，可在右下角找到）。</p>
          <p class="font-body-sm text-[11px] text-secondary">支持拖拽、贴边吸附、悬停展开菜单、点击齿轮打开设置弹窗。</p>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto">
          <AxPropPanel v-model="ballPrefs" :schema="ballSchema" title="悬浮球属性" />
        </div>
      </div>
    </div>

    <!-- AxImage -->
    <div id="section-image"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">Image</span>
        <span class="font-body-sm text-[11px] text-secondary">懒加载图片 — 加载/成功/失败三态、点击放大预览、hover 图标、自适应宽高比</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[340px]">
        <div class="flex-1 p-ax-lg comp-preview flex flex-col gap-ax-md items-start justify-center">
          <div class="flex flex-wrap items-start gap-ax-xl">
            <div class="flex flex-col items-center gap-ax-sm">
              <span class="font-label-md text-[10px] text-secondary">动态预览</span>
              <div class="w-56 h-40 rounded-lg overflow-hidden border border-outline-variant">
                <AxImage :src="imageProps.src" :alt="imageProps.alt" :object-fit="imageProps.objectFit"
                  :adaptive-aspect="imageProps.adaptiveAspect" />
              </div>
            </div>
            <div class="flex flex-col gap-ax-sm">
              <span class="font-label-md text-[10px] text-secondary">各种状态：</span>
              <div class="flex gap-ax-sm flex-wrap">
                <div class="flex flex-col items-center gap-ax-xs">
                  <div class="w-28 h-20 rounded-lg overflow-hidden border border-outline-variant">
                    <AxImage src="https://picsum.photos/seed/normal/320/240" alt="正常" />
                  </div>
                  <span class="font-body-sm text-[10px] text-outline">正常加载</span>
                </div>
                <div class="flex flex-col items-center gap-ax-xs">
                  <div class="w-28 h-20 rounded-lg overflow-hidden border border-outline-variant">
                    <AxImage src="https://invalid.example/404.jpg" alt="失败" />
                  </div>
                  <span class="font-body-sm text-[10px] text-outline">加载失败（可重试）</span>
                </div>
                <div class="flex flex-col items-center gap-ax-xs">
                  <div class="w-28 h-20 rounded-lg overflow-hidden border border-outline-variant">
                    <AxImage src="https://picsum.photos/seed/contain/320/240" alt="Contain" object-fit="contain" />
                  </div>
                  <span class="font-body-sm text-[10px] text-outline">Contain 模式</span>
                </div>
              </div>
            </div>
          </div>
          <p class="font-body-sm text-[11px] text-secondary">点击已加载图片触发 <code class="bg-surface-container px-1 rounded text-primary">preview</code> 事件（可接入 ImageViewer 放大浏览）。</p>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto">
          <AxPropPanel v-model="imageProps" :schema="imageSchema" title="图片属性" />
        </div>
      </div>
    </div>

    <!-- AxJsonViewer -->
    <div id="section-json-viewer"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">JsonViewer</span>
        <span class="font-body-sm text-[11px] text-secondary">可折叠 JSON 树查看器 — 递归展开/折叠、Ctrl+点击深层切换、语法高亮</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[360px]">
        <div class="flex-1 p-ax-lg comp-preview flex flex-col gap-ax-sm items-start justify-center">
          <div class="w-full max-w-lg bg-surface-container-low rounded-lg border border-outline-variant p-ax-md">
            <AxJsonViewer :data="sampleJson" :expand-level="jsonViewerProps.expandLevel"
              :wrap-enabled="jsonViewerProps.wrapEnabled" is-root />
          </div>
          <p class="font-body-sm text-[11px] text-secondary">点击箭头展开/折叠节点，<kbd class="font-label-md text-[10px] bg-surface-container border border-outline-variant px-1 rounded">Ctrl</kbd> + 点击递归展开/折叠所有子节点。</p>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto">
          <AxPropPanel v-model="jsonViewerProps" :schema="jsonViewerSchema" title="JSON属性" />
        </div>
      </div>
    </div>

    <!-- AxImageViewer -->
    <div id="section-image-viewer"
      class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div class="px-ax-md py-ax-sm border-b border-outline-variant flex items-center gap-ax-sm bg-surface-container-low">
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">ImageViewer</span>
        <span class="font-body-sm text-[11px] text-secondary">全屏图片查看器 — 缩放/旋转/翻转/键盘快捷键/下载</span>
      </div>
      <div class="flex divide-x divide-outline-variant min-h-[260px]">
        <div class="flex-1 p-ax-lg comp-preview flex flex-col gap-ax-lg items-center justify-center">
          <div class="flex flex-wrap items-center gap-ax-lg">
            <div class="flex flex-col items-center gap-ax-sm">
              <span class="font-label-md text-[10px] text-secondary">点击打开查看器</span>
              <AxButton size="lg" variant="primary" icon="open_in_full" @click="showImageViewer = true">
                浏览 {{ demoImages.length }} 张图片
              </AxButton>
            </div>
            <div class="flex -space-x-2">
              <img v-for="(img, i) in demoImages.slice(0, 4)" :key="i" :src="img"
                class="w-14 h-10 rounded-md border-2 border-surface-container-lowest object-cover shadow-sm"
                :style="{ zIndex: demoImages.length - i }" />
            </div>
          </div>
          <div class="flex flex-wrap gap-ax-sm text-center">
            <span class="font-label-md text-[10px] text-secondary">键盘快捷键：</span>
            <kbd class="font-label-md text-[10px] bg-surface-container border border-outline-variant px-1.5 py-0.5 rounded text-primary">← →</kbd><span class="font-body-sm text-[10px] text-outline">切换</span>
            <kbd class="font-label-md text-[10px] bg-surface-container border border-outline-variant px-1.5 py-0.5 rounded text-primary">+ -</kbd><span class="font-body-sm text-[10px] text-outline">缩放</span>
            <kbd class="font-label-md text-[10px] bg-surface-container border border-outline-variant px-1.5 py-0.5 rounded text-primary">R</kbd><span class="font-body-sm text-[10px] text-outline">旋转</span>
            <kbd class="font-label-md text-[10px] bg-surface-container border border-outline-variant px-1.5 py-0.5 rounded text-primary">F</kbd><span class="font-body-sm text-[10px] text-outline">翻转</span>
            <kbd class="font-label-md text-[10px] bg-surface-container border border-outline-variant px-1.5 py-0.5 rounded text-primary">Esc</kbd><span class="font-body-sm text-[10px] text-outline">关闭</span>
          </div>
        </div>
        <div class="w-84 p-ax-md bg-surface-container-lowest overflow-y-auto flex items-start">
          <div class="space-y-ax-sm w-full">
            <p class="font-body-sm text-[11px] text-secondary leading-relaxed">
              ImageViewer 基于 <code class="bg-surface-container px-1 rounded text-primary">Teleport to body</code> 全屏覆盖渲染。
              支持鼠标滚轮缩放、拖拽平移、工具栏旋转/翻转，自动下载（fallback 新窗口打开）。
            </p>
            <div class="flex gap-ax-xs">
              <span v-for="(img, i) in demoImages" :key="i"
                class="w-10 h-8 rounded bg-surface-container border border-outline-variant overflow-hidden">
                <img :src="img" class="w-full h-full object-cover opacity-60 hover:opacity-100 transition-opacity" />
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- AxImageViewer instance -->
    <AxImageViewer :images="demoImages" :initial-index="0" v-model:visible="showImageViewer" />
  </div>

  <!-- FloatingBall (rendered to document body) -->
  <FloatingBall v-if="showBall" :prefs="ballPrefs" @save-prefs="handleBallSave" @main-click="() => { }"
    @open-settings="() => { }" />
</template>
