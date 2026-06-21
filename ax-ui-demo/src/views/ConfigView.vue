<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { configApi } from '@/api'
import { useNotify } from '@/components/ui'

const { triggerNotify } = useNotify()

// ---- 类型推断 & 标签 ----
type ConfigType = 'bool' | 'number' | 'select' | 'text'

interface ConfigItem {
  key: string
  value: any
  desc: string
  updated: string
  type: ConfigType
  label: string
}

const LABEL_MAP: Record<string, string> = {
  proxy_enabled: '启用代理', proxy_provider: '代理服务商', proxy_api_url: 'API 提取 URL',
  proxy_fetch_num: '每次拉取数', proxy_ttl: 'IP 有效期(秒)', proxy_max_use: '单 IP 最大使用次数',
  proxy_health_interval: '健康检查间隔(秒)',
  cache_enabled: '启用静态缓存', cache_html_ttl: 'HTML 缓存有效期(秒)',
  image_download: '下载业务图片',
  request_concurrency: '全局并发数', request_interval_min: '最小间隔(秒)',
  request_interval_max: '最大间隔(秒)', request_timeout: '请求超时(秒)',
  retry_network: '网络重试次数', retry_5xx: '5xx 重试次数',
  domain_rate_limit: '单域名速率(/s)', ip_rate_limit: '单 IP 速率(/min)',
  captcha_enabled: '处理验证码', captcha_auto_solve: '自动接码',
  captcha_max_retry: '接码重试次数', captcha_fallback: '降级策略',
  captcha_max_switch: '最多换 IP 次数', captcha_cooldown: 'IP 冷却(秒)',
  log_level: '日志级别',
}

const BOOL_KEYS = new Set(['proxy_enabled', 'cache_enabled', 'image_download', 'captcha_enabled', 'captcha_auto_solve'])
const SELECT_OPTIONS: Record<string, Array<{ value: string; label: string }>> = {
  proxy_provider: [{ value: 'juliang', label: '巨量' }, { value: 'kuaidaili', label: '快代理' }],
  log_level: [{ value: 'INFO', label: 'INFO' }, { value: 'DEBUG', label: 'DEBUG' }],
  captcha_fallback: [{ value: 'manual', label: '手动处理' }, { value: 'switch_ip', label: '换 IP' }],
}

function inferType(key: string): ConfigType {
  if (BOOL_KEYS.has(key)) return 'bool'
  if (key in SELECT_OPTIONS) return 'select'
  return 'number'  // body 25 项中 bool/select 之外全是 number；proxy_api_url 在默认里为空但也是 text，作为特例处理
}

// ---- 数据 ----
const configs = ref<ConfigItem[]>([])

const loadConfigs = async () => {
  try {
    const raw = await configApi.getAll()
    configs.value = raw.map((item: { key: string; value: string; desc: string; updated: string }) => {
      const type = inferType(item.key)
      return {
        ...item,
        type,
        label: LABEL_MAP[item.key] || item.key,
        value: type === 'bool' ? (item.value === 'true') : item.value,
      }
    })
  } catch {}
}

// ---- 分类 & Tab ----
const activeTab = ref(0)
const tabs = ['代理IP', '反爬限速', '验证码', '系统']

const CATEGORY_RULES: Array<(key: string) => boolean> = [
  k => k.startsWith('proxy_'),
  k => k.startsWith('request_') || k.startsWith('cache_') || k.startsWith('image_'),
  k => k.startsWith('captcha_'),
  () => true,  // 兜底
]

const filteredConfigs = computed(() =>
  configs.value.filter(c => CATEGORY_RULES[activeTab.value](c.key))
)

// ---- 操作 ----
const dirty = ref(false)

const markDirty = () => { dirty.value = true }

const doSave = async () => {
  const data: Record<string, string> = {}
  configs.value.forEach(c => {
    data[c.key] = typeof c.value === 'boolean' ? (c.value ? 'true' : 'false') : String(c.value)
  })
  try { await configApi.update(data); triggerNotify('配置已保存', 'success'); dirty.value = false } catch {}
}

const doReset = async () => {
  try { await configApi.reset(); triggerNotify('已重置为默认值', 'success'); loadConfigs(); dirty.value = false } catch {}
}

onMounted(loadConfigs)
</script>

<template>
  <div class="space-y-ax-md">
    <!-- Tabs -->
    <div class="flex gap-1 border-b border-outline-variant">
      <button
        v-for="(tab, i) in tabs"
        :key="tab"
        @click="activeTab = i"
        :class="['text-xs px-4 py-2 -mb-px border-b-2 transition-colors',
          activeTab === i ? 'border-primary text-primary font-medium' : 'border-transparent text-secondary hover:text-primary']"
      >{{ tab }}</button>
    </div>

    <!-- Config rows -->
    <div class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden">
      <template v-if="filteredConfigs.length">
        <div
          v-for="cfg in filteredConfigs"
          :key="cfg.key"
          class="flex items-center gap-ax-md px-4 py-ax-sm border-b border-outline-variant/50 last:border-b-0"
        >
          <!-- 标题 + 描述 -->
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-primary">{{ cfg.label }}</p>
            <p class="text-xs text-secondary mt-0.5">{{ cfg.desc }}</p>
          </div>
          <!-- UI 控件 -->
          <div class="shrink-0">
            <AxSwitch
              v-if="cfg.type === 'bool'"
              :model-value="cfg.value"
              @update:model-value="cfg.value = $event; markDirty()"
            />
            <AxSelect
              v-else-if="cfg.type === 'select'"
              v-model="cfg.value"
              size="lg"
              :options="SELECT_OPTIONS[cfg.key]"
              @update:model-value="markDirty()"
            />
            <AxInput
              v-else
              v-model="cfg.value"
              size="lg"
              type="number"
              class="w-28"
              @update:model-value="markDirty()"
            />
          </div>
        </div>
      </template>
      <div v-else class="p-ax-lg text-center text-secondary text-sm">暂无配置项</div>

      <!-- Footer -->
      <div class="px-4 py-ax-sm border-t border-outline-variant flex justify-between items-center">
        <span class="text-[11px] text-secondary">{{ dirty ? '有未保存的修改' : '配置改动立即生效' }}</span>
        <div class="flex gap-ax-sm">
          <AxButton variant="outline" size="lg" @click="doReset">重置默认</AxButton>
          <AxButton variant="primary" size="lg" :disabled="!dirty" @click="doSave">保存全部</AxButton>
        </div>
      </div>
    </div>
  </div>
</template>
