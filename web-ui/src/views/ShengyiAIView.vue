<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { shengyiApi } from '@/api'
import { useNotify } from '@/components/ui'

const { triggerNotify } = useNotify()

// ── 筛选器可选值 ──
const filterOptions = ref({
  districts: [] as string[],
  biz_statuses: [] as string[],
  biz_types: [] as string[],
  levels: [] as string[],
})

const districtOptions = computed(() =>
  filterOptions.value.districts.map(d => ({ value: d, label: d })),
)
const bizStatusOptions = computed(() =>
  filterOptions.value.biz_statuses.map(s => ({ value: s, label: s })),
)
const bizTypeOptions = computed(() =>
  filterOptions.value.biz_types.map(t => ({ value: t, label: t })),
)

// ── 搜索条件 ──
const search = ref('')
const selectedLevels = ref<string[]>([])
const district = ref('')
const bizStatus = ref('')
const bizType = ref('')
const scoreMin = ref('')
const scoreMax = ref('')
const wfStatus = ref('')

const toggleLevel = (level: string) => {
  const idx = selectedLevels.value.indexOf(level)
  if (idx >= 0) {
    selectedLevels.value.splice(idx, 1)
  } else {
    selectedLevels.value.push(level)
  }
}

// ── 分页/数据 ──
const items = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)

// ── 选中详情 ──
const selectedItem = ref<any>(null)

const fetchFilters = async () => {
  try {
    filterOptions.value = await shengyiApi.filters()
  } catch { /* ignore */ }
}

const buildParams = () => {
  const p: any = { page: page.value, size: size.value }
  if (search.value.trim()) p.search = search.value.trim()
  if (selectedLevels.value.length) p.level = selectedLevels.value.join(',')
  if (district.value) p.district = district.value
  if (bizStatus.value) p.biz_status = bizStatus.value
  if (bizType.value) p.biz_type = bizType.value
  if (scoreMin.value.trim()) p.score_min = Number(scoreMin.value)
  if (scoreMax.value.trim()) p.score_max = Number(scoreMax.value)
  if (wfStatus.value) p.status = wfStatus.value
  return p
}

const fetchData = async () => {
  loading.value = true
  try {
    const r: any = await shengyiApi.list(buildParams())
    items.value = r.items
    total.value = r.total
  } catch (e: any) {
    triggerNotify(e?.error || '数据加载失败', 'error')
  } finally {
    loading.value = false
  }
}

const onSearch = () => {
  page.value = 1
  selectedItem.value = null
  fetchData()
}

const onPageChange = (p: number) => {
  page.value = p
  fetchData()
}

const onSizeChange = (s: number) => {
  size.value = s
  page.value = 1
  fetchData()
}

const selectItem = (item: any) => {
  selectedItem.value = item
}

const resetFilters = () => {
  search.value = ''
  selectedLevels.value = []
  district.value = ''
  bizStatus.value = ''
  bizType.value = ''
  scoreMin.value = ''
  scoreMax.value = ''
  wfStatus.value = ''
  page.value = 1
  selectedItem.value = null
  fetchData()
}

// ── 辅助函数 ──
const levelColors: Record<string, string> = {
  '潜力极高': 'bg-emerald-100 text-emerald-700',
  '值得关注': 'bg-blue-100 text-blue-700',
  '一般':     'bg-amber-100 text-amber-700',
  '不推荐':   'bg-red-100 text-red-700',
}

const scoreColor = (score: number) => {
  if (score >= 8) return 'text-emerald-600'
  if (score >= 6) return 'text-blue-600'
  if (score >= 4) return 'text-amber-600'
  return 'text-red-500'
}

const firstPhoto = (photos: string) => {
  if (!photos) return ''
  return photos.split('|').find((u: string) => u.startsWith('http')) || ''
}

const allPhotos = (photos: string) => {
  if (!photos) return []
  return photos.split('|').filter((u: string) => u.startsWith('http'))
}

const selectedPhotoIndex = ref(0)

watch(selectedItem, () => { selectedPhotoIndex.value = 0 })

const formatPrice = (item: any) => {
  const num = item.price_num || ''
  const unit = item.price_unit || ''
  return num ? `${num} ${unit}` : '-'
}

onMounted(async () => {
  await fetchFilters()
  await fetchData()
})
</script>

<template>
  <div class="h-full flex flex-col overflow-hidden bg-background">
    <!-- ════════════════ 顶部搜索区 ════════════════ -->
    <div class="flex-shrink-0 border-b border-outline-variant bg-surface-container-lowest px-4 py-ax-sm">
      <!-- 标题行 -->
      <div class="flex items-center justify-between mb-ax-sm">
        <div class="flex items-center gap-ax-sm">
          <span class="material-symbols-outlined text-primary text-xl">storefront</span>
          <span class="text-base font-semibold">生意转让 AI 评估</span>
          <span v-if="total" class="text-xs text-secondary">共 {{ total }} 条</span>
        </div>
        <div class="flex items-center gap-ax-xs">
          <AxButton variant="ghost" size="lg" icon="refresh" @click="fetchData" :loading="loading" />
          <AxButton variant="ghost" size="lg" icon="filter_alt_off" @click="resetFilters">重置</AxButton>
        </div>
      </div>

      <!-- 筛选区 -->
      <div class="flex items-center gap-ax-xs flex-wrap">
        <!-- 评级按钮组 -->
        <span class="text-xs text-secondary flex-shrink-0">评级</span>
        <div class="flex gap-0.5">
          <AxButton
            v-for="level in filterOptions.levels"
            :key="level"
            variant="ghost"
            size="lg"
            :class="selectedLevels.includes(level)
              ? '!bg-primary/10 !text-primary !font-semibold'
              : 'text-secondary'"
            @click="toggleLevel(level)"
          >
            {{ level }}
          </AxButton>
        </div>

        <!-- 区域下拉 -->
        <span class="text-xs text-secondary flex-shrink-0 ml-ax-sm">区域</span>
        <AxSelect
          v-model="district"
          :options="districtOptions"
          placeholder="全部区域"
          size="lg"
          trigger-width="140px"
        />

        <!-- 经营状态 -->
        <span class="text-xs text-secondary flex-shrink-0 ml-ax-sm">状态</span>
        <AxSelect
          v-model="bizStatus"
          :options="bizStatusOptions"
          placeholder="经营状态"
          size="lg"
          trigger-width="130px"
        />

        <!-- 经营类型 -->
        <span class="text-xs text-secondary flex-shrink-0 ml-ax-sm">类型</span>
        <AxSelect
          v-model="bizType"
          :options="bizTypeOptions"
          placeholder="经营类型"
          size="lg"
          trigger-width="140px"
        />

        <!-- 搜索输入 -->
        <div class="ml-2 w-52">
          <AxInput
            v-model="search"
            placeholder="搜索标题、地址、描述..."
            size="lg"
            @keyup.enter="onSearch"
          >
            <template #prefix>
              <span class="material-symbols-outlined text-[16px] text-secondary">search</span>
            </template>
          </AxInput>
        </div>

        <!-- 评分范围 -->
        <span class="text-xs text-secondary flex-shrink-0">评分</span>
        <AxInput
          v-model="scoreMin"
          placeholder="最低"
          size="lg"
          class="!w-20"
        />
        <span class="text-xs text-secondary">-</span>
        <AxInput
          v-model="scoreMax"
          placeholder="最高"
          size="lg"
          class="!w-20"
        />
        <!-- 搜索按钮 -->
        <AxButton variant="primary" size="lg" icon="search" @click="onSearch" :loading="loading">
          搜索
        </AxButton>
      </div>
    </div>

    <!-- ════════════════ 中间内容区：左右分栏 ════════════════ -->
    <div class="flex-1 flex overflow-hidden min-h-0">
      <!-- ── 左侧 Grid 2 卡片列表 ── -->
      <div class="flex-1 overflow-y-auto p-ax-md">
        <!-- 加载中 -->
        <div v-if="loading && !items.length" class="h-full flex items-center justify-center">
          <span class="text-secondary text-sm">
            <span class="material-symbols-outlined align-middle animate-spin mr-1">progress_activity</span>
            加载中...
          </span>
        </div>

        <!-- 空状态 -->
        <div v-else-if="!items.length" class="h-full flex items-center justify-center">
          <div class="text-center space-y-ax-sm">
            <span class="material-symbols-outlined text-4xl text-secondary">inventory_2</span>
            <p class="text-sm text-secondary">暂无数据</p>
          </div>
        </div>

        <!-- Grid 2 卡片 -->
        <div v-else class="grid grid-cols-2 gap-ax-sm">
          <div
            v-for="item in items"
            :key="item.info_id"
            class="bg-surface-container-lowest border rounded-xl p-ax-sm cursor-pointer transition-all hover:shadow-md hover:border-primary/30"
            :class="selectedItem?.info_id === item.info_id
              ? 'border-primary ring-1 ring-primary/20'
              : 'border-outline-variant'"
            @click="selectItem(item)"
          >
            <!-- 图片 + 评分 -->
            <div class="flex gap-ax-xs mb-ax-xs">
              <div class="w-20 h-20 flex-shrink-0 rounded-lg overflow-hidden bg-surface-container-high">
                <img
                  v-if="firstPhoto(item.photos)"
                  :src="`/api/images/proxy?url=${encodeURIComponent(firstPhoto(item.photos))}`"
                  class="w-full h-full object-cover"
                  loading="lazy"
                />
                <div v-else class="w-full h-full flex items-center justify-center">
                  <span class="material-symbols-outlined text-2xl text-secondary">image_not_supported</span>
                </div>
              </div>

              <div class="flex-1 min-w-0 flex flex-col justify-between">
                <div>
                  <div class="text-sm font-medium leading-tight line-clamp-2" :title="item.title">
                    {{ item.title || '无标题' }}
                  </div>
                  <div class="text-xs text-secondary mt-0.5">
                    {{ [item.district, item.block].filter(Boolean).join(' ') || '未知位置' }}
                  </div>
                </div>

                <div class="flex items-center justify-between mt-ax-xs">
                  <span class="text-sm font-semibold text-primary">{{ formatPrice(item) }}</span>
                  <span v-if="item.ai?.level" class="text-[10px] px-1.5 py-0.5 rounded-full font-medium" :class="levelColors[item.ai.level] || 'bg-gray-100 text-gray-600'">
                    {{ item.ai.level }} {{ item.ai?.score }}
                  </span>
                </div>
              </div>
            </div>

            <!-- 标签行 -->
            <div class="flex items-center gap-ax-xs text-[10px] text-secondary flex-wrap">
              <span v-if="item.area" class="px-1 py-0.5 bg-surface-container-high rounded">{{ item.area }}</span>
              <span v-if="item.property_type" class="px-1 py-0.5 bg-surface-container-high rounded">{{ item.property_type }}</span>
              <span v-if="item.biz_status" class="px-1 py-0.5 bg-surface-container-high rounded">{{ item.biz_status }}</span>
              <span v-if="item.biz_type" class="px-1 py-0.5 bg-surface-container-high rounded">{{ item.biz_type }}</span>
              <span v-if="!item.ai" class="px-1 py-0.5 bg-amber-50 text-amber-600 rounded">
                <span class="material-symbols-outlined text-[12px] align-text-bottom">pending</span>
                待评估
              </span>
              <span v-else-if="item.ai_status !== 'done'" class="px-1 py-0.5 bg-blue-50 text-blue-600 rounded">
                <span class="material-symbols-outlined text-[12px] align-text-bottom">hourglass_top</span>
                {{ item.ai_status === 'running' ? '评估中' : item.ai_status }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- ── 右侧详情面板 ── -->
      <div v-if="selectedItem"
        class="w-1/2 flex-shrink-0 border-l border-outline-variant bg-surface-container-lowest overflow-y-auto flex flex-col">
        <!-- 标题栏 -->
        <div class="flex-shrink-0 flex items-center justify-between px-4 py-ax-sm border-b border-outline-variant">
          <span class="text-sm font-semibold">详情</span>
          <AxButton variant="ghost" size="icon" icon="close" @click="selectedItem = null" />
        </div>

        <div class="flex-1 overflow-y-auto p-4 space-y-ax-md">
          <!-- ── 图片轮播 ── -->
          <div v-if="allPhotos(selectedItem.photos).length" class="space-y-ax-xs">
            <div class="flex items-center justify-between">
              <span class="text-xs text-secondary uppercase tracking-wide">房源图片</span>
              <span class="text-[10px] text-secondary">{{ selectedPhotoIndex + 1 }} / {{ allPhotos(selectedItem.photos).length }}</span>
            </div>
            <div class="relative aspect-[4/3] rounded-lg overflow-hidden bg-surface-container-high">
              <img
                :src="`/api/images/proxy?url=${encodeURIComponent(allPhotos(selectedItem.photos)[selectedPhotoIndex])}`"
                class="w-full h-full object-contain"
                loading="lazy"
              />
              <div class="absolute inset-x-0 bottom-2 flex justify-center gap-ax-xs">
                <button
                  v-for="(_, i) in allPhotos(selectedItem.photos)"
                  :key="i"
                  class="w-2 h-2 rounded-full transition-all"
                  :class="i === selectedPhotoIndex ? 'bg-primary scale-110' : 'bg-white/60 hover:bg-white/80'"
                  @click="selectedPhotoIndex = i"
                />
              </div>
              <button
                v-if="allPhotos(selectedItem.photos).length > 1"
                class="absolute left-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-black/30 hover:bg-black/50 flex items-center justify-center text-white transition-colors"
                @click="selectedPhotoIndex = (selectedPhotoIndex - 1 + allPhotos(selectedItem.photos).length) % allPhotos(selectedItem.photos).length"
              >
                <span class="material-symbols-outlined text-[18px]">chevron_left</span>
              </button>
              <button
                v-if="allPhotos(selectedItem.photos).length > 1"
                class="absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-black/30 hover:bg-black/50 flex items-center justify-center text-white transition-colors"
                @click="selectedPhotoIndex = (selectedPhotoIndex + 1) % allPhotos(selectedItem.photos).length"
              >
                <span class="material-symbols-outlined text-[18px]">chevron_right</span>
              </button>
            </div>
            <!-- 缩略图条 -->
            <div v-if="allPhotos(selectedItem.photos).length > 1" class="flex gap-ax-xs overflow-x-auto">
              <div
                v-for="(photo, i) in allPhotos(selectedItem.photos)"
                :key="i"
                class="w-14 h-14 flex-shrink-0 rounded-md overflow-hidden cursor-pointer border-2 transition-colors"
                :class="i === selectedPhotoIndex ? 'border-primary' : 'border-transparent hover:border-outline-secondary'"
                @click="selectedPhotoIndex = i"
              >
                <img
                  :src="`/api/images/proxy?url=${encodeURIComponent(photo)}`"
                  class="w-full h-full object-cover"
                  loading="lazy"
                />
              </div>
            </div>
          </div>
          <!-- 基本信息 -->
          <div>
            <div class="text-xs text-secondary mb-ax-xs uppercase tracking-wide">基本信息</div>
            <div class="space-y-ax-xs">
              <div class="flex justify-between text-sm">
                <span class="text-secondary">标题</span>
                <span class="text-right max-w-[260px]">{{ selectedItem.title || '-' }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-secondary">月租</span>
                <span class="font-semibold text-primary">{{ formatPrice(selectedItem) }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-secondary">转让费</span>
                <span>{{ selectedItem.transfer_fee || '-' }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-secondary">面积</span>
                <span>{{ selectedItem.area || '-' }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-secondary">区域</span>
                <span>{{ [selectedItem.district, selectedItem.block, selectedItem.address].filter(Boolean).join(' ') || '-' }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-secondary">楼层</span>
                <span>{{ selectedItem.floor || '-' }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-secondary">商铺类型</span>
                <span>{{ [selectedItem.property_type, selectedItem.property_nature].filter(Boolean).join(' / ') || '-' }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-secondary">经营状态</span>
                <span>{{ [selectedItem.biz_status, selectedItem.biz_type].filter(Boolean).join(' / ') || '-' }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-secondary">剩余租期</span>
                <span>{{ selectedItem.remaining_lease || '-' }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-secondary">转让类型</span>
                <span>{{ selectedItem.transfer_type || '-' }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-secondary">支付方式</span>
                <span>{{ selectedItem.payment_method || '-' }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-secondary">发帖人</span>
                <span class="text-right max-w-[260px]">{{ [selectedItem.poster_name, selectedItem.poster_company].filter(Boolean).join(' / ') || '-' }}</span>
              </div>
              <div v-if="selectedItem.tags" class="text-sm">
                <span class="text-secondary">标签</span>
                <div class="flex gap-ax-xs mt-ax-xs flex-wrap">
                  <span
                    v-for="tag in selectedItem.tags.split('/')"
                    :key="tag"
                    class="px-1.5 py-0.5 text-[10px] bg-surface-container-high rounded text-secondary"
                  >{{ tag }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 描述 -->
          <div v-if="selectedItem.description">
            <div class="text-xs text-secondary mb-ax-xs uppercase tracking-wide">房源描述</div>
            <p class="text-sm text-secondary leading-relaxed">{{ selectedItem.description }}</p>
          </div>

          <div v-if="selectedItem.surroundings">
            <div class="text-xs text-secondary mb-ax-xs uppercase tracking-wide">周边客流</div>
            <p class="text-sm text-secondary leading-relaxed">{{ selectedItem.surroundings }}</p>
          </div>

          <div v-if="selectedItem.suitable_biz">
            <div class="text-xs text-secondary mb-ax-xs uppercase tracking-wide">适合行业</div>
            <p class="text-sm text-secondary leading-relaxed">{{ selectedItem.suitable_biz }}</p>
          </div>

          <!-- 配套设施 -->
          <div v-if="selectedItem.facilities">
            <div class="text-xs text-secondary mb-ax-xs uppercase tracking-wide">配套设施</div>
            <div class="flex gap-ax-xs flex-wrap">
              <span
                v-for="f in selectedItem.facilities.split('|')"
                :key="f"
                class="text-[10px] px-1.5 py-0.5 rounded"
                :class="f.includes(':有') ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-400'"
              >{{ f.replace(/:.*$/, '') }}</span>
            </div>
          </div>

          <!-- ════════ AI 评估 ════════ -->
          <div v-if="selectedItem.ai"
            class="border-t border-outline-variant pt-ax-md"
          >
            <div class="text-xs text-secondary mb-ax-sm uppercase tracking-wide">AI 评估</div>

            <!-- 总分 + 评级 -->
            <div class="flex items-center justify-between mb-ax-sm">
              <div class="flex items-baseline gap-ax-xs">
                <span class="text-2xl font-bold" :class="scoreColor(selectedItem.ai.score)">
                  {{ selectedItem.ai.score }}
                </span>
                <span class="text-xs text-secondary">/10</span>
              </div>
              <span
                class="text-sm px-2 py-0.5 rounded-full font-medium"
                :class="levelColors[selectedItem.ai.level] || 'bg-gray-100 text-gray-600'"
              >
                {{ selectedItem.ai.level }}
              </span>
              <span v-if="selectedItem.ai_finished_at" class="text-[10px] text-secondary">
                {{ selectedItem.ai_finished_at }}
              </span>
            </div>

            <!-- 一句话总结 -->
            <div v-if="selectedItem.ai.summary" class="text-sm text-secondary mb-ax-sm leading-relaxed">
              {{ selectedItem.ai.summary }}
            </div>

            <!-- 维度详评 -->
            <div v-if="selectedItem.ai.details" class="space-y-ax-xs mb-ax-sm">
              <div v-if="selectedItem.ai.details.scale" class="text-sm">
                <span class="text-secondary text-xs">铺面规模：</span>
                <span>{{ selectedItem.ai.details.scale }}</span>
              </div>
              <div v-if="selectedItem.ai.details.equipment" class="text-sm">
                <span class="text-secondary text-xs">设备状况：</span>
                <span>{{ selectedItem.ai.details.equipment }}</span>
              </div>
              <div v-if="selectedItem.ai.details.category" class="text-sm">
                <span class="text-secondary text-xs">经营品类：</span>
                <span>{{ selectedItem.ai.details.category }}</span>
              </div>
              <div v-if="selectedItem.ai.details.reliability" class="text-sm">
                <span class="text-secondary text-xs">信息可靠性：</span>
                <span>{{ selectedItem.ai.details.reliability }}</span>
              </div>
              <div v-if="selectedItem.ai.details.intent" class="text-sm">
                <span class="text-secondary text-xs">转让诚意：</span>
                <span>{{ selectedItem.ai.details.intent }}</span>
              </div>
            </div>

            <!-- 收购建议 -->
            <div v-if="selectedItem.ai.advice"
              class="p-ax-sm rounded-lg bg-surface-container-high border border-outline-variant text-sm leading-relaxed"
            >
              <div class="text-xs text-secondary mb-ax-xs font-medium">收购建议</div>
              {{ selectedItem.ai.advice }}
            </div>

            <!-- AI 任务元信息 -->
            <div class="mt-ax-sm text-[10px] text-secondary flex items-center gap-ax-xs">
              <span v-if="selectedItem.ai_status === 'done'" class="text-emerald-600">✓ 评估完成</span>
              <span v-else-if="selectedItem.ai_status === 'running'" class="text-blue-600">⟳ 评估中</span>
              <span v-else-if="selectedItem.ai_error" class="text-red-500">✗ 失败</span>
              <span v-if="selectedItem.ai_task_id">任务 #{{ selectedItem.ai_task_id }}</span>
            </div>
          </div>

          <!-- 无 AI 评估 -->
          <div v-else class="border-t border-outline-variant pt-ax-md">
            <div class="text-xs text-secondary mb-ax-sm uppercase tracking-wide">AI 评估</div>
            <div class="flex items-center gap-ax-sm text-sm text-secondary p-ax-sm rounded-lg bg-surface-container-high">
              <span class="material-symbols-outlined">hourglass_empty</span>
              <span>尚未评估，等待 Workflow 处理</span>
            </div>
          </div>

          <!-- 原始链接 -->
          <div v-if="selectedItem.url" class="text-xs">
            <a :href="selectedItem.url" target="_blank" rel="noopener"
              class="flex items-center gap-ax-xs text-primary hover:underline">
              <span class="material-symbols-outlined text-[14px]">open_in_new</span>
              查看 58 原始页面
            </a>
          </div>
        </div>
      </div>

      <!-- 未选择时的占位 -->
      <div v-else
        class="w-1/2 flex-shrink-0 border-l border-outline-variant bg-surface-container-lowest flex items-center justify-center">
        <div class="text-center space-y-ax-sm text-secondary">
          <span class="material-symbols-outlined text-4xl">touch_app</span>
          <p class="text-sm">点击左侧卡片查看详情</p>
        </div>
      </div>
    </div>

    <!-- ════════════════ 底部分页 ════════════════ -->
    <div v-if="total > 0"
      class="flex-shrink-0 border-t border-outline-variant bg-surface-container-lowest px-4 py-ax-sm">
      <AxPagination
        :page="page"
        :size="size"
        :total="total"
        :sizes="[12, 20, 36, 60]"
        @update:page="onPageChange"
        @update:size="onSizeChange"
      />
    </div>
  </div>
</template>

<style scoped>
.animate-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
