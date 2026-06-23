<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'

// ── Props ──
const props = defineProps<{
  amapKey: string
  amapSecurityCode?: string
  amapWebapiKey?: string
}>()

// ── v-model ──
const lng = defineModel<string>('lng', { default: '116.397428' })
const lat = defineModel<string>('lat', { default: '39.909230' })
const radius = defineModel<string>('radius', { default: '3000' })
const sortBy = defineModel<string>('sortBy', { default: 'distance' })
const keyword = defineModel<string>('keyword', { default: '' })

// ── 地图实例 ──
let map: any = null
let placeSearch: any = null
let markers: any[] = []
let currentInfoWin: any = null

const loading = ref(true)
const loadError = ref('')

// ── 搜索参数选项 ──
const radiusOptions = [
  { value: '500', label: '范围 500m' },
  { value: '1000', label: '范围 1km' },
  { value: '3000', label: '范围 3km' },
  { value: '5000', label: '范围 5km' },
  { value: '10000', label: '范围 10km' },
  { value: '20000', label: '范围 20km' },
]
const sortOptions = [
  { value: 'distance', label: '按距离排序' },
  { value: 'rating', label: '按评分排序' },
]

// ── 结果 ──
const currentPois = ref<any[]>([])
const activeIdx = ref(-1)
const searching = ref(false)

// ── 详情 ──
const showDetail = ref(false)
const detailPoi = ref<any>(null)

// ── Toast ──
const toastMsg = ref('')
const toastVisible = ref(false)
let toastTimer: any = null

function showToast(msg: string) {
  toastMsg.value = msg
  toastVisible.value = true
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastVisible.value = false }, 2000)
}

// ── 加载 AMap JS API ──
function loadAMapScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if ((window as any).AMap) { resolve(); return }

    if (props.amapSecurityCode) {
      (window as any)._AMapSecurityConfig = { securityJsCode: props.amapSecurityCode }
    }

    const loader = document.createElement('script')
    loader.src = 'https://webapi.amap.com/loader.js'
    loader.onload = () => {
      ;(window as any).AMapLoader.load({
        key: props.amapKey,
        version: '2.0',
        plugins: ['AMap.PlaceSearch', 'AMap.Geolocation', 'AMap.Scale', 'AMap.ToolBar'],
      }).then(() => resolve()).catch(reject)
    }
    loader.onerror = () => reject(new Error('网络错误'))
    document.head.appendChild(loader)
  })
}

function initMap() {
  const center: [number, number] = [parseFloat(lng.value), parseFloat(lat.value)]
  map = new (window as any).AMap.Map('amap-container', {
    zoom: 14,
    center,
    resizeEnable: true,
  })
  map.addControl(new (window as any).AMap.Scale())
  map.addControl(new (window as any).AMap.ToolBar({
    position: { right: '12px', bottom: '40px' },
  }))

  placeSearch = new (window as any).AMap.PlaceSearch({
    pageSize: 25,
    pageIndex: 1,
    extensions: 'all',
  })

  syncCoords()
  map.on('moveend', syncCoords)
  map.on('click', () => {
    if (currentInfoWin) { currentInfoWin.close(); currentInfoWin = null }
  })
}

function syncCoords() {
  if (!map) return
  const c = map.getCenter()
  lng.value = c.lng.toFixed(6)
  lat.value = c.lat.toFixed(6)
}

function getCenter(): [number, number] {
  const nlng = parseFloat(lng.value)
  const nlat = parseFloat(lat.value)
  if (!isNaN(nlng) && !isNaN(nlat)) return [nlng, nlat]
  if (map) {
    const c = map.getCenter()
    return [c.lng, c.lat]
  }
  return [116.397428, 39.90923]
}

// ── 搜索 ──
function doApiSearch() {
  const kw = keyword.value.trim()
  if (!kw) { showToast('请输入搜索关键词'); return }
  if (!props.amapWebapiKey) { showToast('请先配置高德 Web服务 Key'); return }

  const center = getCenter()
  if (map) map.setCenter(center)
  searching.value = true
  currentPois.value = []

  const loc = `${center[0]},${center[1]}`
  const sortrule = sortBy.value === 'rating' ? 'weight' : 'distance'

  fetch(
    `https://restapi.amap.com/v3/place/around?key=${props.amapWebapiKey}&location=${loc}&radius=${radius.value}&keywords=${encodeURIComponent(kw)}&sortrule=${sortrule}&offset=25&page=1&extensions=all`
  )
    .then(r => r.json())
    .then(data => {
      searching.value = false
      if (data.status === '1' && data.pois) {
        const pois = data.pois.map((p: any) => ({
          ...p,
          location: { lng: parseFloat(p.location.split(',')[0]), lat: parseFloat(p.location.split(',')[1]) },
          distance: parseInt(p.distance) || 0,
          biz_ext: p.biz_ext || {},
          photos: p.photos || [],
        }))
        if (sortBy.value === 'rating') {
          pois.sort((a: any, b: any) => ((b.biz_ext && b.biz_ext.rating) || 0) - ((a.biz_ext && a.biz_ext.rating) || 0))
        }
        currentPois.value = pois
        activeIdx.value = -1
        addMarkers(pois)
        showToast(`找到 ${pois.length} 个结果`)
      } else {
        showToast(data.info || '未找到结果')
        clearAll()
      }
    })
    .catch(e => {
      searching.value = false
      showToast('请求失败: ' + e.message)
    })
}

function doSearch() {
  const kw = keyword.value.trim()
  if (!kw) { showToast('请输入搜索关键词'); return }
  const center = getCenter()
  const r = parseInt(radius.value) || 3000
  if (map) map.setCenter(center)
  searching.value = true
  currentPois.value = []

  placeSearch.searchNearBy(kw, center, r, (status: string, result: any) => {
    searching.value = false
    if (status === 'complete' && result.poiList && result.poiList.pois.length > 0) {
      const pois = result.poiList.pois.map((p: any) => ({
        ...p,
        distance: p.distance || Math.round(
          (window as any).AMap.GeometryUtil.distance(
            [p.location.lng, p.location.lat], center
          )
        ),
      }))

      if (sortBy.value === 'rating') {
        pois.sort((a: any, b: any) =>
          ((b.biz_ext && b.biz_ext.rating) || 0) - ((a.biz_ext && a.biz_ext.rating) || 0)
        )
      } else {
        pois.sort((a: any, b: any) => a.distance - b.distance)
      }

      currentPois.value = pois
      activeIdx.value = -1
      addMarkers(pois)
      showToast(`找到 ${pois.length} 个结果`)
    } else {
      showToast(`未找到「${kw}」相关结果`)
      clearAll()
    }
  })
}

function clearAll() {
  currentPois.value = []
  activeIdx.value = -1
  clearMarkers()
  closeDetail()
}

// ── Markers ──
function clearMarkers() {
  markers.forEach(m => { m.setMap(null); if (m._iw) m._iw.close() })
  markers = []
  currentInfoWin = null
}

function addMarkers(pois: any[]) {
  clearMarkers()
  const AMap = (window as any).AMap
  pois.forEach((poi, i) => {
    const m = new AMap.Marker({
      position: [poi.location.lng, poi.location.lat],
      title: poi.name,
      label: {
        content:
          '<span style="background:#ef4444;color:#fff;padding:2px 8px;' +
          'border-radius:12px;font-size:11px;font-weight:700;' +
          'box-shadow:0 1px 4px rgba(0,0,0,0.2);">' + (i + 1) + '</span>',
        offset: new AMap.Pixel(-14, -40),
      },
      zIndex: 100 - i,
    })

    const iw = new AMap.InfoWindow({
      content:
        '<div style="font-size:12px;color:#1f2937;max-width:210px;line-height:1.5;">' +
        '<div style="font-weight:600;font-size:13px;margin-bottom:3px;">' + poi.name + '</div>' +
        '<div style="color:#6b7280;font-size:11px;">' + (poi.address || '') + '</div>' +
        (poi.tel ? '<div style="color:#3b82f6;font-size:11px;margin-top:2px;">📞 ' + poi.tel + '</div>' : '') +
        '</div>',
      offset: new AMap.Pixel(0, -36),
    })

    m.on('click', () => {
      if (currentInfoWin) currentInfoWin.close()
      iw.open(map, m.getPosition())
      currentInfoWin = iw
      openDetail(i)
    })
    m._iw = iw
    m.setMap(map)
    markers.push(m)
  })
  if (pois.length > 0) {
    const padR = window.innerWidth <= 768 ? 20 : 420
    map.setFitView(markers, false, [60, 60, 20, padR])
  }
}

// ── 详情 ──
function openDetail(idx: number) {
  if (idx < 0 || idx >= currentPois.value.length) return
  closeDetail()
  const poi = currentPois.value[idx]
  detailPoi.value = poi
  activeIdx.value = idx

  if (map) map.setZoomAndCenter(16, [poi.location.lng, poi.location.lat])
  if (markers[idx]) {
    if (currentInfoWin) currentInfoWin.close()
    markers[idx]._iw.open(map, markers[idx].getPosition())
    currentInfoWin = markers[idx]._iw
  }

  nextTick(() => { showDetail.value = true })
}

function closeDetail() {
  showDetail.value = false
  activeIdx.value = -1
  if (currentInfoWin) { currentInfoWin.close(); currentInfoWin = null }
}

// ── POI 辅助 ──
function getIconClass(type = '') {
  const s = type.toLowerCase()
  if (/餐饮|餐厅|美食|咖啡|茶/.test(s)) return 'restaurant'
  if (/酒店|宾馆|住宿|民宿/.test(s)) return 'hotel'
  if (/购物|商场|超市|便利店/.test(s)) return 'shop'
  if (/加油|充电/.test(s)) return 'gas'
  if (/银行|金融|ATM/.test(s)) return 'bank'
  if (/医院|诊所|药/.test(s)) return 'hospital'
  return 'default'
}

function getEmoji(type = '') {
  const s = type.toLowerCase()
  if (/餐饮|餐厅|美食/.test(s)) return '🍽️'
  if (/咖啡/.test(s)) return '☕'
  if (/茶/.test(s)) return '🍵'
  if (/酒店|宾馆|住宿|民宿/.test(s)) return '🏨'
  if (/购物|商场/.test(s)) return '🛍️'
  if (/超市/.test(s)) return '🏪'
  if (/加油站/.test(s)) return '⛽'
  if (/充电/.test(s)) return '🔌'
  if (/银行/.test(s)) return '🏦'
  if (/医院/.test(s)) return '🏥'
  if (/诊所/.test(s)) return '🩺'
  if (/药店/.test(s)) return '💊'
  if (/公园/.test(s)) return '🌳'
  if (/学校/.test(s)) return '🏫'
  return '📍'
}

function poiPhotoUrl(poi: any) {
  if (poi.photos && poi.photos.length) {
    const url = poi.photos[0].url
    return url + (url.includes('?') ? '&' : '?') + 'size=120*120'
  }
  return null
}

function poiPhotoUrls(poi: any) {
  if (!poi.photos || !poi.photos.length) return []
  return poi.photos.slice(0, 6).map((ph: any) =>
    ph.url + (ph.url.includes('?') ? '&' : '?') + 'size=360*240'
  )
}

// ── 定位 ──
function doLocate() {
  if (!map) return
  const AMap = (window as any).AMap
  const geo = new AMap.Geolocation({
    enableHighAccuracy: true, timeout: 8000,
    showCircle: false, panToLocation: true, zoomToAccuracy: true,
  })
  map.addControl(geo)
  geo.getCurrentPosition((status: string, result: any) => {
    if (status === 'complete') {
      map.setZoomAndCenter(16, [result.position.lng, result.position.lat])
      syncCoords()
      showToast('已定位到当前位置')
    } else {
      showToast('定位失败，请检查浏览器位置权限')
    }
  })
}

// ── 键盘快捷键 ──
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') { closeDetail() }
}

// ── 初始化 ──
onMounted(async () => {
  if (!props.amapKey) {
    loadError.value = '缺少 amapKey，请传入有效的 API Key'
    loading.value = false
    return
  }

  try {
    await loadAMapScript()
    initMap()
    loading.value = false
    document.addEventListener('keydown', onKeydown)
  } catch (e: any) {
    loadError.value = '加载失败: ' + (e.message || String(e))
    loading.value = false
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  clearMarkers()
  if (map) map.destroy()
})

// ── 暴露方法 ──
defineExpose({ search: doSearch, openDetail })
</script>

<template>
  <div id="amap-app" class="flex w-full overflow-hidden" style="height: calc(100% + var(--spacing-margin) * 2); margin: calc(var(--spacing-margin) * -1)">
    <!-- ── 侧边栏 ── -->
    <aside class="w-[380px] min-w-[380px] h-full bg-surface-container-lowest border-r border-outline-variant flex flex-col overflow-hidden shadow-sm">
      <div class="px-4 pt-4 flex-shrink-0">
        <h2 class="text-sm font-semibold text-primary mb-ax-sm">附近搜索</h2>
        <div class="flex gap-ax-sm mb-ax-sm">
          <AxInput v-model="lng" size="lg" placeholder="经度" style="font-family: 'JetBrains Mono'" />
          <AxInput v-model="lat" size="lg" placeholder="纬度" style="font-family: 'JetBrains Mono'" />
        </div>
      </div>

      <div class="px-4 pb-ax-sm flex-shrink-0 space-y-ax-sm">
        <AxInput v-model="keyword" size="lg" placeholder="搜索关键词：餐厅 / 酒店 / 加油站…" @keydown="(e: KeyboardEvent) => e.key === 'Enter' && doSearch()" />
        <div class="flex gap-ax-sm">
          <div style="flex:1"><AxSelect v-model="radius" :options="radiusOptions" size="lg" /></div>
          <div style="flex:1"><AxSelect v-model="sortBy" :options="sortOptions" size="lg" /></div>
        </div>
        <div class="flex gap-ax-sm">
          <AxButton variant="primary" size="lg" @click="doSearch" :loading="searching" style="flex:1">搜索</AxButton>
          <AxButton variant="outline" size="lg" @click="doApiSearch" :disabled="!props.amapWebapiKey" style="flex:1">API</AxButton>
          <AxButton variant="outline" size="lg" @click="doLocate" style="flex:1"><span class="material-symbols-outlined text-sm">my_location</span> 定位</AxButton>
        </div>
      </div>

      <!-- 结果列表 -->
      <div class="flex-1 overflow-hidden flex flex-col border-t border-outline-variant">
        <div class="flex justify-between items-center px-4 py-ax-sm flex-shrink-0 border-b border-outline-variant/50">
          <span class="text-xs text-secondary">{{ currentPois.length ? currentPois.length + ' 个结果' : '输入关键词搜索' }}</span>
          <button v-if="currentPois.length" class="text-xs text-secondary hover:text-primary cursor-pointer bg-transparent border-none" @click="clearAll">清除</button>
        </div>

        <div class="flex-1 overflow-y-auto">
          <template v-if="currentPois.length">
            <div
              v-for="(poi, i) in currentPois"
              :key="i"
              class="flex items-start gap-ax-sm px-4 py-ax-sm border-b border-outline-variant/50 cursor-pointer transition-colors hover:bg-surface-container-low"
              :class="{ 'bg-secondary-container border-l-[3px] border-l-primary pl-[13px]': activeIdx === i }"
              @click="openDetail(i)"
            >
              <div class="w-11 h-11 rounded-lg flex items-center justify-center text-xl flex-shrink-0"
                :class="{
                  'bg-error/8': getIconClass(poi.type || '') === 'restaurant',
                  'bg-primary/8': getIconClass(poi.type || '') === 'hotel',
                  'bg-warning/8': getIconClass(poi.type || '') === 'shop',
                  'bg-success/8': getIconClass(poi.type || '') === 'gas',
                  'bg-purple-500/8': getIconClass(poi.type || '') === 'bank',
                  'bg-pink-500/8': getIconClass(poi.type || '') === 'hospital',
                  'bg-black/[0.04]': getIconClass(poi.type || '') === 'default',
                }"
              >{{ getEmoji(poi.type || '') }}</div>

              <div class="flex-1 min-w-0">
                <div class="text-sm font-medium truncate text-primary">{{ poi.name }}</div>
                <div class="text-xs text-secondary mt-0.5">{{ (poi.type || '').split(';')[0].split('|')[0] || '' }}</div>
                <div class="flex items-center gap-ax-md text-xs mt-1">
                  <span class="text-primary font-medium font-mono">{{ poi.distance }}m</span>
                  <span v-if="poi.biz_ext && poi.biz_ext.rating" class="text-warning">{{ poi.biz_ext.rating }} 分</span>
                </div>
              </div>

              <img
                v-if="poiPhotoUrl(poi)"
                :src="poiPhotoUrl(poi)!"
                class="w-14 h-14 rounded-md object-cover flex-shrink-0 bg-surface-container"
                loading="lazy"
              />
              <span class="flex-shrink-0 text-secondary text-sm self-center">›</span>
            </div>
          </template>
          <div v-else class="flex items-center justify-center h-full text-secondary text-sm text-center px-6">
            {{ searching ? '搜索中…' : '输入关键词后点击「搜索」' }}
          </div>
        </div>
      </div>
    </aside>

    <!-- ── 地图 ── -->
    <main id="amap-container" class="flex-1 h-full relative"></main>

    <!-- ── 详情面板 ── -->
    <div
      v-if="showDetail"
      class="w-[420px] min-w-[420px] h-full bg-surface-container-lowest border-l border-outline-variant flex flex-col overflow-hidden shadow-[0_0_24px_rgba(0,0,0,0.06)] animate-[slideIn_.25s_ease] relative"
    >
      <button
        class="absolute top-ax-sm right-ax-sm z-10 w-7 h-7 rounded-full bg-black/[0.06] hover:bg-black/[0.12] border-none text-secondary cursor-pointer flex items-center justify-center transition-colors"
        @click="closeDetail"
      ><span class="material-symbols-outlined text-sm">close</span></button>

      <!-- 照片 -->
      <div v-if="poiPhotoUrls(detailPoi).length" class="flex gap-1.5 overflow-x-auto px-4 pb-3 flex-shrink-0 pt-4">
        <img
          v-for="(url, j) in poiPhotoUrls(detailPoi)"
          :key="j"
          :src="url"
          class="h-[100px] w-[150px] rounded-lg object-cover flex-shrink-0 bg-surface-container"
          loading="lazy"
        />
      </div>

      <!-- 头部 -->
      <div class="px-4 pt-4 pb-2 flex-shrink-0">
        <h3 class="text-base font-semibold text-primary leading-snug">{{ detailPoi?.name }}</h3>
        <div class="flex items-center gap-ax-sm mt-ax-sm">
          <span class="text-xs px-ax-sm py-0.5 rounded-full bg-black/[0.06] text-secondary">{{ (detailPoi?.type || '').split(';')[0].split('|')[0] || 'POI' }}</span>
          <span v-if="detailPoi?.distance" class="text-xs text-secondary font-mono">{{ detailPoi.distance }}m</span>
          <span v-if="detailPoi?.biz_ext?.rating" class="text-xs font-medium" style="color:#f59e0b">★ {{ detailPoi.biz_ext.rating }}</span>
        </div>
      </div>

      <!-- 属性列表 -->
      <div class="px-4 pb-4 overflow-y-auto flex-1">
        <div v-if="detailPoi?.address" class="flex py-ax-sm border-b border-outline-variant/50">
          <span class="w-5 text-center flex-shrink-0 text-[13px] leading-5 mr-3">📍</span>
          <div class="text-sm text-primary leading-relaxed">{{ detailPoi.address }}</div>
        </div>
        <div v-if="detailPoi?.tel || detailPoi?.biz_ext?.tel" class="flex py-ax-sm border-b border-outline-variant/50">
          <span class="w-5 text-center flex-shrink-0 text-[13px] leading-5 mr-3">📞</span>
          <div class="text-sm text-primary">{{ detailPoi.tel || detailPoi.biz_ext?.tel }}</div>
        </div>
        <div v-if="detailPoi?.biz_ext?.business_area" class="flex py-ax-sm border-b border-outline-variant/50">
          <span class="w-5 text-center flex-shrink-0 text-[13px] leading-5 mr-3">🏙️</span>
          <div class="text-sm text-primary">{{ detailPoi.biz_ext.business_area }}</div>
        </div>
        <div v-if="detailPoi?.biz_ext?.rating" class="flex py-ax-sm border-b border-outline-variant/50">
          <span class="w-5 text-center flex-shrink-0 text-[13px] leading-5 mr-3">⭐</span>
          <div class="text-sm text-primary">
            {{ detailPoi.biz_ext.rating }} 分
            <template v-if="detailPoi.biz_ext.cost"> · 人均 ¥{{ detailPoi.biz_ext.cost }}</template>
          </div>
        </div>
        <div v-else-if="detailPoi?.biz_ext?.cost" class="flex py-ax-sm border-b border-outline-variant/50">
          <span class="w-5 text-center flex-shrink-0 text-[13px] leading-5 mr-3">💰</span>
          <div class="text-sm text-primary">¥{{ detailPoi.biz_ext.cost }}</div>
        </div>
        <div v-if="detailPoi?.biz_ext?.opentime" class="flex py-ax-sm border-b border-outline-variant/50">
          <span class="w-5 text-center flex-shrink-0 text-[13px] leading-5 mr-3">🕐</span>
          <div class="text-sm text-primary">{{ detailPoi.biz_ext.opentime }}</div>
        </div>
        <div class="flex py-ax-sm border-b border-outline-variant/50">
          <span class="w-5 text-center flex-shrink-0 text-[13px] leading-5 mr-3">🏷️</span>
          <div class="text-sm text-primary">{{ (detailPoi?.type || '').split(';')[0].split('|').join(' › ') }}</div>
        </div>
        <div v-if="detailPoi" class="flex py-ax-sm border-b border-outline-variant/50">
          <span class="w-5 text-center flex-shrink-0 text-[13px] leading-5 mr-3">🌍</span>
          <div class="text-sm text-primary font-mono text-xs leading-5">{{ detailPoi.location.lng.toFixed(6) }}, {{ detailPoi.location.lat.toFixed(6) }}</div>
        </div>
      </div>
    </div>

    <!-- ── Toast ── -->
    <Teleport to="body">
      <div
        class="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[1000] px-6 py-ax-sm rounded-lg bg-gray-800/90 text-white text-sm pointer-events-none transition-opacity duration-250 shadow-lg"
        :class="{ 'opacity-100': toastVisible, 'opacity-0': !toastVisible }"
      >{{ toastMsg }}</div>
    </Teleport>

    <!-- ── 加载 / 错误状态 ── -->
    <div v-if="loading || loadError" class="absolute inset-0 z-50 bg-surface-container flex items-center justify-center">
      <div v-if="loading" class="text-secondary text-sm">地图加载中…</div>
      <div v-else class="text-center space-y-ax-md px-6">
        <div class="text-error text-sm">{{ loadError }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes slideIn {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}
</style>

<style>
/* 干掉 AMap Marker Label 默认蓝色边框 */
.amap-marker-label {
  border: none !important;
  padding: 0 !important;
  background: transparent !important;
}
</style>
