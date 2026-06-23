<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { configApi } from '@/api'
import { useNotify } from '@/components/ui'
import AmapNearbySearch from '@/components/AmapNearbySearch.vue'

const route = useRoute()
const router = useRouter()
const { triggerNotify } = useNotify()

// ── 高德配置（从后端加载） ──
const amapKey = ref('')
const amapSecurityCode = ref('')
const amapWebapiKey = ref('')
const ready = ref(false)
const notConfigured = ref(false)

// ── v-model 值（从 URL query 初始化） ──
const lng = ref((route.query.lng as string) || '116.397428')
const lat = ref((route.query.lat as string) || '39.909230')
const radius = ref((route.query.radius as string) || '3000')
const sortBy = ref((route.query.sortBy as string) || 'distance')
const keyword = ref((route.query.keyword as string) || '')

// ── 组件引用 ──
const amapRef = ref<InstanceType<typeof AmapNearbySearch> | null>(null)

// ── 同步到 URL ──
let syncTimer: any = null

function syncToUrl() {
  clearTimeout(syncTimer)
  syncTimer = setTimeout(() => {
    router.replace({
      query: {
        lng: lng.value,
        lat: lat.value,
        radius: radius.value,
        sortBy: sortBy.value,
        ...(keyword.value ? { keyword: keyword.value } : {}),
      },
    })
  }, 300)
}

watch([lng, lat, radius, sortBy, keyword], syncToUrl)

// ── 加载配置 ──
onMounted(async () => {
  try {
    const raw = await configApi.getAll()
    const cfg: Record<string, string> = {}
    raw.forEach((item: any) => { cfg[item.key] = item.value })

    amapKey.value = cfg['amap_key'] || ''
    amapSecurityCode.value = cfg['amap_security_code'] || ''
    amapWebapiKey.value = cfg['amap_webapi_key'] || ''

    if (!amapKey.value) {
      notConfigured.value = true
      triggerNotify('高德 API Key 未配置', 'error', '请先在「配置 → 地图」中填写')
      return
    }

    ready.value = true
  } catch (e: any) {
    triggerNotify('加载配置失败: ' + (e.message || String(e)), 'error')
  }
})
</script>

<template>
  <!-- 未配置 -->
  <div v-if="notConfigured" class="flex items-center justify-center h-full">
    <div class="text-center space-y-ax-md">
      <div class="text-error text-sm">请先在「配置 → 地图」中填写高德 API Key 和安全密钥</div>
      <AxButton variant="outline" size="lg" @click="$router.push('/config')">前往配置</AxButton>
    </div>
  </div>

  <!-- 地图组件 -->
  <AmapNearbySearch
    v-else-if="ready"
    ref="amapRef"
    :amap-key="amapKey"
    :amap-security-code="amapSecurityCode"
    :amap-webapi-key="amapWebapiKey"
    v-model:lng="lng"
    v-model:lat="lat"
    v-model:radius="radius"
    v-model:sort-by="sortBy"
    v-model:keyword="keyword"
  />

  <!-- 加载中 -->
  <div v-else class="flex items-center justify-center h-full text-secondary text-sm">
    加载中…
  </div>
</template>
