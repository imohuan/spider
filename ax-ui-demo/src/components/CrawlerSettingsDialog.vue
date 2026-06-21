<script setup lang="ts">
import { ref, computed } from 'vue'
import { configApi } from '@/api'
import { useTestHistory } from '@/composables/useTestHistory'

// ── Model ──
const isOpen = defineModel<boolean>({ default: false })
const props = defineProps<{ parserName?: string }>()
const activeTab = ref<'test' | 'history'>('test')

// ── 历史记录 ──
const { items: historyItems, add: addHistory, remove: removeHistory, clearAll: clearHistory, getById } = useTestHistory()

// ── 测试配置 ──
const testMode = ref<'browser' | 'http'>('http')
const testUrl = ref('')
const testMethod = ref<'GET' | 'POST' | 'PUT'>('GET')
const testHeaders = ref('')
const testCookies = ref('')
const testBodyType = ref<'none' | 'raw' | 'form-data' | 'json'>('none')
const testBodyContent = ref('')
const testRunning = ref(false)
const testResult = ref<any>(null)

const showBodyConfig = computed(() => testMode.value === 'http' && ['POST', 'PUT'].includes(testMethod.value))

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

// ── 执行测试 ──
async function runTest() {
  if (!testUrl.value.trim()) return
  testRunning.value = true
  testResult.value = null

  // 构建请求
  const payload: any = {
    url: testUrl.value.trim(),
    mode: testMode.value,
  }

  if (testMode.value === 'http') {
    payload.method = testMethod.value
    if (testHeaders.value.trim()) {
      try {
        payload.headers = JSON.parse(testHeaders.value)
      } catch {
        // 尝试解析 key: value 格式
        const h: Record<string, string> = {}
        testHeaders.value.split('\n').forEach(line => {
          const idx = line.indexOf(':')
          if (idx > 0) h[line.slice(0, idx).trim()] = line.slice(idx + 1).trim()
        })
        payload.headers = Object.keys(h).length ? h : undefined
      }
    }
    if (testCookies.value.trim()) payload.cookies = testCookies.value
    if (testBodyType.value !== 'none') {
      payload.body_type = testBodyType.value
      payload.body_content = testBodyContent.value
    }
  }

  try {
    const result = await configApi.testUrl(payload)
    testResult.value = result

    // 保存历史记录
    addHistory({
      url: testUrl.value.trim(),
      mode: testMode.value,
      method: payload.method || 'GET',
      headers: testHeaders.value,
      cookies: testCookies.value,
      bodyType: testBodyType.value,
      bodyContent: testBodyContent.value,
    })
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
  testMode.value = item.mode
  testMethod.value = item.method
  testHeaders.value = item.headers
  testCookies.value = item.cookies
  testBodyType.value = item.bodyType
  testBodyContent.value = item.bodyContent
}

// ── 状态颜色 ──
function statusColor(code: number): string {
  if (code >= 200 && code < 300) return 'text-green-600'
  if (code >= 300 && code < 400) return 'text-yellow-600'
  if (code >= 400) return 'text-red-600'
  return 'text-secondary'
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
</script>

<template>
  <AxDialog
    v-model="isOpen"
    :title="props.parserName ? `测试 URL — ${props.parserName}` : '测试 URL'"
    icon="science"
    max-width="max-w-[820px]"
    body-class="!p-0"
    @close="handleCancel"
  >
    <div class="flex h-[520px] overflow-hidden">
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
            <span
              class="material-symbols-outlined text-[16px]"
              :style="iconFillStyle('test')"
            >science</span>
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
            <span
              class="material-symbols-outlined text-[16px]"
              :style="iconFillStyle('history')"
            >history</span>
            <span>请求历史</span>
            <span v-if="historyItems.length" class="ml-auto bg-primary text-on-primary text-[10px] rounded-full w-5 h-5 flex items-center justify-center font-bold">
              {{ historyItems.length > 99 ? '99+' : historyItems.length }}
            </span>
          </button>
        </nav>

        <div class="border-t border-outline-variant pt-ax-sm">
          <div class="px-2 text-[10px] text-outline">
            {{ props.parserName || '' }}
          </div>
        </div>
      </aside>

      <!-- ══════ 右侧内容 ══════ -->
      <div class="flex-1 flex flex-col min-w-0">
        <div class="flex-1 overflow-y-auto p-margin space-y-ax-sm">

          <!-- ──── Test URL Tab ──── -->
          <template v-if="activeTab === 'test'">
            <div class="border-b border-outline-variant pb-ax-sm mb-ax-sm">
              <h3 class="font-headline-sm text-headline-sm text-primary">测试 URL</h3>
              <p class="font-body-sm text-body-sm text-on-surface-variant mt-1">使用 Browser 或 HTTP 模式抓取目标 URL，查看返回内容。</p>
            </div>

            <!-- 模式选择 -->
            <section class="bg-white border border-outline-variant rounded-lg p-ax-md">
              <div class="flex items-center gap-ax-md">
                <div class="flex-1">
                  <p class="font-label-md text-label-md font-semibold text-primary">请求模式</p>
                  <p class="font-body-sm text-[11px] text-secondary mt-0.5">Browser 模式使用 Playwright 渲染页面，HTTP 模式直接请求。</p>
                </div>
                <div class="flex rounded-lg border border-outline-variant overflow-hidden">
                  <button
                    :class="[
                      'px-3 py-1.5 text-[12px] font-medium transition-colors cursor-pointer',
                      testMode === 'http' ? 'bg-primary text-on-primary' : 'bg-surface-container-lowest text-secondary hover:bg-surface-container-low',
                    ]"
                    @click="testMode = 'http'"
                  >HTTP</button>
                  <button
                    :class="[
                      'px-3 py-1.5 text-[12px] font-medium transition-colors cursor-pointer',
                      testMode === 'browser' ? 'bg-primary text-on-primary' : 'bg-surface-container-lowest text-secondary hover:bg-surface-container-low',
                    ]"
                    @click="testMode = 'browser'"
                  >Browser</button>
                </div>
              </div>
            </section>

            <!-- URL 输入 -->
            <section class="bg-white border border-outline-variant rounded-lg p-ax-md space-y-ax-sm">
              <div class="flex items-center gap-ax-sm mb-ax-xs">
                <span class="material-symbols-outlined text-[16px] text-primary">link</span>
                <span class="font-label-md text-label-md font-semibold text-primary">请求 URL</span>
              </div>
              <div class="flex gap-ax-xs">
                <AxInput v-model="testUrl" size="lg" placeholder="https://cd.58.com/ershouche/" class="flex-1" />
                <AxButton
                  variant="primary"
                  size="lg"
                  icon="play_arrow"
                  :loading="testRunning"
                  :disabled="!testUrl.trim()"
                  @click="runTest"
                >发送请求</AxButton>
              </div>
            </section>

            <!-- HTTP 配置（仅 HTTP 模式显示） -->
            <template v-if="testMode === 'http'">
              <section class="bg-white border border-outline-variant rounded-lg p-ax-md space-y-ax-sm">
                <div class="flex items-center gap-ax-sm mb-ax-xs">
                  <span class="material-symbols-outlined text-[16px] text-primary">settings_ethernet</span>
                  <span class="font-label-md text-label-md font-semibold text-primary">HTTP 配置</span>
                </div>

                <!-- Method -->
                <div class="flex items-center gap-ax-md">
                  <span class="font-body-sm text-[12px] text-secondary w-14 shrink-0">Method</span>
                  <div class="flex rounded-lg border border-outline-variant overflow-hidden">
                    <button
                      v-for="opt in httpMethodOpts" :key="opt.value"
                      :class="[
                        'px-3 py-1 text-[11px] font-medium transition-colors cursor-pointer',
                        testMethod === opt.value ? 'bg-primary text-on-primary' : 'bg-surface-container-lowest text-secondary hover:bg-surface-container-low',
                      ]"
                      @click="testMethod = opt.value as any"
                    >{{ opt.label }}</button>
                  </div>
                </div>

                <!-- Headers -->
                <div>
                  <div class="flex items-center justify-between mb-ax-xs">
                    <span class="font-body-sm text-[12px] text-secondary">Headers</span>
                    <span class="font-body-sm text-[10px] text-outline">每行一条，格式: key: value</span>
                  </div>
                  <AxInput v-model="testHeaders" size="lg" :multiline="true" :rows="3" resize="vertical" placeholder="User-Agent: Mozilla/5.0..." class="font-mono text-[12px]" />
                </div>

                <!-- Cookies -->
                <div>
                  <div class="flex items-center justify-between mb-ax-xs">
                    <span class="font-body-sm text-[12px] text-secondary">Cookies</span>
                    <span class="font-body-sm text-[10px] text-outline">格式: k1=v1; k2=v2</span>
                  </div>
                  <AxInput v-model="testCookies" size="lg" placeholder="session=abc123; token=xyz" class="font-mono text-[12px]" />
                </div>

                <!-- Body（仅 POST/PUT 显示） -->
                <template v-if="showBodyConfig">
                  <div class="border-t border-outline-variant/40 pt-ax-sm">
                    <div class="flex items-center gap-ax-md">
                      <span class="font-body-sm text-[12px] text-secondary w-14 shrink-0">Body</span>
                      <div class="flex rounded-lg border border-outline-variant overflow-hidden">
                        <button
                          v-for="opt in bodyTypeOpts" :key="opt.value"
                          :class="[
                            'px-2.5 py-1 text-[11px] font-medium transition-colors cursor-pointer',
                            testBodyType === opt.value ? 'bg-primary text-on-primary' : 'bg-surface-container-lowest text-secondary hover:bg-surface-container-low',
                          ]"
                          @click="testBodyType = opt.value as any"
                        >{{ opt.label }}</button>
                      </div>
                    </div>
                    <div v-if="testBodyType !== 'none'" class="mt-ax-xs">
                      <AxInput
                        v-model="testBodyContent"
                        size="lg"
                        :multiline="true"
                        :rows="testBodyType === 'json' ? 5 : 3"
                        resize="vertical"
                        :placeholder="testBodyType === 'json' ? '{ &quot;key&quot;: &quot;value&quot; }' : testBodyType === 'form-data' ? 'key1=value1&key2=value2' : '输入请求体内容...'"
                        class="font-mono text-[12px]"
                      />
                    </div>
                  </div>
                </template>
              </section>
            </template>

            <!-- 结果展示 -->
            <section v-if="testResult" class="bg-white border border-outline-variant rounded-lg p-ax-md">
              <div class="flex items-center gap-ax-sm mb-ax-sm">
                <span class="material-symbols-outlined text-[16px]" :class="testResult.ok ? 'text-green-600' : 'text-error'">
                  {{ testResult.ok ? 'check_circle' : 'error' }}
                </span>
                <span class="font-label-md text-label-md font-semibold text-primary">请求结果</span>
              </div>

              <template v-if="testResult.ok">
                <div class="flex flex-wrap gap-x-ax-xl gap-y-ax-xs mb-ax-sm text-[12px]">
                  <div>
                    <span class="text-secondary">状态: </span>
                    <span :class="statusColor(testResult.status_code)" class="font-bold">{{ testResult.status_code }}</span>
                  </div>
                  <div>
                    <span class="text-secondary">耗时: </span>
                    <span class="text-primary font-bold">{{ testResult.duration_ms }}ms</span>
                  </div>
                  <div>
                    <span class="text-secondary">大小: </span>
                    <span class="text-primary">{{ (testResult.content_length / 1024).toFixed(1) }}KB</span>
                  </div>
                  <div>
                    <span class="text-secondary">类型: </span>
                    <span class="text-primary font-mono text-[11px]">{{ testResult.content_type || '-' }}</span>
                  </div>
                </div>

                <!-- 响应 Headers 折叠 -->
                <details class="mb-ax-sm">
                  <summary class="font-body-sm text-[11px] text-secondary cursor-pointer hover:text-primary select-none">
                    Response Headers ({{ Object.keys(testResult.headers || {}).length }})
                  </summary>
                  <div class="mt-ax-xs bg-surface-container-lowest rounded p-ax-sm font-mono text-[11px] max-h-40 overflow-y-auto">
                    <div v-for="(v, k) in testResult.headers" :key="k" class="text-secondary">
                      <span class="text-primary font-semibold">{{ k }}</span>: {{ v }}
                    </div>
                  </div>
                </details>

                <!-- Body Preview -->
                <div>
                  <div class="font-body-sm text-[11px] text-secondary mb-ax-xs">Response Body</div>
                  <pre class="bg-surface-container-lowest rounded p-ax-sm font-mono text-[11px] text-primary leading-relaxed max-h-80 overflow-y-auto whitespace-pre-wrap break-all">{{ testResult.body_preview }}</pre>
                </div>
              </template>

              <template v-else>
                <div class="bg-error-container text-on-error-container rounded-lg p-ax-sm text-[12px]">
                  <span class="font-bold">{{ testResult.error_type }}</span>: {{ testResult.error }}
                </div>
              </template>
            </section>
          </template>

          <!-- ──── History Tab ──── -->
          <template v-if="activeTab === 'history'">
            <div class="flex items-center justify-between border-b border-outline-variant pb-ax-sm mb-ax-sm">
              <div>
                <h3 class="font-headline-sm text-headline-sm text-primary">请求历史</h3>
                <p class="font-body-sm text-body-sm text-on-surface-variant mt-1">本地存储的测试记录，点击恢复配置。</p>
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
                  <div class="flex-1 min-w-0 cursor-pointer py-0.5" @click="restoreFromHistory(item.id)">
                    <div class="flex items-center gap-ax-xs">
                      <span
                        :class="[
                          'text-[10px] px-1.5 py-0.5 rounded font-bold',
                          item.mode === 'http' ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700',
                        ]"
                      >{{ item.mode.toUpperCase() }}</span>
                      <span class="text-[10px] px-1.5 py-0.5 rounded bg-surface-container-low text-secondary font-bold">{{ item.method }}</span>
                      <span class="font-mono text-[11px] text-primary truncate">{{ item.url }}</span>
                    </div>
                    <div class="flex gap-ax-md text-[10px] text-outline">
                      <span v-if="item.headers">{{ item.headers.slice(0, 60) }}{{ item.headers.length > 60 ? '...' : '' }}</span>
                      <span v-if="item.cookies">Cookies: {{ item.cookies.slice(0, 40) }}...</span>
                      <span v-if="item.bodyType !== 'none'" class="text-primary">Body: {{ item.bodyType }}</span>
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
