<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { configApi } from '@/api'
import { useTestHistory } from '@/composables/useTestHistory'

// ── Model ──
const isOpen = defineModel<boolean>({ default: false })
const props = defineProps<{ parserName?: string }>()
const activeTab = ref<'test' | 'history'>('test')

// ── 历史记录 ──
const { items: historyItems, add: addHistory, remove: removeHistory, clearAll: clearHistory, getById } = useTestHistory()

// ── 测试配置 ──
const testUrl = ref('')
const showWindow = ref(false)
const keepOpen = ref(false)
const testRunning = ref(false)
const testResult = ref<any>(null)

// ── Debug 会话 ──
const debugPages = ref<any[]>([])
let pollTimer: ReturnType<typeof setInterval> | null = null

async function pollDebugPages() {
  try {
    const pages = await configApi.getDebugPages()
    debugPages.value = pages || []
  } catch {
    debugPages.value = []
  }
}

async function closeDebugPage(sessionId: string) {
  try {
    await configApi.closeDebugPage(sessionId)
    debugPages.value = debugPages.value.filter(p => p.session_id !== sessionId)
  } catch {
    // ignore
  }
}

onMounted(() => {
  pollDebugPages()
  pollTimer = setInterval(pollDebugPages, 5000)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

// ── 执行测试 ──
async function runTest() {
  if (!testUrl.value.trim()) return
  testRunning.value = true
  testResult.value = null

  const payload: any = {
    url: testUrl.value.trim(),
    show_window: showWindow.value,
  }
  if (keepOpen.value) payload.keep_open_seconds = 3600
  if (props.parserName) payload.parser = props.parserName

  try {
    const result = await configApi.getUrl(payload)
    testResult.value = result

    addHistory({
      url: testUrl.value.trim(),
      parser: props.parserName || undefined,
    })

    // 立即刷新 debug pages
    if (result.debug_session_id) {
      pollDebugPages()
    }
  } catch (err: any) {
    testResult.value = {
      ok: false,
      error: err?.message || err?.toString?.() || 'Unknown error',
      error_type: 'NetworkError',
    }
  } finally {
    testRunning.value = false
  }
}

// ── 恢复历史记录 ──
function restoreFromHistory(id: string) {
  const item = getById(id)
  if (!item) return
  testUrl.value = item.url
}

// ── 格式化时间 ──
function formatTime(ts: number): string {
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// ── Material Symbols 填充样式 ──
function iconFillStyle(tab: 'test' | 'history'): Record<string, string> {
  const fill = activeTab.value === tab ? '1' : '0'
  return { fontVariationSettings: `'FILL' ${fill}` }
}

function handleCancel() { isOpen.value = false }

// ── 解析结果表格列 ──
const resultColumns = computed(() => {
  if (!testResult.value?.ok || !testResult.value.data?.length) return []
  return Object.keys(testResult.value.data[0]).slice(0, 15) // 最多 15 列
})
</script>

<template>
  <AxDialog
    v-model="isOpen"
    :title="props.parserName ? `测试 URL — ${props.parserName}` : '测试 URL'"
    icon="science"
    max-width="max-w-[960px]"
    body-class="!p-0"
    @close="handleCancel"
  >
    <div class="flex h-[560px] overflow-hidden">
      <!-- ══════ 左侧导航 ══════ -->
      <aside class="w-44 shrink-0 border-r border-outline-variant bg-surface-container-lowest flex flex-col py-ax-sm px-ax-sm select-none">
        <div class="mb-ax-md px-2">
          <h2 class="font-headline-sm text-headline-sm text-primary font-bold">测试</h2>
          <p class="font-body-sm text-[10px] text-secondary mt-0.5">URL 请求调试</p>
        </div>

        <nav class="flex-1 space-y-0.5">
          <button
            :class="[
              'flex items-center gap-ax-sm rounded-xl py-1.5 px-2 font-label-md text-label-md transition-all duration-100 cursor-pointer w-full text-left',
              activeTab === 'test'
                ? 'bg-secondary-container text-on-secondary-container font-medium scale-[0.98]'
                : 'text-secondary hover:bg-surface-container-low',
            ]"
            @click="activeTab = 'test'"
          >
            <span class="material-symbols-outlined text-[16px]" :style="iconFillStyle('test')">science</span>
            <span>测试 URL</span>
          </button>

          <button
            :class="[
              'flex items-center gap-ax-sm rounded-xl py-1.5 px-2 font-label-md text-label-md transition-all duration-100 cursor-pointer w-full text-left',
              activeTab === 'history'
                ? 'bg-secondary-container text-on-secondary-container font-medium scale-[0.98]'
                : 'text-secondary hover:bg-surface-container-low',
            ]"
            @click="activeTab = 'history'"
          >
            <span class="material-symbols-outlined text-[16px]" :style="iconFillStyle('history')">history</span>
            <span>请求历史</span>
            <span v-if="historyItems.length" class="ml-auto bg-primary text-on-primary text-[10px] rounded-full w-5 h-5 flex items-center justify-center font-bold">
              {{ historyItems.length > 99 ? '99+' : historyItems.length }}
            </span>
          </button>
        </nav>

        <div v-if="props.parserName" class="border-t border-outline-variant pt-ax-sm">
          <div class="px-2 text-[10px] text-outline font-mono truncate">{{ props.parserName }}</div>
        </div>
      </aside>

      <!-- ══════ 右侧内容 ══════ -->
      <div class="flex-1 flex flex-col min-w-0">
        <div class="flex-1 overflow-y-auto p-margin space-y-ax-sm">

          <!-- ──── Test URL Tab ──── -->
          <template v-if="activeTab === 'test'">
            <div class="border-b border-outline-variant pb-ax-sm mb-ax-sm">
              <h3 class="font-headline-sm text-headline-sm text-primary">测试 URL</h3>
              <p class="font-body-sm text-body-sm text-on-surface-variant mt-1">
                {{ props.parserName ? `使用 ${props.parserName} 解析目标 URL` : '自动匹配 Parser 解析目标 URL' }}
              </p>
            </div>

            <!-- URL 输入 -->
            <section class="bg-white border border-outline-variant rounded-lg p-ax-md space-y-ax-sm">
              <div class="flex items-center gap-ax-sm mb-ax-xs">
                <span class="material-symbols-outlined text-[16px] text-primary">link</span>
                <span class="font-label-md text-label-md font-semibold text-primary">请求 URL</span>
              </div>
              <div class="flex items-center gap-ax-md">
                <div class="flex-1 flex gap-ax-xs">
                  <AxInput v-model="testUrl" size="lg" placeholder="https://cd.58.com/shangpu/xxx.shtml" class="flex-1" />
                  <AxButton
                    variant="primary"
                    size="lg"
                    icon="play_arrow"
                    :loading="testRunning"
                    :disabled="!testUrl.trim()"
                    @click="runTest"
                  >发送请求</AxButton>
                </div>
              </div>
              <!-- 显示浏览器窗口开关 -->
              <label class="flex items-center gap-ax-xs cursor-pointer select-none text-[12px] text-secondary hover:text-primary transition-colors">
                <input type="checkbox" v-model="showWindow" class="w-4 h-4 rounded border-outline-variant text-primary cursor-pointer" />
                <span class="material-symbols-outlined text-[16px]">visibility</span>
                <span>显示浏览器窗口</span>
                <span class="text-[10px] text-outline">(调试用，仅 browser 模式生效)</span>
              </label>
              <!-- 保持浏览器打开开关 -->
              <label class="flex items-center gap-ax-xs cursor-pointer select-none text-[12px] text-secondary hover:text-primary transition-colors">
                <input type="checkbox" v-model="keepOpen" class="w-4 h-4 rounded border-outline-variant text-primary cursor-pointer" />
                <span class="material-symbols-outlined text-[16px]">schedule</span>
                <span>保持浏览器打开</span>
                <span class="text-[10px] text-outline">(1 小时后自动关闭，可手动关闭)</span>
              </label>
            </section>

            <!-- Debug 会话列表 -->
            <section v-if="debugPages.length" class="bg-amber-50 border border-amber-300 rounded-lg p-ax-md space-y-ax-xs">
              <div class="flex items-center justify-between mb-ax-xs">
                <div class="flex items-center gap-ax-xs">
                  <span class="material-symbols-outlined text-[16px] text-amber-700">visibility</span>
                  <span class="font-label-md text-label-md font-semibold text-amber-800">保持打开的浏览器会话</span>
                </div>
                <div class="flex items-center gap-ax-xs">
                  <AxButton
                    v-for="page in debugPages"
                    :key="page.session_id"
                    variant="outline"
                    size="sm"
                    icon="close"
                    @click="closeDebugPage(page.session_id)"
                  >关闭 <span class="text-[10px] text-outline ml-ax-xs">{{ page.session_id.slice(0, 6) }}</span></AxButton>
                </div>
              </div>
              <div
                v-for="page in debugPages"
                :key="page.session_id"
                class="bg-white border border-amber-200 rounded-md p-ax-xs"
              >
                <div class="flex items-center gap-ax-xs">
                  <span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 font-bold font-mono">{{ page.parser }}</span>
                  <span class="font-mono text-[11px] text-primary truncate">{{ page.url }}</span>
                </div>
                <div class="text-[10px] text-secondary mt-0.5">
                  剩余 {{ Math.ceil(page.remaining_seconds / 60) }} 分钟
                </div>
              </div>
            </section>

            <!-- 模式信息（后端返回后展示） -->
            <section v-if="testResult?.ok && testResult.fetch_mode" class="bg-white border border-outline-variant rounded-lg p-ax-md">
              <div class="flex items-center gap-ax-md flex-wrap text-[12px]">
                <div class="flex items-center gap-ax-xs">
                  <span class="text-secondary">Parser:</span>
                  <span class="text-primary font-bold font-mono text-[11px]">{{ testResult.parser }}</span>
                </div>
                <div class="flex items-center gap-ax-xs">
                  <span class="text-secondary">Fetch:</span>
                  <span :class="testResult.fetch_mode === 'browser' ? 'text-purple-600 font-bold' : 'text-blue-600 font-bold'">{{ testResult.fetch_mode.toUpperCase() }}</span>
                </div>
                <div>
                  <span class="text-secondary">总耗时: </span>
                  <span class="text-primary font-bold">{{ testResult.duration_ms }}ms</span>
                  <span class="text-outline text-[10px] ml-ax-xs">(fetch {{ testResult.fetch_duration_ms }}ms + parse {{ testResult.parse_duration_ms }}ms)</span>
                </div>
                <div>
                  <span class="text-secondary">数据量: </span>
                  <span class="text-primary font-bold">{{ testResult.data_count }} 条</span>
                </div>
              </div>
            </section>

            <!-- 解析结果表格 -->
            <section v-if="testResult?.ok && testResult.data?.length" class="bg-white border border-outline-variant rounded-lg overflow-hidden">
              <div class="px-ax-md py-ax-sm border-b border-outline-variant bg-surface-container-lowest">
                <span class="font-label-md text-label-md font-semibold text-primary">解析结果</span>
              </div>
              <div class="overflow-x-auto">
                <table class="w-full text-[11px]">
                  <thead>
                    <tr class="bg-surface-container-lowest border-b border-outline-variant">
                      <th
                        v-for="col in resultColumns"
                        :key="col"
                        class="px-ax-sm py-ax-xs text-left font-semibold text-secondary whitespace-nowrap"
                      >{{ col }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, ri) in testResult.data" :key="ri" class="border-b border-outline-variant/40 hover:bg-surface-container-low/50">
                      <td
                        v-for="col in resultColumns"
                        :key="col"
                        class="px-ax-sm py-ax-xs text-primary max-w-[200px] truncate"
                        :title="row[col]"
                      >{{ row[col] ?? '-' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <!-- 错误展示 -->
            <section v-if="testResult && !testResult.ok" class="bg-white border border-error-container rounded-lg p-ax-md">
              <div class="flex items-center gap-ax-sm mb-ax-sm">
                <span class="material-symbols-outlined text-[16px] text-error">error</span>
                <span class="font-label-md text-label-md font-semibold text-error">请求失败</span>
              </div>
              <div class="bg-error-container text-on-error-container rounded p-ax-sm text-[12px]">
                <span v-if="testResult.error_type" class="font-bold">{{ testResult.error_type }}</span>
                <span v-if="testResult.error_type && testResult.error">: </span>
                <span>{{ testResult.error }}</span>
              </div>
            </section>

            <!-- Raw HTML 预览（折叠） -->
            <details v-if="testResult?.ok && testResult.raw_preview" class="bg-white border border-outline-variant rounded-lg">
              <summary class="px-ax-md py-ax-sm cursor-pointer hover:bg-surface-container-lowest transition-colors select-none">
                <span class="font-label-md text-label-md text-secondary">原始 HTML 预览 ({{ testResult.raw_preview.length }} 字符)</span>
              </summary>
              <pre class="px-ax-md pb-ax-sm font-mono text-[11px] text-primary leading-relaxed max-h-60 overflow-y-auto whitespace-pre-wrap break-all">{{ testResult.raw_preview }}</pre>
            </details>
          </template>

          <!-- ──── History Tab ──── -->
          <template v-if="activeTab === 'history'">
            <div class="flex items-center justify-between border-b border-outline-variant pb-ax-sm mb-ax-sm">
              <div>
                <h3 class="font-headline-sm text-headline-sm text-primary">请求历史</h3>
                <p class="font-body-sm text-body-sm text-on-surface-variant mt-1">本地存储的测试记录，点击恢复 URL。</p>
              </div>
              <AxButton
                v-if="historyItems.length"
                variant="ghost"
                size="icon-lg"
                icon="delete_sweep"
                @click="clearHistory()"
              />
            </div>

            <div v-if="historyItems.length === 0" class="text-center py-ax-xl text-secondary text-sm">
              <span class="material-symbols-outlined text-[48px] text-outline block mb-ax-sm">history</span>
              暂无请求历史
            </div>

            <div v-else class="space-y-ax-xs">
              <div
                v-for="item in historyItems" :key="item.id"
                class="bg-white border border-outline-variant rounded-lg p-ax-sm hover:border-primary/40 transition-colors group"
              >
                <div class="flex items-center gap-ax-sm">
                  <div class="flex-1 min-w-0 cursor-pointer py-0.5" @click="restoreFromHistory(item.id); activeTab = 'test'">
                    <div class="flex items-center gap-ax-xs">
                      <span v-if="item.parser" class="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary font-bold font-mono">{{ item.parser }}</span>
                      <span class="font-mono text-[11px] text-primary truncate">{{ item.url }}</span>
                    </div>
                  </div>
                  <div class="flex items-center gap-ax-xs shrink-0 text-[10px] text-outline">
                    {{ formatTime(item.createdAt) }}
                    <AxButton
                      variant="ghost"
                      size="icon"
                      icon="edit"
                      @click="restoreFromHistory(item.id); activeTab = 'test'"
                    />
                    <AxButton
                      variant="ghost"
                      size="icon"
                      icon="delete"
                      @click="removeHistory(item.id)"
                    />
                  </div>
                </div>
              </div>
            </div>
          </template>

        </div>
      </div>
    </div>

    <template #footer>
      <AxButton size="lg" variant="outline" @click="handleCancel">关闭</AxButton>
    </template>
  </AxDialog>
</template>
