<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { queueApi, parsersApi } from '@/api'
import { useNotify, useLinkify } from '@/components/ui'

const { triggerNotify } = useNotify()
const { linkify } = useLinkify()
const stats = ref<Record<string, number>>({})
const items = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const filterStatus = ref('')
const filterParser = ref('')
const filterSearch = ref('')
const refreshing = ref(false)

let _autoRefreshTimer: ReturnType<typeof setInterval> | null = null

const queueStatusOptions = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: 'pending' },
  { value: 'running', label: 'running' },
  { value: 'done', label: 'done' },
  { value: 'failed', label: 'failed' },
  { value: 'blocked', label: 'blocked' },
]

const statusColors: Record<string, string> = {
  pending: 'status-label',
  running: 'status-label-running',
  done: 'status-label-done',
  failed: 'status-label-failed',
  blocked: 'status-label-blocked',
}

// ── 新建任务弹窗 ──
const showCreateDialog = ref(false)
const createUrl = ref('')
const createParser = ref('')
const createFetchMode = ref<'browser' | 'http'>('browser')
const createMethod = ref<'GET' | 'POST' | 'PUT'>('GET')
const createHeaders = ref('')
const createCookies = ref('')
const createBodyType = ref<'none' | 'raw' | 'form-data' | 'json'>('none')
const createBodyContent = ref('')
const createSubmitting = ref(false)
const parsers = ref<Array<{ name: string }>>([])

const parserOptions = computed(() => {
  const opts = [{ value: '', label: '自动检测' }]
  parsers.value.forEach(p => opts.push({ value: p.name, label: p.name }))
  return opts
})

const showBodyConfig = computed(() => createFetchMode.value === 'http' && ['POST', 'PUT'].includes(createMethod.value))

const httpMethodOpts = [
  { value: 'GET', label: 'GET' },
  { value: 'POST', label: 'POST' },
  { value: 'PUT', label: 'PUT' },
]

const bodyTypeOpts = [
  { value: 'none', label: '无 Body' },
  { value: 'raw', label: 'Raw Text' },
  { value: 'form-data', label: 'Form Data' },
  { value: 'json', label: 'JSON' },
]

const openCreateDialog = async () => {
  createUrl.value = ''
  createParser.value = ''
  createFetchMode.value = 'browser'
  createMethod.value = 'GET'
  createHeaders.value = ''
  createCookies.value = ''
  createBodyType.value = 'none'
  createBodyContent.value = ''
  createSubmitting.value = false
  try { parsers.value = await parsersApi.list() } catch {}
  showCreateDialog.value = true
}

const submitCreate = async () => {
  if (!createUrl.value.trim()) return
  createSubmitting.value = true
  try {
    let requestConfig: Record<string, any> | undefined
    if (createFetchMode.value === 'http') {
      const cfg: Record<string, any> = {}
      cfg.method = createMethod.value
      if (createHeaders.value.trim()) {
        const h: Record<string, string> = {}
        createHeaders.value.split('\n').forEach(line => {
          const idx = line.indexOf(':')
          if (idx > 0) h[line.slice(0, idx).trim()] = line.slice(idx + 1).trim()
        })
        if (Object.keys(h).length) cfg.headers = h
      }
      if (createCookies.value.trim()) cfg.cookies = createCookies.value
      if (createBodyType.value !== 'none') {
        cfg.body_type = createBodyType.value
        cfg.body_content = createBodyContent.value
      }
      if (Object.keys(cfg).length > 1 || (Object.keys(cfg).length === 1 && cfg.method !== 'GET')) {
        requestConfig = cfg
      } else if (cfg.method === 'GET') {
        requestConfig = undefined
      } else {
        requestConfig = cfg
      }
    }
    
    const res: any = await queueApi.create({
      url: createUrl.value.trim(),
      parser_name: createParser.value || undefined,
      fetch_mode: createFetchMode.value,
      request_config: requestConfig,
    })
    triggerNotify(`任务已入队 (ID: ${res.queue_id}, Parser: ${res.parser})`, 'success')
    showCreateDialog.value = false
    fetchStats()
    fetchList()
  } catch (err: any) {
    triggerNotify(err?.response?.data?.error || '创建失败', 'error')
  } finally {
    createSubmitting.value = false
  }
}

const fetchStats = async () => {
  try { stats.value = await queueApi.stats() } catch {}
}

const fetchList = async (silent = false) => {
  if (!silent) refreshing.value = true
  try {
    const r: any = await queueApi.list({ page: page.value, size: size.value, status: filterStatus.value, parser: filterParser.value, search: filterSearch.value })
    items.value = r.items; total.value = r.total
  } catch {} finally {
    refreshing.value = false
  }
}

// 无感自动刷新：不显示 loading，后台静默更新
const autoRefresh = () => {
  fetchStats()
  fetchList(true)
}

const startAutoRefresh = () => {
  _autoRefreshTimer = setInterval(autoRefresh, 3000)
}

const stopAutoRefresh = () => {
  if (_autoRefreshTimer) { clearInterval(_autoRefreshTimer); _autoRefreshTimer = null }
}

const doRetry = async (id: number) => { try { await queueApi.retry(id); triggerNotify('已重新入队', 'success') } catch {} }
const doRetryBlocked = async () => { try { await queueApi.retryBlocked(); triggerNotify('所有 blocked 已重新入队', 'success'); fetchList(); fetchStats() } catch {} }

const handleFilterChange = () => { page.value = 1; fetchList() }
const handlePageChange = (p: number) => { page.value = p; fetchList() }
const handleSizeChange = (s: number) => { size.value = s; page.value = 1; fetchList() }

onMounted(() => { fetchStats(); fetchList(); startAutoRefresh() })
onUnmounted(() => { stopAutoRefresh() })
</script>

<template>
  <div class="space-y-ax-md">
    <!-- 状态分布 -->
    <div class="grid grid-cols-6 gap-ax-xs">
      <div v-for="s in ['pending','running','done','failed','blocked','skipped']" :key="s"
        class="bg-surface-container-lowest border border-outline-variant rounded-lg p-ax-sm">
        <div class="text-[10px] text-secondary uppercase">{{ s }}</div>
        <div class="text-lg font-medium text-primary">{{ stats[s] || 0 }}</div>
      </div>
    </div>

    <!-- 筛选条 -->
    <div class="bg-surface-container-lowest border border-outline-variant rounded-xl px-4 py-ax-sm flex items-center gap-ax-sm">
      <AxSelect v-model="filterStatus" size="lg" :options="queueStatusOptions" @update:model-value="handleFilterChange" />
      <AxInput v-model="filterSearch"  size="lg" placeholder="搜索 URL 或错误..." class="flex-1" @keyup.enter="handleFilterChange" />
      <AxButton variant="primary" size="lg" icon="add" @click="openCreateDialog">新建任务</AxButton>
      <AxButton variant="outline"  size="lg" @click="doRetryBlocked">重试 blocked</AxButton>
    </div>

    <!-- 表格 -->
    <div class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden relative">
      <!-- 无感刷新指示器 -->
      <div v-if="refreshing" class="refresh-bar" />
      <div class="overflow-x-auto">
      <table class="w-full text-xs">
        <thead class="bg-surface-container-low text-secondary text-[11px]">
          <tr>
            <th class="text-left px-4 py-2 font-medium">URL</th>
            <th class="text-left px-4 py-2 font-medium">Parser</th>
            <th class="text-left px-4 py-2 font-medium">状态</th>
            <th class="text-left px-4 py-2 font-medium">重试</th>
            <th class="text-left px-4 py-2 font-medium">换IP</th>
            <th class="text-left px-4 py-2 font-medium">错误</th>
            <th class="text-left px-4 py-2 font-medium w-24">操作</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-outline-variant">
          <tr v-for="q in items" :key="q.id" class="hover:bg-surface-container-low">
            <td class="px-4 py-2 font-mono truncate max-w-[240px]" v-html="linkify(q.url)" />
            <td class="px-4 py-2 text-secondary">{{ q.parser }}</td>
            <td class="px-4 py-2"><span class="pill" :class="statusColors[q.status] || ''">{{ q.status }}</span></td>
            <td class="px-4 py-2 text-secondary">{{ q.retry }}</td>
            <td class="px-4 py-2 text-secondary">{{ q.switch }}</td>
            <td class="px-4 py-2 text-secondary truncate max-w-[100px] text-[11px]">{{ q.error_msg || '-' }}</td>
            <td class="px-4 py-2">
              <AxTooltip content="重新入队">
                <AxButton variant="ghost" size="icon" icon="replay" @click="doRetry(q.id)" />
              </AxTooltip>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
      <!-- 分页 -->
      <div class="px-4 py-ax-sm border-t border-outline-variant">
        <AxPagination
          :page="page"
          :size="size"
          :total="total"
          :sizes="[20, 50, 100]"
          @update:page="handlePageChange"
          @update:size="handleSizeChange"
        />
      </div>
    </div>

    <!-- 新建任务弹窗 -->
    <AxDialog
      v-model="showCreateDialog"
      title="新建任务"
      icon="add_task"
      max-width="max-w-[640px]"
    >
      <div class="space-y-ax-md">
        <!-- URL -->
        <div>
          <label class="block font-label-md text-label-md font-semibold text-primary mb-ax-xs">目标 URL</label>
          <AxInput v-model="createUrl" size="lg" placeholder="https://cd.58.com/ershouche/" />
        </div>

        <!-- Parser -->
        <div>
          <label class="block font-label-md text-label-md font-semibold text-primary mb-ax-xs">Parser</label>
          <p class="text-[11px] text-secondary mb-ax-xs">留空自动匹配，选择后可精确触发对应的解析器。</p>
          <AxSelect v-model="createParser" size="lg" :options="parserOptions" placeholder="自动检测" />
        </div>

        <!-- 请求模式 -->
        <div>
          <label class="block font-label-md text-label-md font-semibold text-primary mb-ax-xs">请求模式</label>
          <p class="text-[11px] text-secondary mb-ax-xs">Browser 使用 Playwright 渲染，HTTP 直接请求（对 58 类站点推荐 HTTP）。</p>
          <div class="flex rounded-lg border border-outline-variant overflow-hidden w-fit">
            <button
              :class="[
                'px-3 py-1.5 text-[12px] font-medium transition-colors cursor-pointer',
                createFetchMode === 'http' ? 'bg-primary text-on-primary' : 'bg-surface-container-lowest text-secondary hover:bg-surface-container-low',
              ]"
              @click="createFetchMode = 'http'"
            >HTTP</button>
            <button
              :class="[
                'px-3 py-1.5 text-[12px] font-medium transition-colors cursor-pointer',
                createFetchMode === 'browser' ? 'bg-primary text-on-primary' : 'bg-surface-container-lowest text-secondary hover:bg-surface-container-low',
              ]"
              @click="createFetchMode = 'browser'"
            >Browser</button>
          </div>
        </div>

        <!-- HTTP 配置（仅 HTTP 模式显示） -->
        <template v-if="createFetchMode === 'http'">
          <div class="border-t border-outline-variant pt-ax-md space-y-ax-sm">
            <label class="font-label-md text-label-md font-semibold text-primary">HTTP 配置</label>

            <!-- Method -->
            <div>
              <span class="text-[12px] text-secondary mb-ax-xs block">Method</span>
              <div class="flex rounded-lg border border-outline-variant overflow-hidden w-fit">
                <button
                  v-for="opt in httpMethodOpts" :key="opt.value"
                  :class="[
                    'px-3 py-1 text-[11px] font-medium transition-colors cursor-pointer',
                    createMethod === opt.value ? 'bg-primary text-on-primary' : 'bg-surface-container-lowest text-secondary hover:bg-surface-container-low',
                  ]"
                  @click="createMethod = opt.value as any"
                >{{ opt.label }}</button>
              </div>
            </div>

            <!-- Headers -->
            <div>
              <div class="flex items-center justify-between mb-ax-xs">
                <span class="text-[12px] text-secondary">Headers</span>
                <span class="text-[10px] text-outline">每行一条，格式: key: value</span>
              </div>
              <AxInput v-model="createHeaders" size="lg" :multiline="true" :rows="2" resize="vertical" placeholder="User-Agent: Mozilla/5.0..." class="font-mono text-[12px]" />
            </div>

            <!-- Cookies -->
            <div>
              <div class="flex items-center justify-between mb-ax-xs">
                <span class="text-[12px] text-secondary">Cookies</span>
                <span class="text-[10px] text-outline">格式: k1=v1; k2=v2</span>
              </div>
              <AxInput v-model="createCookies" size="lg" placeholder="session=abc123" class="font-mono text-[12px]" />
            </div>

            <!-- Body（仅 POST/PUT 显示） -->
            <template v-if="showBodyConfig">
              <div class="border-t border-outline-variant/40 pt-ax-sm">
                <span class="text-[12px] text-secondary mb-ax-xs block">Body</span>
                <div class="flex rounded-lg border border-outline-variant overflow-hidden w-fit mb-ax-xs">
                  <button
                    v-for="opt in bodyTypeOpts" :key="opt.value"
                    :class="[
                      'px-2.5 py-1 text-[11px] font-medium transition-colors cursor-pointer',
                      createBodyType === opt.value ? 'bg-primary text-on-primary' : 'bg-surface-container-lowest text-secondary hover:bg-surface-container-low',
                    ]"
                    @click="createBodyType = opt.value as any"
                  >{{ opt.label }}</button>
                </div>
                <AxInput
                  v-if="createBodyType !== 'none'"
                  v-model="createBodyContent"
                  size="lg"
                  :multiline="true"
                  :rows="createBodyType === 'json' ? 4 : 2"
                  resize="vertical"
                  :placeholder="createBodyType === 'json' ? '{ &quot;key&quot;: &quot;value&quot; }' : createBodyType === 'form-data' ? 'key1=value1&amp;key2=value2' : '输入请求体内容...'"
                  class="font-mono text-[12px]"
                />
              </div>
            </template>
          </div>
        </template>
      </div>

      <template #footer>
        <AxButton size="lg" variant="outline" @click="showCreateDialog = false">取消</AxButton>
        <AxButton
          size="lg"
          variant="primary"
          icon="add"
          :loading="createSubmitting"
          :disabled="!createUrl.trim()"
          @click="submitCreate"
        >添加任务</AxButton>
      </template>
    </AxDialog>
  </div>
</template>

<style scoped>
.pill { padding: 1px 8px; border-radius: 999px; font-size: 10px; line-height: 1.6; }
.status-label { background: var(--color-surface-container, #f1efe8); color: var(--color-text-secondary, #5f5e5a); }
.status-label-running { background: #e6f1fb; color: #0c447c; }
.status-label-done { background: #e1f5ee; color: #085041; }
.status-label-failed { background: #faeeda; color: #633806; }
.status-label-blocked { background: #fcebeb; color: #791f1f; }

.refresh-bar {
  position: absolute;
  top: 0;
  left: 0;
  height: 2px;
  width: 100%;
  background: linear-gradient(90deg, transparent, var(--color-primary, #2864ff), transparent);
  animation: refresh-slide 2s ease-in-out infinite;
  z-index: 1;
}
@keyframes refresh-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}
</style>
