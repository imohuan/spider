<script setup lang="ts">
import { reactive } from 'vue'

// ── 侧边栏导航项 ──
interface NavSection {
  id: string
  label: string
  icon: string
}

const props = defineProps<{
  navItems: NavSection[]
  bottomNavItems?: NavSection[]
  title?: string
  subtitle?: string
}>()

const emit = defineEmits<{
  close: []
  cancel: []
  save: []
  navClick: [item: NavSection]
}>()

const activeTab = defineModel<string>('activeTab', { default: 'general' })
const isOpen = defineModel<boolean>({ default: false })

function open() { isOpen.value = true }
function close() { isOpen.value = false; emit('close') }
function handleCancel() { emit('cancel'); close() }
function handleSave() { emit('save'); close() }

defineExpose({ open, close })

// ── 配置数据 ──
const config = reactive({
  siteName: 'Axiom Console',
  maxUploadSize: 100,
  sessionTimeout: 30,
  retentionDays: 90,
  logLevel: 'info',
  enableCache: true,
  enableCompression: false,
  enableAutoBackup: true,
  backupTime: '03:00',
  backupPath: '/data/backups',
  threadCount: 4,
  cpuLimit: 70,
  hwAccel: true,
  gpuVendor: 'nvidia',
  authMethod: 'password',
  twoFactor: false,
  rateLimit: false,
  rateLimitCount: 100,
  auditLog: true,
  debugMode: false,
  profiler: false,
  logRetention: 30,
  maintenanceWindow: '02:00-04:00',
})
</script>

<template>
  <AxDialog v-model="isOpen" :title="title ?? '系统设置中心'" icon="settings" max-width="max-w-[820px]" body-class="!p-0" @close="close">
    <div class="flex h-[520px] overflow-hidden">
      <!-- ══════ 左侧导航栏 ══════ -->
      <aside
        class="w-48 shrink-0 border-r border-outline-variant bg-surface-container-lowest flex flex-col py-ax-sm px-ax-sm select-none">
        <div class="mb-ax-md px-2">
          <h2 class="font-headline-sm text-headline-sm text-primary font-bold">
            {{ title ?? 'Configuration' }}
          </h2>
          <p class="font-body-sm text-[10px] text-secondary mt-0.5">
            {{ subtitle ?? '管理系统运行参数' }}
          </p>
        </div>

        <nav class="flex-1 space-y-0.5">
          <button v-for="item in navItems" :key="item.id" :class="[
            activeTab === item.id
              ? 'bg-secondary-container text-on-secondary-container font-medium scale-[0.98]'
              : 'text-secondary hover:bg-surface-container-low',
          ]"
            class="flex items-center gap-ax-sm rounded-xl py-1.5 px-2 font-label-md text-label-md transition-all duration-100 cursor-pointer w-full text-left"
            @click="activeTab = item.id">
            <span class="material-symbols-outlined text-[16px]"
              :style="{ fontVariationSettings: activeTab === item.id ? '\'FILL\' 1' : '\'FILL\' 0' }">{{ item.icon
              }}</span>
            <span>{{ item.label }}</span>
          </button>
        </nav>

        <div v-if="bottomNavItems?.length" class="border-t border-outline-variant pt-ax-sm space-y-0.5">
          <button v-for="item in bottomNavItems" :key="item.id"
            class="flex items-center gap-ax-sm rounded-xl py-1.5 px-2 font-label-md text-label-md text-secondary hover:bg-surface-container-low transition-colors cursor-pointer w-full text-left"
            @click="emit('navClick', item)">
            <span class="material-symbols-outlined text-[16px]">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </button>
        </div>
      </aside>

      <!-- ══════ 右侧主内容区 ══════ -->
      <div class="flex-1 flex flex-col min-w-0">
        <!-- ══════ 内容区（按 tab 切换） ══════ -->
        <div class="flex-1 overflow-y-auto p-margin space-y-ax-md scrollbar-hide">

          <!-- ──── 通用设置 ──── -->
          <template v-if="activeTab === 'general'">
            <div class="border-b border-outline-variant pb-ax-sm mb-ax-sm">
              <h3 class="font-headline-sm text-headline-sm text-primary">通用设置</h3>
              <p class="font-body-sm text-body-sm text-on-surface-variant mt-1">配置控制台基本运行参数与展示选项。</p>
            </div>
            <section
              class="bg-white border border-outline-variant rounded-lg p-ax-md divide-y divide-outline-variant/40">
              <!-- 站点名称 (Input) -->
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">站点名称</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">显示在顶栏和浏览器标签页中的控制台名称</p>
                </div>
                <AxInput v-model="config.siteName"  size="lg" class="!w-44 shrink-0" />
              </div>
              <!-- 上传限制 (Slider) -->
              <div class="py-3">
                <div class="flex items-center justify-between">
                  <p class="font-label-md text-label-md font-semibold text-primary">文件上传大小限制</p>
                  <span class="font-label-md text-[12px] font-bold text-primary tabular-nums">{{ config.maxUploadSize }}
                    MB</span>
                </div>
                <p class="font-body-sm text-[11px] text-secondary mt-0.5 mb-2">单个文件上传的最大容量限制</p>
                <AxSlider v-model="config.maxUploadSize" :min="1" :max="500" :step="1" show-labels show-value
                  label-left="1 MB" label-right="500 MB" :value-label="config.maxUploadSize + ' MB'" />
              </div>
              <!-- 会话超时 (Slider) -->
              <div class="py-3">
                <div class="flex items-center justify-between">
                  <p class="font-label-md text-label-md font-semibold text-primary">会话超时时间</p>
                  <span class="font-label-md text-[12px] font-bold text-primary tabular-nums">{{ config.sessionTimeout
                  }} 分钟</span>
                </div>
                <p class="font-body-sm text-[11px] text-secondary mt-0.5 mb-2">用户无操作后自动登出的等待时长</p>
                <AxSlider v-model="config.sessionTimeout" :min="5" :max="240" :step="5" show-labels show-value
                  label-left="5 分钟" label-right="240 分钟" :value-label="config.sessionTimeout + ' 分钟'" />
              </div>
              <!-- 保留天数 (Select) -->
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">日志保留天数</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">系统操作日志自动清理前的保留周期</p>
                </div>
                <div class="max-w-[160px] ml-auto">
                  <AxSelect v-model="config.retentionDays" size="lg" dropdownWidth="120px" placement="bottom-end"
                    :options="[
                      { value: 7, label: '7 天' },
                      { value: 30, label: '30 天' },
                      { value: 90, label: '90 天' },
                      { value: 180, label: '180 天' },
                      { value: 365, label: '365 天' },
                    ]" />
                </div>
              </div>
            </section>
          </template>

          <!-- ──── 性能与算力 ──── -->
          <template v-if="activeTab === 'performance'">
            <div class="border-b border-outline-variant pb-ax-sm mb-ax-sm">
              <h3 class="font-headline-sm text-headline-sm text-primary">性能与算力</h3>
              <p class="font-body-sm text-body-sm text-on-surface-variant mt-1">调整系统资源分配与计算性能参数。</p>
            </div>
            <section
              class="bg-white border border-outline-variant rounded-lg p-ax-md divide-y divide-outline-variant/40">
              <!-- 线程数 (Select) -->
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">工作线程数</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">并行处理任务的线程池大小，影响吞吐与延迟</p>
                </div>
                <div class="max-w-[160px] ml-auto">
                  <AxSelect v-model="config.threadCount" size="lg" dropdownWidth="120px" placement="bottom-end"
                    :options="[
                      { value: 1, label: '1 线程' },
                      { value: 2, label: '2 线程' },
                      { value: 4, label: '4 线程' },
                      { value: 8, label: '8 线程' },
                      { value: 16, label: '16 线程' },
                    ]" />
                </div>
              </div>
              <!-- CPU 限制 (Slider) -->
              <div class="py-3">
                <div class="flex items-center justify-between">
                  <p class="font-label-md text-label-md font-semibold text-primary">CPU 使用上限</p>
                  <span class="font-label-md text-[12px] font-bold text-primary tabular-nums">{{ config.cpuLimit
                  }}%</span>
                </div>
                <p class="font-body-sm text-[11px] text-secondary mt-0.5 mb-2">限制系统最大 CPU 占用比例，防止过载</p>
                <AxSlider v-model="config.cpuLimit" :min="10" :max="100" :step="5" show-labels show-value
                  label-left="低负载" label-right="满负载" :value-label="config.cpuLimit + '%'" />
              </div>
              <!-- 硬件加速 (Switch) -->
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">硬件加速</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">启用 GPU 加速提升渲染与计算性能</p>
                </div>
                <button role="switch" :aria-checked="config.hwAccel"
                  :class="config.hwAccel ? 'bg-primary' : 'bg-outline'"
                  class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200"
                  @click="config.hwAccel = !config.hwAccel">
                  <span :class="config.hwAccel ? 'translate-x-4' : 'translate-x-0'"
                    class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out" />
                </button>
              </div>
              <!-- GPU 厂商 (Select) -->
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">首选 GPU 厂商</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">硬件加速时优先使用的显卡品牌</p>
                </div>
                <div class="max-w-[160px] ml-auto">
                  <AxSelect v-model="config.gpuVendor" size="lg" dropdownWidth="120px" placement="bottom-end" :options="[
                    { value: 'nvidia', label: 'NVIDIA' },
                    { value: 'amd', label: 'AMD' },
                    { value: 'intel', label: 'Intel' },
                    { value: 'auto', label: '自动检测' },
                  ]" />
                </div>
              </div>
            </section>
          </template>

          <!-- ──── 安全与权限 ──── -->
          <template v-if="activeTab === 'security'">
            <div class="border-b border-outline-variant pb-ax-sm mb-ax-sm">
              <h3 class="font-headline-sm text-headline-sm text-primary">安全与权限</h3>
              <p class="font-body-sm text-body-sm text-on-surface-variant mt-1">配置身份验证、权限控制与审计策略。</p>
            </div>
            <section
              class="bg-white border border-outline-variant rounded-lg p-ax-md divide-y divide-outline-variant/40">
              <!-- 认证方式 (Select) -->
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">认证方式</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">用户登录时使用的身份验证协议</p>
                </div>
                <div class="max-w-[160px] ml-auto">
                  <AxSelect v-model="config.authMethod" size="lg" dropdownWidth="120px" placement="bottom-end" :options="[
                    { value: 'password', label: '密码登录' },
                    { value: 'sso', label: 'SSO 单点登录' },
                    { value: 'ldap', label: 'LDAP' },
                    { value: 'oauth', label: 'OAuth 2.0' },
                  ]" />
                </div>
              </div>
              <!-- 双因素认证 (Switch) -->
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">双因素认证</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">登录时强制要求手机验证码或硬件密钥</p>
                </div>
                <button role="switch" :aria-checked="config.twoFactor"
                  :class="config.twoFactor ? 'bg-primary' : 'bg-outline'"
                  class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200"
                  @click="config.twoFactor = !config.twoFactor">
                  <span :class="config.twoFactor ? 'translate-x-4' : 'translate-x-0'"
                    class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out" />
                </button>
              </div>
              <!-- 审计日志 (Switch + 复选框级的 Select 联动) -->
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">操作审计日志</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">记录所有用户操作，用于安全审查与合规</p>
                </div>
                <button role="switch" :aria-checked="config.auditLog"
                  :class="config.auditLog ? 'bg-primary' : 'bg-outline'"
                  class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200"
                  @click="config.auditLog = !config.auditLog">
                  <span :class="config.auditLog ? 'translate-x-4' : 'translate-x-0'"
                    class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out" />
                </button>
              </div>
              <!-- 速率限制 (Switch + Slider) -->
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">请求速率限制</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">限制 API 调用频率防止滥用与 DDoS 攻击</p>
                </div>
                <button role="switch" :aria-checked="config.rateLimit"
                  :class="config.rateLimit ? 'bg-primary' : 'bg-outline'"
                  class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200"
                  @click="config.rateLimit = !config.rateLimit">
                  <span :class="config.rateLimit ? 'translate-x-4' : 'translate-x-0'"
                    class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out" />
                </button>
              </div>
              <!-- 开启速率限制后显示 Slider -->
              <div v-show="config.rateLimit"
                class="py-3 pl-4 border-l-2 border-outline-variant bg-surface-container-lowest rounded-r-md">
                <div class="flex items-center justify-between">
                  <p class="font-label-md text-label-md font-semibold text-primary">每分钟请求上限</p>
                  <span class="font-label-md text-[12px] font-bold text-primary tabular-nums">{{ config.rateLimitCount
                  }} 次</span>
                </div>
                <p class="font-body-sm text-[11px] text-secondary mt-0.5 mb-2">超出限制的请求将被自动拒绝</p>
                <AxSlider v-model="config.rateLimitCount" :min="10" :max="1000" :step="10" show-labels show-value
                  label-left="10" label-right="1000" :value-label="config.rateLimitCount + ' 次/分'" />
              </div>
            </section>
          </template>

          <!-- ──── 通知与告警 ──── -->
          <template v-if="activeTab === 'notifications'">
            <div class="border-b border-outline-variant pb-ax-sm mb-ax-sm">
              <h3 class="font-headline-sm text-headline-sm text-primary">通知与告警</h3>
              <p class="font-body-sm text-body-sm text-on-surface-variant mt-1">管理事件通知类别与推送偏好。</p>
            </div>
            <section
              class="bg-white border border-outline-variant rounded-lg p-ax-md divide-y divide-outline-variant/40">
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">CPU 使用率告警</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">当 CPU 使用率超过阈值时推送通知</p>
                </div>
                <button role="switch" :aria-checked="true"
                  class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200 bg-primary">
                  <span
                    class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out translate-x-4" />
                </button>
              </div>
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">磁盘空间告警</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">存储空间不足时向管理员发送紧急通知</p>
                </div>
                <button role="switch" :aria-checked="true"
                  class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200 bg-primary">
                  <span
                    class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out translate-x-4" />
                </button>
              </div>
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">备份完成通知</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">自动备份任务完成后推送确认消息</p>
                </div>
                <button role="switch" :aria-checked="false"
                  class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200 bg-outline">
                  <span
                    class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out translate-x-0" />
                </button>
              </div>
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">异地登录提醒</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">检测到异地或异常设备登录时发出警告</p>
                </div>
                <button role="switch" :aria-checked="true"
                  class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200 bg-primary">
                  <span
                    class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out translate-x-4" />
                </button>
              </div>
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">系统更新提醒</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">有新版本或安全补丁时在控制台展示通知</p>
                </div>
                <button role="switch" :aria-checked="false"
                  class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200 bg-outline">
                  <span
                    class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out translate-x-0" />
                </button>
              </div>
            </section>
          </template>

          <!-- ──── 高级配置 ──── -->
          <template v-if="activeTab === 'advanced'">
            <div class="border-b border-outline-variant pb-ax-sm mb-ax-sm">
              <h3 class="font-headline-sm text-headline-sm text-primary">高级配置</h3>
              <p class="font-body-sm text-body-sm text-on-surface-variant mt-1">开发者工具、备份与系统级调试选项。</p>
            </div>
            <section
              class="bg-white border border-outline-variant rounded-lg p-ax-md divide-y divide-outline-variant/40">
              <!-- 自动备份 (Switch) -->
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">自动备份</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">按定时计划自动备份数据库和配置文件</p>
                </div>
                <button role="switch" :aria-checked="config.enableAutoBackup"
                  :class="config.enableAutoBackup ? 'bg-primary' : 'bg-outline'"
                  class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200"
                  @click="config.enableAutoBackup = !config.enableAutoBackup">
                  <span :class="config.enableAutoBackup ? 'translate-x-4' : 'translate-x-0'"
                    class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out" />
                </button>
              </div>
              <!-- 备份路径 (Input) -->
              <div class="py-3">
                <label class="font-label-md text-label-md font-semibold text-primary block">备份存储路径</label>
                <p class="font-body-sm text-[11px] text-secondary mt-0.5 mb-2">自动备份文件的目标目录</p>
                <AxInput v-model="config.backupPath"  size="lg">
                  <template #prefix><span class="material-symbols-outlined text-[16px]">folder</span></template>
                </AxInput>
              </div>
              <!-- 备份时间 (Input + Select 组合) -->
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">每日备份时间</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">自动备份任务的执行时间点 (HH:MM)</p>
                </div>
                <AxInput v-model="config.backupTime"  size="lg" class="!w-32 shrink-0" />
              </div>
              <!-- 日志级别 (Select) -->
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">日志输出级别</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">控制运行时日志的详细程度</p>
                </div>
                <div class="max-w-[160px] ml-auto">
                  <AxSelect v-model="config.logLevel" size="lg" dropdownWidth="120px" placement="bottom-end" :options="[
                    { value: 'error', label: '仅错误' },
                    { value: 'warn', label: '警告及以上' },
                    { value: 'info', label: '信息及以上' },
                    { value: 'debug', label: '调试模式' },
                  ]" />
                </div>
              </div>
              <!-- 调试模式 (Switch) -->
              <div class="flex items-center gap-ax-md py-3">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">开发者调试模式</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">输出详细堆栈信息和性能分析报告</p>
                </div>
                <button role="switch" :aria-checked="config.debugMode"
                  :class="config.debugMode ? 'bg-primary' : 'bg-outline'"
                  class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors duration-200"
                  @click="config.debugMode = !config.debugMode">
                  <span :class="config.debugMode ? 'translate-x-4' : 'translate-x-0'"
                    class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ease-in-out" />
                </button>
              </div>
            </section>
          </template>

        </div>
      </div>
    </div>

    <template #footer>
      <AxButton size="lg" variant="outline" @click="handleCancel">取消</AxButton>
      <AxButton size="lg" icon="save" @click="handleSave">保存更改</AxButton>
    </template>
  </AxDialog>
</template>
