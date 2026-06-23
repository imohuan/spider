<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { dataApi, configApi } from '@/api'
import { useNotify } from '@/components/ui'

const { triggerNotify } = useNotify()

const sidebarCollapsed = ref(false)
const toggleSidebar = () => { sidebarCollapsed.value = !sidebarCollapsed.value }

const prompt = ref('')
const htmlTemplate = ref('')
const generating = ref(false)

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

interface Template {
  id: number
  table_name: string
  template_html: string
  template_name: string
  created_at: string
  updated_at: string
}

const templates = ref<Template[]>([])
const selectedTemplateId = ref<number | null>(null)
const selectedOriginal = ref('')

const htmlDirty = computed(() => htmlTemplate.value !== selectedOriginal.value)

const fetchTables = async () => {
  try { tables.value = await dataApi.tables() } catch { }
}

const fetchData = async () => {
  if (!selectedTable.value) return
  try {
    const r: any = await dataApi.query(selectedTable.value, { page: page.value, size: size.value })
    columns.value = r.columns
    rows.value = r.items
    total.value = r.total
  } catch { }
}

const fetchTemplates = async () => {
  if (!selectedTable.value) return
  try {
    const r: any = await configApi.getTemplates(selectedTable.value)
    templates.value = r.templates || []
  } catch { templates.value = [] }
}

const onTableChange = () => {
  page.value = 1
  htmlTemplate.value = ''
  selectedTemplateId.value = null
  selectedOriginal.value = ''
  templates.value = []
  fetchData()
  fetchTemplates()
}

const handlePageChange = (p: number) => { page.value = p; fetchData() }
const handleSizeChange = (s: number) => { size.value = s; page.value = 1; fetchData() }

const generateTemplate = async () => {
  if (!prompt.value.trim()) {
    triggerNotify('请先输入 Prompt 描述', 'error')
    return
  }
  if (!selectedTable.value) {
    triggerNotify('请先选择数据表', 'error')
    return
  }

  generating.value = true
  try {
    const res: any = await configApi.generateTemplate({
      table: selectedTable.value,
      prompt: prompt.value,
    })
    htmlTemplate.value = res.template
    selectedOriginal.value = res.template
    await fetchTemplates()
    triggerNotify('模板生成成功', 'success')
  } catch (e: any) {
    const msg = e?.error || e?.message || '生成失败'
    triggerNotify(msg, 'error')
  } finally {
    generating.value = false
  }
}

const selectTemplate = (t: Template) => {
  htmlTemplate.value = t.template_html
  selectedTemplateId.value = t.id
  selectedOriginal.value = t.template_html
}

const saveAsNew = async () => {
  if (!selectedTable.value || !htmlTemplate.value.trim()) return
  const name = prompt.value.trim().slice(0, 30) || `手动保存 - ${new Date().toLocaleTimeString()}`
  try {
    await configApi.saveTemplate({
      table_name: selectedTable.value,
      template_html: htmlTemplate.value,
      template_name: name,
    })
    selectedOriginal.value = htmlTemplate.value
    selectedTemplateId.value = null
    await fetchTemplates()
    triggerNotify('模板已保存', 'success')
  } catch (e: any) {
    triggerNotify(e?.error || '保存失败', 'error')
  }
}

const deleteTemplate = async (id: number) => {
  try {
    await configApi.deleteTemplate(id)
    if (selectedTemplateId.value === id) {
      selectedTemplateId.value = null
      selectedOriginal.value = ''
    }
    await fetchTemplates()
    triggerNotify('已删除', 'success')
  } catch (e: any) {
    triggerNotify(e?.error || '删除失败', 'error')
  }
}

const renderPreview = (html: string) => {
  const firstRow = rows.value[0]
  if (!firstRow) return html
  return html.replace(/\{\{(\w+)\}\}/g, (_, key) => {
    const val = firstRow[key]
    return val != null ? String(val) : ''
  })
}

onMounted(async () => {
  await fetchTables()
  if (tables.value.length) {
    const firstWithData = tables.value.find(t => t.rows > 0)
    selectedTable.value = firstWithData ? firstWithData.name : tables.value[0].name
    if (selectedTable.value) {
      await fetchData()
      await fetchTemplates()
    }
  }
})
</script>

<template>
  <div class="flex gap-ax-md h-full">
    <!-- 左侧 AI 配置面板（可折叠） -->
    <transition name="slide">
      <div v-if="!sidebarCollapsed"
        class="w-80 flex-shrink-0 bg-surface-container-lowest border border-outline-variant rounded-xl flex flex-col overflow-hidden">
        <div class="px-4 py-ax-sm border-b border-outline-variant">
          <span class="text-sm font-medium">AI 生成配置</span>
        </div>

        <div class="flex-1 overflow-y-auto space-y-ax-sm">
          <div class="px-4">
            <div class="pt-ax-sm text-xs text-secondary mb-1">Prompt 描述</div>
            <AxInput v-model="prompt" multiline :rows="4" size="lg" placeholder="描述你想要的 UI 样式" />
          </div>

          <div>
            <div class="px-4 text-xs text-secondary mb-1">数据表</div>
            <AxSelect v-model="selectedTable" :options="tableOptions" placeholder="选择数据表" size="lg"
              trigger-max-width="100%" class="px-4" @update:model-value="onTableChange" />
          </div>

          <div class="px-4">
            <AxButton variant="primary" size="lg" icon="auto_awesome" block :loading="generating"
              @click="generateTemplate">
              {{ generating ? '生成中...' : 'AI 生成' }}
            </AxButton>
          </div>

          <!-- 可编辑的 HTML 模板 -->
          <div class="px-4">
            <div class="flex items-center justify-between mb-1">
              <span class="text-xs text-secondary">HTML 模板（可编辑）</span>
              <AxButton v-if="htmlDirty" variant="outline" size="sm" icon="save" @click="saveAsNew">
                保存为新模板
              </AxButton>
            </div>
            <AxInput v-model="htmlTemplate" multiline :rows="8" size="lg" placeholder="编辑 HTML 模板，使用 {{字段名}} 作为占位符"
              class="text-xs font-mono" />
          </div>

          <!-- 模板缓存列表 -->
          <div v-if="templates.length" class="px-4 pb-ax-sm">
            <div class="text-xs text-secondary mb-1">
              已保存模板 ({{ templates.length }})
            </div>
            <div class="flex gap-ax-xs overflow-x-auto pb-ax-xs">
              <div v-for="t in templates" :key="t.id"
                class="relative flex-shrink-0 p-ax-xs rounded-lg border cursor-pointer transition-colors w-[160px] h-[180px] overflow-hidden" :class="selectedTemplateId === t.id
                  ? 'border-primary bg-primary/5'
                  : 'border-outline-variant hover:border-outline-secondary'" @click="selectTemplate(t)">
                <div class="overflow-hidden pr-4"
                  style="transform: scale(0.5); transform-origin: left top; width: 200%;"
                  v-html="renderPreview(t.template_html)" />
                <div class="absolute top-1 right-1 !text-3 text-text-hint hover:!text-danger">
                  <AxButton size="icon" icon="close" @click.stop="deleteTemplate(t.id)" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </transition>

    <!-- 右侧预览区 -->
    <div class="flex-1 flex flex-col min-w-0 overflow-hidden">
      <div class="flex-1 overflow-auto bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div v-if="htmlTemplate && renderedItems.length" :style="gridStyle as any">
          <div v-for="(item, i) in renderedItems" :key="i" v-html="item.html" />
        </div>
        <div v-else class="h-full flex items-center justify-center text-secondary text-sm">
          <div class="text-center space-y-ax-sm">
            <span class="material-symbols-outlined text-3xl">grid_view</span>
            <p>{{ !selectedTable ? '请选择数据表' : !htmlTemplate ? '请先输入 Prompt 并点击 AI 生成，或从下方模板列表选择' : '暂无数据' }}</p>
          </div>
        </div>
      </div>

      <!-- 底部工具栏 -->
      <div v-if="selectedTable && total > 0"
        class="mt-ax-md flex-shrink-0 bg-surface-container-lowest border border-outline-variant rounded-xl px-4 py-ax-sm flex items-center gap-ax-sm">
        <AxButton variant="ghost" size="icon" :icon="sidebarCollapsed ? 'chevron_right' : 'chevron_left'"
          @click="toggleSidebar" />

        <span class="text-xs text-secondary">列数</span>

        <div class="flex gap-0.5">
          <AxButton v-for="n in 6" :key="n" variant="ghost" size="sm" @click="gridCols = n"
            :class="gridCols === n ? '!bg-primary/10 !text-primary !font-semibold' : ''">
            {{ n }}
          </AxButton>
        </div>

        <div class="flex-1">
          <AxPagination :page="page" :size="size" :total="total" :sizes="[12, 24, 48, 96]"
            @update:page="handlePageChange" @update:size="handleSizeChange" />
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
