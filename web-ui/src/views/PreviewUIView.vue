<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { dataApi } from '@/api'
import { useNotify } from '@/components/ui'

const { triggerNotify } = useNotify()

const sidebarCollapsed = ref(false)
const toggleSidebar = () => { sidebarCollapsed.value = !sidebarCollapsed.value }

const prompt = ref('')
const htmlTemplate = ref('')

const tables = ref<Array<{ name: string; rows: number }>>([])
const selectedTable = ref('')
const tableOptions = computed(() =>
  tables.value.map(t => ({ value: t.name, label: `${t.name} (${t.rows} 行)` })),
)

const rows = ref<any[]>([])
const columns = ref<string[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)

const gridCols = ref(3)
const gridStyle = computed(() => ({
  display: 'grid',
  gridTemplateColumns: `repeat(${gridCols.value}, minmax(0, 1fr))`,
  gap: '12px',
  alignContent: 'start',
}))

const renderedItems = computed(() =>
  rows.value.map(row => {
    const html = htmlTemplate.value.replace(/\{\{(\w+)\}\}/g, (_, key) => {
      const val = row[key]
      return val != null ? String(val) : ''
    })
    return { html, row }
  }),
)

const fetchTables = async () => {
  try { tables.value = await dataApi.tables() } catch {}
}

const fetchData = async () => {
  if (!selectedTable.value) return
  try {
    const r: any = await dataApi.query(selectedTable.value, { page: page.value, size: size.value })
    columns.value = r.columns
    rows.value = r.items
    total.value = r.total
  } catch {}
}

const onTableChange = () => {
  page.value = 1
  fetchData()
  htmlTemplate.value = ''
}

const handlePageChange = (p: number) => { page.value = p; fetchData() }
const handleSizeChange = (s: number) => { size.value = s; page.value = 1; fetchData() }

const generateTemplate = () => {
  if (!prompt.value.trim()) {
    triggerNotify('请先输入 Prompt 描述', 'error')
    return
  }
  if (!selectedTable.value || columns.value.length === 0) {
    triggerNotify('请先选择有数据的数据表', 'error')
    return
  }
  const cols = columns.value.slice(0, 8)
  const imgCol = cols.find((c: string) => /img|image|pic|photo|图片|图像/.test(c.toLowerCase()))
  const titleCol = cols.find((c: string) => /title|name|标题|名称/.test(c.toLowerCase())) || cols[0]
  const priceCol = cols.find((c: string) => /price|价格|amount/.test(c.toLowerCase()))
  const descCol = cols.find((c: string) => /desc|描述|说明|content|detail/.test(c.toLowerCase()))
  const locCol = cols.find((c: string) => /loc|city|addr|地区|地址|位置/.test(c.toLowerCase()))
  const dateCol = cols.find((c: string) => /date|time|日期|时间/.test(c.toLowerCase()))

  let t = '<div style="background:var(--color-background-primary, #fff);border-radius:8px;overflow:hidden;border:0.5px solid var(--color-border-tertiary, #e5e5e5);height:100%;">\n'
  if (imgCol) t += `  <img src="{{${imgCol}}}" style="width:100%;height:140px;object-fit:cover;background:var(--color-background-secondary, #f5f5f5);" onerror="this.style.display=\'none\'">\n`
  t += '  <div style="padding:12px;">\n'
  t += `    <h3 style="margin:0 0 6px;font-size:14px;font-weight:500;line-height:1.4;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;">{{${titleCol}}}</h3>\n`
  if (priceCol) t += `    <p style="margin:0 0 4px;color:#d85a30;font-size:16px;font-weight:600;">{{${priceCol}}}</p>\n`
  if (descCol) t += `    <p style="margin:0 0 4px;color:var(--color-text-secondary, #666);font-size:12px;line-height:1.4;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;">{{${descCol}}}</p>\n`
  if (locCol) t += `    <p style="margin:4px 0 0;color:var(--color-text-hint, #999);font-size:11px;">{{${locCol}}}</p>\n`
  if (dateCol && dateCol !== locCol) t += `    <p style="margin:2px 0 0;color:var(--color-text-hint, #999);font-size:11px;">{{${dateCol}}}</p>\n`
  t += '  </div>\n</div>'

  htmlTemplate.value = t
  triggerNotify('模板生成成功，已填充 {{字段名}} 占位符', 'success')
}

onMounted(async () => {
  await fetchTables()
  if (tables.value.length) {
    const firstWithData = tables.value.find(t => t.rows > 0)
    selectedTable.value = firstWithData ? firstWithData.name : tables.value[0].name
    if (selectedTable.value) fetchData()
  }
})
</script>

<template>
  <div class="flex gap-ax-md h-full">
    <!-- 左侧 AI 配置面板（可折叠） -->
    <transition name="slide">
      <div
        v-if="!sidebarCollapsed"
        class="w-72 flex-shrink-0 bg-surface-container-lowest border border-outline-variant rounded-xl flex flex-col overflow-hidden"
      >
        <div class="px-4 py-ax-sm border-b border-outline-variant">
          <span class="text-sm font-medium">AI 生成配置</span>
        </div>

        <div class="flex-1 overflow-y-auto space-y-ax-sm">
          <div>
            <div class="px-4 pt-ax-sm text-xs text-secondary mb-1">Prompt 描述</div>
            <AxInput
              v-model="prompt"
              multiline
              :rows="5"
              size="lg"
              placeholder="描述你想要的 UI 样式，例如：生成商品卡片列表，包含图片、标题、价格、地区"
              class="px-4"
            />
          </div>

          <div>
            <div class="px-4 text-xs text-secondary mb-1">数据表</div>
            <AxSelect
              v-model="selectedTable"
              :options="tableOptions"
              placeholder="选择数据表"
              size="lg"
              trigger-max-width="100%"
              class="px-4"
              @update:model-value="onTableChange"
            />
          </div>

          <div class="px-4">
            <AxButton
              variant="primary"
              size="lg"
              icon="auto_awesome"
              block
              @click="generateTemplate"
            >
              AI 生成
            </AxButton>
          </div>

          <div v-if="htmlTemplate" class="flex-1 min-h-0 flex flex-col">
            <div class="px-4 text-xs text-secondary mb-1">生成的 HTML</div>
            <div class="mx-4 flex-1 bg-surface-container-low border border-outline-variant rounded-lg p-ax-sm overflow-auto max-h-60">
              <pre class="text-[11px] font-mono text-secondary whitespace-pre">{{ htmlTemplate }}</pre>
            </div>
          </div>
        </div>
      </div>
    </transition>

    <!-- 右侧预览区 -->
    <div class="flex-1 flex flex-col min-w-0 overflow-hidden">
      <!-- Grid 预览内容区 -->
      <div
        class="flex-1 overflow-auto bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md"
      >
        <div v-if="htmlTemplate && renderedItems.length" :style="gridStyle as any">
          <div v-for="(item, i) in renderedItems" :key="i" v-html="item.html" />
        </div>
        <div
          v-else
          class="h-full flex items-center justify-center text-secondary text-sm"
        >
          <div class="text-center space-y-ax-sm">
            <span class="material-symbols-outlined text-3xl">grid_view</span>
            <p>{{ !selectedTable ? '请选择数据表' : !htmlTemplate ? '请先输入 Prompt 并点击 AI 生成' : '暂无数据' }}</p>
          </div>
        </div>
      </div>

      <!-- 底部工具栏：折叠 + 列数 + 分页 -->
      <div
        v-if="selectedTable && total > 0"
        class="mt-ax-md flex-shrink-0 bg-surface-container-lowest border border-outline-variant rounded-xl px-4 py-ax-sm flex items-center gap-ax-sm"
      >
        <AxButton
          variant="ghost"
          size="lg"
          :icon="sidebarCollapsed ? 'chevron_right' : 'chevron_left'"
          @click="toggleSidebar"
        />

        <span class="text-xs text-secondary">列数</span>

        <div class="flex gap-0.5">
          <AxButton
            v-for="n in 6"
            :key="n"
            variant="ghost"
            size="lg"
            @click="gridCols = n"
            :class="gridCols === n ? '!bg-primary/10 !text-primary !font-semibold' : ''"
          >
            {{ n }}
          </AxButton>
        </div>

        <div class="flex-1">
          <AxPagination
            :page="page"
            :size="size"
            :total="total"
            :sizes="[12, 24, 48, 96]"
            @update:page="handlePageChange"
            @update:size="handleSizeChange"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.slide-enter-active,
.slide-leave-active {
  transition: width 0.25s ease, opacity 0.2s ease;
}
.slide-enter-from,
.slide-leave-to {
  width: 0;
  opacity: 0;
  overflow: hidden;
}
</style>
