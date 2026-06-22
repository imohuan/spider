<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  cpuLimit: number
  backupEnabled: boolean
  selectedClearanceKey: string
  selectedClearanceLevel: number
  latestLatency: number
  latencyHistory: number[]
  sparklinePath: string
  sparklineAreaPath: string
}>()

const openFaq = ref<number | null>(null)
const toggleFaq = (id: number) => {
  openFaq.value = openFaq.value === id ? null : id
}

const faqs = [
  {
    id: 1,
    q: '如何安全地导出系统配置？',
    a: '在设置界面中选择「通用设置」→「自动保存配置」开启后，所有变更会自动持久化。你也可以通过侧边栏用户菜单手动导出当前状态为 JSON 文件。',
  },
  {
    id: 2,
    q: '算力限制达到 100% 会发生什么？',
    a: '系统将自动暂停所有后台低优先级任务，保留核心服务线程运行。前端界面仍可正常操作，但实时数据刷新频率会降低。',
  },
  {
    id: 3,
    q: '双因素认证支持哪些方式？',
    a: '目前支持 TOTP 时间型一次性密码（通过 Google Authenticator、Microsoft Authenticator 等应用生成）以及硬件安全密钥（FIDO2 / WebAuthn）。',
  },
  {
    id: 4,
    q: 'IP 白名单最多支持多少条规则？',
    a: '当前版本支持最多 256 条 IPv4 / IPv6 单地址或 CIDR 段规则。超出限制时最早的规则会被自动移除。',
  },
]

const activities = ref([
  { id: 1, time: '12:05', title: '自动备份完成', desc: '第 1,247 次增量备份成功写入持久化存储', type: 'success' },
  { id: 2, time: '11:42', title: '防御等级变更', desc: '管理员将系统防御等级从 Level 1 提升至 Level 2', type: 'info' },
  { id: 3, time: '10:18', title: '算力告警触发', desc: '实时算力占用达到 87%，超出预设阈值', type: 'warning' },
  { id: 4, time: '09:03', title: '核心服务重启', desc: '内核版本 v2.4.1 热更新完成，零停机切换', type: 'success' },
  { id: 5, time: '08:30', title: '异地登录检测', desc: '检测到来自 203.0.113.45 的新设备登录请求', type: 'error' },
])

const navCards = [
  { icon: 'analytics', label: '实时监控', desc: '查看系统各项核心指标', color: 'bg-primary text-on-primary' },
  { icon: 'shield', label: '安全中心', desc: '管理权限与防御策略', color: 'bg-secondary-container text-on-secondary-container' },
  { icon: 'speed', label: '性能分析', desc: '算力与资源使用详情', color: 'bg-surface-container-high text-primary' },
  { icon: 'notifications', label: '告警日志', desc: '历史通知与事件追踪', color: 'bg-surface-container-high text-primary' },
  { icon: 'backup', label: '备份管理', desc: '增量备份与恢复操作', color: 'bg-surface-container-high text-primary' },
  { icon: 'settings', label: '系统配置', desc: '全局参数与高级选项', color: 'bg-surface-container-high text-primary' },
]

const settingGroups = [
  {
    title: '账户管理',
    items: [
      { icon: 'person', label: '个人资料', desc: '修改显示名称与身份标识' },
      { icon: 'credit_card', label: '计费与配额', desc: '查看资源使用账单与续费' },
      { icon: 'notifications_active', label: '通知偏好', desc: '自定义各类消息的推送渠道' },
      { icon: 'lock', label: '安全设置', desc: '密码、双因素认证与登录历史' },
    ],
  },
  {
    title: '系统运维',
    items: [
      { icon: 'help_outline', label: '帮助中心', desc: '查阅官方文档与常见问题' },
      { icon: 'contact_support', label: '联系支持', desc: '提交工单或联系技术团队' },
      { icon: 'monitoring', label: '运行状态', desc: '查看各子系统的健康状态' },
    ],
  },
]
</script>

<template>
  <div class="space-y-ax-lg">
    <section id="section-overview" class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-lg relative overflow-hidden pro-shadow scroll-mt-4">
      <div class="relative z-10 max-w-xl">
        <div class="flex items-center gap-ax-xs mb-2">
          <span class="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
          <span class="font-label-md text-[10px] text-secondary uppercase tracking-wider">系统运行中</span>
        </div>
        <h1 class="text-headline-lg font-semibold text-primary font-headline-sm mb-ax-sm">控制台概览</h1>
        <p class="font-body-sm text-body-md text-on-surface-variant leading-relaxed">
          实时监控核心集群运行状态，快速访问常用功能模块，浏览最近系统活动记录。
        </p>
      </div>
      <div class="absolute right-0 top-0 bottom-0 w-1/3 bg-gradient-to-l from-surface-container-low to-transparent opacity-40 pointer-events-none"></div>
    </section>

    <div id="section-metrics" class="grid grid-cols-1 md:grid-cols-4 gap-gutter scroll-mt-4">
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md transition-all duration-300 pro-shadow">
        <div class="flex items-center justify-between text-secondary mb-ax-sm">
          <span class="font-label-md text-[11px] uppercase tracking-wider">算力占用</span>
          <span class="material-symbols-outlined text-[16px]">speed</span>
        </div>
        <div class="flex items-baseline gap-ax-xs">
          <span class="text-3xl font-bold font-headline-sm text-primary tracking-tight">{{ cpuLimit }}</span>
          <span class="text-secondary font-label-md text-xs">%</span>
        </div>
        <div class="w-full bg-surface-container h-1.5 rounded-full mt-3 overflow-hidden">
          <div class="h-full bg-primary transition-all duration-300" :style="{ width: cpuLimit + '%' }"></div>
        </div>
      </div>

      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md pro-shadow">
        <div class="flex items-center justify-between text-secondary mb-ax-sm">
          <span class="font-label-md text-[11px] uppercase tracking-wider">备份服务</span>
          <span class="h-2 w-2 rounded-full animate-pulse" :class="backupEnabled ? 'bg-primary' : 'bg-outline'"></span>
        </div>
        <div class="flex items-baseline gap-ax-xs">
          <span class="text-3xl font-bold font-headline-sm text-primary tracking-tight">{{ backupEnabled ? '已开启' : '已离线' }}</span>
        </div>
        <p class="font-body-sm text-[11px] text-on-surface-variant mt-2">每隔一小时归档持久化配置</p>
      </div>

      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md pro-shadow">
        <div class="flex items-center justify-between text-secondary mb-ax-sm">
          <span class="font-label-md text-[11px] uppercase tracking-wider">防御等级</span>
          <span class="material-symbols-outlined text-[16px]">shield</span>
        </div>
        <div class="flex items-baseline">
          <span class="text-[20px] font-bold font-label-md text-primary tracking-tight leading-none pt-1 truncate max-w-full block">{{ selectedClearanceKey }}</span>
        </div>
        <div class="flex items-center gap-ax-xs mt-4">
          <span v-for="i in 4" :key="i" class="h-1 w-6 rounded-full" :class="i <= selectedClearanceLevel ? 'bg-primary' : 'bg-surface-container'"></span>
        </div>
      </div>

      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md flex flex-col justify-between pro-shadow">
        <div>
          <div class="flex items-center justify-between text-secondary mb-ax-xs">
            <span class="font-label-md text-[11px] uppercase tracking-wider">接口实时延迟</span>
            <span class="font-label-md text-[10px] text-primary font-semibold border border-outline-variant px-1.5 py-0.5 rounded bg-surface-container">LIVE</span>
          </div>
          <div class="flex items-baseline gap-ax-xs">
            <span class="text-3xl font-bold font-headline-sm text-primary tracking-tight">{{ latestLatency }}</span>
            <span class="text-secondary font-label-md text-xs">ms</span>
          </div>
        </div>
        <div class="h-8 mt-2 w-full">
          <svg class="h-full w-full" viewBox="0 0 100 30" preserveAspectRatio="none">
            <path :d="sparklinePath" fill="none" stroke="#000" stroke-width="1.5" stroke-linecap="round" />
            <path :d="sparklineAreaPath" fill="rgba(0,0,0,0.05)" stroke="none" />
          </svg>
        </div>
      </div>
    </div>

    <div id="section-nav-cards" class="grid grid-cols-1 md:grid-cols-3 gap-gutter scroll-mt-4">
      <div
        v-for="card in navCards"
        :key="card.label"
        class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md flex items-center gap-ax-md cursor-pointer hover:border-outline hover:shadow-md transition-all duration-200 group"
      >
        <div :class="card.color" class="h-10 w-10 rounded-lg flex items-center justify-center shrink-0">
          <span class="material-symbols-outlined text-[20px]">{{ card.icon }}</span>
        </div>
        <div class="flex-1 min-w-0">
          <p class="font-body-sm text-[13px] font-semibold text-primary">{{ card.label }}</p>
          <p class="font-body-sm text-[11px] text-secondary mt-0.5">{{ card.desc }}</p>
        </div>
        <span class="material-symbols-outlined text-[16px] text-secondary group-hover:text-primary transition-colors">chevron_right</span>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-5 gap-gutter">
      <div class="md:col-span-3 space-y-gutter">
        <div id="section-settings-groups" class="scroll-mt-4 space-y-4">
        <div v-for="group in settingGroups" :key="group.title" class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow">
          <div class="px-ax-md py-ax-sm border-b border-outline-variant bg-surface-container-low">
            <span class="font-label-md text-[10px] text-secondary uppercase tracking-wider">{{ group.title }}</span>
          </div>
          <div class="divide-y divide-outline-variant/40">
            <div
              v-for="item in group.items"
              :key="item.label"
              class="flex items-center gap-ax-md px-ax-md py-3 cursor-pointer hover:bg-surface-container-low transition-colors group"
            >
              <span class="material-symbols-outlined text-[18px] text-secondary">{{ item.icon }}</span>
              <div class="flex-1 min-w-0">
                <p class="font-body-sm text-[13px] font-semibold text-primary">{{ item.label }}</p>
                <p class="font-body-sm text-[11px] text-secondary mt-0.5">{{ item.desc }}</p>
              </div>
              <span class="material-symbols-outlined text-[16px] text-secondary group-hover:text-primary transition-colors">chevron_right</span>
            </div>
          </div>
        </div>
        </div>

        <div id="section-faq" class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow scroll-mt-4">
          <div class="px-ax-md py-ax-sm border-b border-outline-variant bg-surface-container-low flex items-center gap-ax-sm">
            <span class="material-symbols-outlined text-[16px] text-secondary">quiz</span>
            <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">常见问题</span>
          </div>
          <div class="divide-y divide-outline-variant/40">
            <div v-for="faq in faqs" :key="faq.id">
              <button
                class="w-full flex items-center justify-between px-ax-md py-3 text-left hover:bg-surface-container-low transition-colors"
                @click="toggleFaq(faq.id)"
              >
                <span class="font-body-sm text-[13px] font-semibold text-primary">{{ faq.q }}</span>
                <span
                  class="material-symbols-outlined text-[16px] text-secondary transition-transform duration-200 shrink-0 ml-2"
                  :class="openFaq === faq.id ? 'rotate-180' : ''"
                >expand_more</span>
              </button>
              <div v-show="openFaq === faq.id" class="px-ax-md pb-3">
                <p class="font-body-sm text-[12px] text-on-surface-variant leading-relaxed">{{ faq.a }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="md:col-span-2">
        <div id="section-activities" class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden pro-shadow sticky top-0 scroll-mt-4">
          <div class="px-ax-md py-ax-sm border-b border-outline-variant bg-surface-container-low flex items-center justify-between">
            <div class="flex items-center gap-ax-sm">
              <span class="material-symbols-outlined text-[16px] text-secondary">history</span>
              <span class="font-label-md text-[11px] font-semibold text-primary uppercase tracking-wider">最近活动</span>
            </div>
            <span class="font-label-md text-[10px] text-secondary">过去 24 小时</span>
          </div>
          <div class="p-ax-md space-y-ax-md">
            <div v-for="act in activities" :key="act.id" class="flex gap-ax-sm">
              <div class="flex flex-col items-center gap-ax-xs">
                <div
                  class="h-2 w-2 rounded-full shrink-0 mt-1.5"
                  :class="{
                    'bg-emerald-500': act.type === 'success',
                    'bg-primary': act.type === 'info',
                    'bg-amber-500': act.type === 'warning',
                    'bg-red-500': act.type === 'error',
                  }"
                ></div>
                <div v-if="act.id !== activities[activities.length - 1]?.id" class="w-px flex-1 bg-outline-variant"></div>
              </div>
              <div class="pb-3">
                <div class="flex items-center gap-ax-xs mb-0.5">
                  <span class="font-label-md text-[10px] text-secondary">{{ act.time }}</span>
                  <span
                    class="font-label-md text-[9px] px-1 rounded uppercase font-semibold"
                    :class="{
                      'bg-emerald-50 text-emerald-700 border border-emerald-200': act.type === 'success',
                      'bg-primary/5 text-primary border border-primary/10': act.type === 'info',
                      'bg-amber-50 text-amber-700 border border-amber-200': act.type === 'warning',
                      'bg-red-50 text-red-700 border border-red-200': act.type === 'error',
                    }"
                  >{{ act.type }}</span>
                </div>
                <p class="font-body-sm text-[12px] font-semibold text-primary">{{ act.title }}</p>
                <p class="font-body-sm text-[11px] text-secondary mt-0.5 leading-relaxed">{{ act.desc }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
