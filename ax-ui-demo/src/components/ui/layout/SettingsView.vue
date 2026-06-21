<script setup lang="ts">
import type { SelectOption } from '../types'

export interface AppSettings {
  language: string
  timezone: string
  consoleName: string
  theme: string
  autoSave: boolean
  workerCount: string
  hwAccel: boolean
  sessionTimeout: number
  twoFactor: boolean
  ipWhitelist: boolean
  ipList: string
  dbAddress: string
  startupScript: string
  debugMode: boolean
  notifications: {
    cpuAlert: boolean
    securityAlert: boolean
    backupComplete: boolean
    loginAlert: boolean
    updateAvailable: boolean
  }
}

defineProps<{
  settings: AppSettings
  cpuLimit: number
  selectedClearance: string
  clearanceOptions: SelectOption[]
}>()

const emit = defineEmits<{
  'update:cpuLimit': [value: number]
  'update:selectedClearance': [value: string]
  reset: []
  save: []
  notify: [message: string, type?: string, title?: string]
}>()

const notifSettings = [
  { key: 'cpuAlert' as const, label: '算力占用告警', desc: '当算力使用率超过 85% 时推送警报' },
  { key: 'securityAlert' as const, label: '安全事件告警', desc: '检测到异常访问或攻击行为时通知' },
  { key: 'backupComplete' as const, label: '备份完成通知', desc: '自动备份任务完成后推送确认消息' },
  { key: 'loginAlert' as const, label: '异地登录提醒', desc: '从未知 IP 或设备登录时发出警告' },
  { key: 'updateAvailable' as const, label: '系统更新提醒', desc: '有新版本可用时在控制台展示通知' },
]

const onCpuChange = (v: number) => emit('update:cpuLimit', v)

const onClearanceChange = (opt: SelectOption | undefined) => {
  if (!opt) return
  emit('update:selectedClearance', String(opt.value))
  emit('notify', `防御权限级别已变更为: ${opt.label.split(' / ')[0]}`, 'secondary', '权限状态变更')
}

type ToggleKey = 'autoSave' | 'hwAccel' | 'twoFactor' | 'ipWhitelist' | 'debugMode'

function toggle(settings: AppSettings, key: ToggleKey) {
  settings[key] = !settings[key]
}

function toggleNotify(settings: AppSettings, key: ToggleKey, msgOn: string, msgOff: string, type?: string) {
  toggle(settings, key)
  emit('notify', settings[key] ? msgOn : msgOff, type)
}
</script>

<template>
  <div class="space-y-ax-lg max-w-2xl">
    <!-- 页头 -->
    <div class="border-b border-outline-variant pb-ax-md">
      <h2 class="font-headline-sm text-headline-md text-primary">系统设置</h2>
      <p class="font-body-sm text-body-sm text-on-surface-variant mt-1">在此配置控制台的全局运行参数、安全策略及个性化选项。</p>
    </div>

    <!-- ═══════ 通用设置 ═══════ -->
    <section id="section-general" class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div class="px-ax-md py-ax-sm border-b border-outline-variant bg-surface-container-low flex items-center gap-ax-sm">
        <span class="material-symbols-outlined text-[16px] text-secondary">tune</span>
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">通用设置</span>
      </div>
      <div class="p-ax-md divide-y divide-outline-variant/40">
        <div class="flex items-center gap-ax-md py-3">
          <div class="flex-1">
            <p class="font-body-sm text-[13px] font-semibold text-primary">系统语言</p>
            <p class="font-body-sm text-[11px] text-secondary mt-0.5">控制台界面显示语言</p>
          </div>
          <div class="w-40 ml-auto">
            <AxSelect
              size="lg"
              v-model="settings.language"
              :options="[
                { value: 'zh', label: '简体中文' },
                { value: 'en', label: 'English' },
                { value: 'ja', label: '日本語' },
                { value: 'ko', label: '한국어' },
              ]"
            />
          </div>
        </div>
        <div class="flex items-center gap-ax-md py-3">
          <div class="flex-1">
            <p class="font-body-sm text-[13px] font-semibold text-primary">时区设置</p>
            <p class="font-body-sm text-[11px] text-secondary mt-0.5">日志时间戳所使用的时区</p>
          </div>
          <div class="w-48 ml-auto">
            <AxSelect
              size="lg"
              v-model="settings.timezone"
              :options="[
                { value: 'asia-shanghai', label: 'Asia/Shanghai (UTC+8)' },
                { value: 'utc', label: 'UTC (UTC+0)' },
                { value: 'us-eastern', label: 'US/Eastern (UTC-5)' },
                { value: 'us-pacific', label: 'US/Pacific (UTC-8)' },
              ]"
            />
          </div>
        </div>
        <div class="flex items-center gap-ax-md py-3">
          <div class="flex-1">
            <p class="font-body-sm text-[13px] font-semibold text-primary">控制台名称</p>
            <p class="font-body-sm text-[11px] text-secondary mt-0.5">显示在顶栏和浏览器标签页中的名称</p>
          </div>
          <AxInput v-model="settings.consoleName"  size="lg" placeholder="Axiom Console" class="!w-44 ml-auto" />
        </div>
        <div class="flex items-center gap-ax-md py-3">
          <div class="flex-1">
            <p class="font-body-sm text-[13px] font-semibold text-primary">外观主题</p>
            <p class="font-body-sm text-[11px] text-secondary mt-0.5">控制台整体配色方案</p>
          </div>
          <div class="flex items-center bg-surface-container rounded-lg p-0.5 gap-0.5 ml-auto">
            <button
              v-for="t in [
                { v: 'light', i: 'light_mode' },
                { v: 'dark', i: 'dark_mode' },
                { v: 'auto', i: 'computer' },
              ]"
              :key="t.v"
              :class="settings.theme === t.v ? 'bg-primary text-on-primary shadow-sm' : 'text-secondary hover:text-primary'"
              class="font-label-md text-[10px] px-2 py-1 rounded-md transition-all flex items-center gap-ax-xs"
              @click="settings.theme = t.v"
            >
              <span class="material-symbols-outlined text-[14px]">{{ t.i }}</span>
              <span>{{ { light: '浅色', dark: '深色', auto: '跟随系统' }[t.v as 'light' | 'dark' | 'auto'] }}</span>
            </button>
          </div>
        </div>
        <div class="flex items-center gap-ax-md py-3">
          <div class="flex-1">
            <p class="font-body-sm text-[13px] font-semibold text-primary">自动保存配置</p>
            <p class="font-body-sm text-[11px] text-secondary mt-0.5">变更后自动持久化系统设置</p>
          </div>
          <button
            role="switch"
            :aria-checked="settings.autoSave"
            :class="settings.autoSave ? 'bg-primary' : 'bg-outline'"
            class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200 focus:outline-none focus:ring-1 focus:ring-primary"
            @click="toggle(settings, 'autoSave')"
          >
            <span
              :class="settings.autoSave ? 'translate-x-4' : 'translate-x-0'"
              class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out"
            />
          </button>
        </div>
      </div>
    </section>

    <!-- ═══════ 性能与算力 ═══════ -->
    <section id="section-performance" class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div class="px-ax-md py-ax-sm border-b border-outline-variant bg-surface-container-low flex items-center gap-ax-sm">
        <span class="material-symbols-outlined text-[16px] text-secondary">speed</span>
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">性能与算力</span>
      </div>
      <div class="p-ax-md space-y-ax-md">
        <div class="space-y-ax-xs">
          <div class="flex items-center justify-between">
            <p class="font-body-sm text-[13px] font-semibold text-primary">算力限制上限</p>
            <span class="font-label-md text-[12px] font-bold text-primary tabular-nums">{{ cpuLimit }}%</span>
          </div>
          <p class="font-body-sm text-[11px] text-secondary">设置系统允许占用的最大计算资源百分比</p>
          <AxSlider
            :model-value="cpuLimit"
            :min="10" :max="100"
            show-labels show-value
            label-left="低功耗 (10%)"
            label-right="全功耗 (100%)"
            :value-label="cpuLimit + '%'"
            @update:model-value="onCpuChange"
          />
        </div>
        <div class="flex items-center gap-ax-md border-t border-outline-variant/40 pt-3">
          <div class="flex-1">
            <p class="font-body-sm text-[13px] font-semibold text-primary">后台任务并发数</p>
            <p class="font-body-sm text-[11px] text-secondary mt-0.5">同时运行的最大后台工作线程数量</p>
          </div>
          <div class="w-32 ml-auto">
            <AxSelect
              size="lg"
              v-model="settings.workerCount"
              :options="[
                { value: '1', label: '1 线程' },
                { value: '2', label: '2 线程' },
                { value: '4', label: '4 线程' },
                { value: '8', label: '8 线程' },
                { value: '16', label: '16 线程' },
              ]"
            />
          </div>
        </div>
        <div class="flex items-center gap-ax-md border-t border-outline-variant/40 pt-3">
          <div class="flex-1">
            <p class="font-body-sm text-[13px] font-semibold text-primary">硬件加速</p>
            <p class="font-body-sm text-[11px] text-secondary mt-0.5">启用 GPU 加速渲染提升界面流畅度</p>
          </div>
          <button
            role="switch"
            :aria-checked="settings.hwAccel"
            :class="settings.hwAccel ? 'bg-primary' : 'bg-outline'"
            class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200"
            @click="toggleNotify(settings, 'hwAccel', '硬件加速已启用', '硬件加速已关闭', 'info')"
          >
            <span
              :class="settings.hwAccel ? 'translate-x-4' : 'translate-x-0'"
              class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out"
            />
          </button>
        </div>
      </div>
    </section>

    <!-- ═══════ 安全与权限 ═══════ -->
    <section id="section-security" class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div class="px-ax-md py-ax-sm border-b border-outline-variant bg-surface-container-low flex items-center gap-ax-sm">
        <span class="material-symbols-outlined text-[16px] text-secondary">security</span>
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">安全与权限</span>
      </div>
      <div class="p-ax-md divide-y divide-outline-variant/40">
        <div class="flex items-center gap-ax-md pb-3">
          <div class="flex-1">
            <p class="font-body-sm text-[13px] font-semibold text-primary">防御等级</p>
            <p class="font-body-sm text-[11px] text-secondary mt-0.5">系统安全扫描与防御响应强度</p>
          </div>
          <div class="w-52 ml-auto">
            <AxSelect
              size="lg"
              :model-value="selectedClearance"
              :options="clearanceOptions"
              searchable
              search-placeholder="检索防御权限..."
              @update:model-value="(v: string | number) => onClearanceChange(clearanceOptions.find((o) => o.value === v))"
            />
          </div>
        </div>
        <div class="py-3">
          <div class="flex items-center justify-between">
            <p class="font-body-sm text-[13px] font-semibold text-primary">会话超时时间</p>
            <span class="font-label-md text-[12px] font-bold text-primary tabular-nums">{{ settings.sessionTimeout }} 分钟</span>
          </div>
          <p class="font-body-sm text-[11px] text-secondary mt-0.5 mb-2">无操作自动注销的等待时间（分钟）</p>
          <AxSlider
            v-model="settings.sessionTimeout"
            :min="5" :max="120" :step="5"
            show-labels show-value
            label-left="5 分钟"
            label-right="120 分钟"
            :value-label="settings.sessionTimeout + ' 分钟'"
          />
        </div>
        <div class="flex items-center gap-ax-md py-3">
          <div class="flex-1">
            <p class="font-body-sm text-[13px] font-semibold text-primary">双因素认证</p>
            <p class="font-body-sm text-[11px] text-secondary mt-0.5">登录时强制要求二次身份验证</p>
          </div>
          <button
            role="switch"
            :aria-checked="settings.twoFactor"
            :class="settings.twoFactor ? 'bg-primary' : 'bg-outline'"
            class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200"
            @click="toggleNotify(settings, 'twoFactor', '双因素认证已启用', '双因素认证已关闭，请注意安全风险', settings.twoFactor ? 'success' : 'error')"
          >
            <span
              :class="settings.twoFactor ? 'translate-x-4' : 'translate-x-0'"
              class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out"
            />
          </button>
        </div>
        <div class="flex items-center gap-ax-md py-3">
          <div class="flex-1">
            <p class="font-body-sm text-[13px] font-semibold text-primary">IP 白名单过滤</p>
            <p class="font-body-sm text-[11px] text-secondary mt-0.5">仅允许来自指定 IP 范围的访问请求</p>
          </div>
          <button
            role="switch"
            :aria-checked="settings.ipWhitelist"
            :class="settings.ipWhitelist ? 'bg-primary' : 'bg-outline'"
            class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200"
            @click="toggle(settings, 'ipWhitelist')"
          >
            <span
              :class="settings.ipWhitelist ? 'translate-x-4' : 'translate-x-0'"
              class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out"
            />
          </button>
        </div>
        <div v-show="settings.ipWhitelist" class="pt-3">
          <label class="font-label-md text-[11px] font-semibold text-primary block mb-1">IP 白名单列表</label>
          <textarea
            v-model="settings.ipList"
            rows="3"
            class="w-full p-2.5 font-label-md text-[11px] bg-surface-container-low border border-outline-variant rounded-md focus:ring-1 focus:ring-primary focus:border-primary resize-none placeholder:text-outline transition-all"
            placeholder="每行输入一个 IP 或 CIDR 段&#10;例如: 192.168.1.0/24&#10;     10.0.0.1"
          />
        </div>
      </div>
    </section>

    <!-- ═══════ 通知与告警 ═══════ -->
    <section id="section-notifications" class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div class="px-ax-md py-ax-sm border-b border-outline-variant bg-surface-container-low flex items-center gap-ax-sm">
        <span class="material-symbols-outlined text-[16px] text-secondary">notifications</span>
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">通知与告警</span>
      </div>
      <div class="p-ax-md divide-y divide-outline-variant/40">
        <div v-for="notif in notifSettings" :key="notif.key" class="flex items-center gap-ax-md py-3">
          <div class="flex-1">
            <p class="font-body-sm text-[13px] font-semibold text-primary">{{ notif.label }}</p>
            <p class="font-body-sm text-[11px] text-secondary mt-0.5">{{ notif.desc }}</p>
          </div>
          <button
            role="switch"
            :aria-checked="settings.notifications[notif.key]"
            :class="settings.notifications[notif.key] ? 'bg-primary' : 'bg-outline'"
            class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200"
            @click="settings.notifications[notif.key] = !settings.notifications[notif.key]"
          >
            <span
              :class="settings.notifications[notif.key] ? 'translate-x-4' : 'translate-x-0'"
              class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out"
            />
          </button>
        </div>
      </div>
    </section>

    <!-- ═══════ 高级配置 ═══════ -->
    <section id="section-advanced" class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
      <div class="px-ax-md py-ax-sm border-b border-outline-variant bg-surface-container-low flex items-center gap-ax-sm">
        <span class="material-symbols-outlined text-[16px] text-secondary">build</span>
        <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">高级配置</span>
      </div>
      <div class="p-ax-md space-y-ax-md divide-y divide-outline-variant/40">
        <div class="pb-3">
          <label class="font-label-md text-[13px] font-semibold text-primary block">数据库连接字符串</label>
          <p class="font-body-sm text-[11px] text-secondary mt-0.5 mb-2">主节点物理地址，支持 MongoDB、PostgreSQL、Redis 格式</p>
          <AxInput v-model="settings.dbAddress" size="lg">
            <template #prefix><span class="material-symbols-outlined text-[16px]">dns</span></template>
          </AxInput>
        </div>
        <div class="pt-3 pb-3">
          <label class="font-label-md text-[13px] font-semibold text-primary block">系统启动脚本</label>
          <p class="font-body-sm text-[11px] text-secondary mt-0.5 mb-2">在服务初始化完成后执行的自定义 Shell 脚本片段</p>
          <textarea
            v-model="settings.startupScript"
            rows="5"
            class="w-full p-3 font-label-md text-[11px] bg-surface-container-low border border-outline-variant rounded-md focus:ring-1 focus:ring-primary focus:border-primary resize-none placeholder:text-outline transition-all"
            placeholder="#!/bin/bash&#10;# 在此输入启动脚本...&#10;echo 'Axiom Console initializing...'"
          />
        </div>
        <div class="flex items-center gap-ax-md pt-3">
          <div class="flex-1">
            <p class="font-body-sm text-[13px] font-semibold text-primary">调试模式</p>
            <p class="font-body-sm text-[11px] text-secondary mt-0.5">开启后将在控制台输出详细调试日志</p>
          </div>
          <button
            role="switch"
            :aria-checked="settings.debugMode"
            :class="settings.debugMode ? 'bg-primary' : 'bg-outline'"
            class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200"
            @click="toggleNotify(settings, 'debugMode', '调试模式已开启，控制台将输出详细日志', '调试模式已关闭', 'secondary')"
          >
            <span
              :class="settings.debugMode ? 'translate-x-4' : 'translate-x-0'"
              class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out"
            />
          </button>
        </div>
        <div class="pt-3 flex justify-end gap-ax-sm">
          <AxButton size="lg" variant="outline" @click="emit('reset')">重置为默认值</AxButton>
          <AxButton size="lg" icon="save" @click="emit('save')">保存所有设置</AxButton>
        </div>
      </div>
    </section>
  </div>
</template>
