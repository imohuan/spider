<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { dataApi, workflowsApi } from '@/api'
import { useLinkify } from '@/components/ui'

const { linkify } = useLinkify()

const route = useRoute()
const router = useRouter()

const tables = ref<Array<{ name: string; rows: number }>>([])
const selectedTable = ref('')
const rows = ref<any[]>([])
const columns = ref<string[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)

const isWorkflowQueue = computed(() => selectedTable.value === 'workflow_queue')
const requeueingIds = ref<Set<number>>(new Set())

// 行详情弹窗
const detailOpen = ref(false)
const detailRow = ref<Record<string, any> | null>(null)

const openDetail = (row: any) => {
  detailRow.value = row
  detailOpen.value = true
}

const detailFields = computed(() => {
  if (!detailRow.value) return []
  return Object.entries(detailRow.value).map(([key, raw]) => {
    let parsed: any = raw
    if (typeof raw === 'string') {
      const trimmed = raw.trim()
      if ((trimmed.startsWith('{') || trimmed.startsWith('[')) && trimmed.length > 2) {
        try { parsed = JSON.parse(trimmed) } catch { /* keep raw */ }
      }
    }
    const isJson = parsed !== raw && (typeof parsed === 'object')
    return { key, raw, parsed, isJson }
  })
})

const tableOptions = computed(() => tables.value.map(t => ({ value: t.name, label: `${t.name} (${t.rows} 行)` })))

// 从 URL query 恢复业务表
const restoreFromQuery = () => {
  const qTable = route.query.table as string | undefined
  const qPage = parseInt(route.query.page as string, 10)
  if (qTable) selectedTable.value = qTable
  if (qPage > 0) page.value = qPage
}

const syncQuery = () => {
  const q: Record<string, string> = {}
  if (selectedTable.value) q.table = selectedTable.value
  if (page.value > 1) q.page = String(page.value)
  router.replace({ query: q })
}

const fetchTables = async () => {
  try { tables.value = await dataApi.tables() } catch {}
}

const fetchData = async () => {
  if (!selectedTable.value) return
  try {
    const r: any = await dataApi.query(selectedTable.value, { page: page.value, size: size.value })
    columns.value = r.columns; rows.value = r.items; total.value = r.total
    syncQuery()
  } catch {}
}

const onTableChange = () => { page.value = 1; fetchData() }

const handlePageChange = (p: number) => { page.value = p; fetchData() }
const handleSizeChange = (s: number) => { size.value = s; page.value = 1; fetchData() }

const exportCsv = () => {
  if (selectedTable.value) window.open(dataApi.exportUrl(selectedTable.value))
}

const handleRequeue = async (row: any) => {
  const id = row['id']
  if (!id) return
  requeueingIds.value = new Set([...requeueingIds.value, id])
  try {
    await workflowsApi.requeue(id)
    await fetchData()
  } finally {
    const next = new Set(requeueingIds.value)
    next.delete(id)
    requeueingIds.value = next
  }
}

onMounted(async () => {
  restoreFromQuery()
  await fetchTables()
  if (!selectedTable.value && tables.value.length) {
    const firstWithData = tables.value.find(t => t.rows > 0)
    selectedTable.value = firstWithData ? firstWithData.name : tables.value[0].name
  }
  if (selectedTable.value) fetchData()
})
</script>

<template>
  <div>
    <div class="space-y-ax-md relative">
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl px-4 py-ax-sm flex items-center gap-ax-sm">
        <span class="text-xs text-secondary">业务表</span>
        <AxSelect v-model="selectedTable" size="lg" :options="tableOptions" placeholder="请选择" @update:model-value="onTableChange" />
        <div class="flex-1"></div>
        <AxButton variant="outline"  size="lg" icon="download" @click="exportCsv" :disabled="!selectedTable">导出 CSV</AxButton>
      </div>

      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden">
        <div v-if="selectedTable && rows.length" class="overflow-x-auto">
          <table class="w-full text-xs">
            <thead class="bg-surface-container-low text-secondary text-[11px]">
              <tr>
                <th v-for="c in columns" :key="c" class="text-left px-4 py-2 font-medium truncate">{{ c }}</th>
                <th v-if="isWorkflowQueue" class="text-left px-4 py-2 font-medium w-20">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-outline-variant">
              <tr
                v-for="(r, i) in rows"
                :key="i"
                class="hover:bg-surface-container-low cursor-pointer"
                @click="openDetail(r)"
              >
                <td v-for="c in columns" :key="c" class="px-4 py-2 text-primary truncate max-w-[200px]" v-html="linkify(r[c])" />
                <td v-if="isWorkflowQueue" class="px-4 py-2" @click.stop>
                  <AxButton
                    size="icon"
                    variant="ghost"
                    icon="refresh"
                    :loading="requeueingIds.has(r['id'])"
                    :disabled="r['status'] === 'pending' || r['status'] === 'running'"
                    @click="handleRequeue(r)"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="p-ax-lg text-center text-secondary text-sm">
          {{ selectedTable ? '表为空' : '请选择业务表' }}
        </div>
        <div v-if="selectedTable && total > 0" class="px-4 py-ax-sm border-t border-outline-variant">
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
    </div>

    <!-- 行详情弹窗：宽 80vw，高 80vh -->
    <AxDialog
    v-model="detailOpen"
    :title="`${selectedTable} — 行详情`"
    icon="table_rows"
    max-width="max-w-[80vw]"
    body-class="!p-0 !space-y-0"
    close-on-overlay
  >
    <template #default>
      <div class="overflow-y-auto" style="height: calc(80vh - 7rem)">
        <div v-if="detailRow" class="divide-y divide-outline-variant">
          <div
            v-for="field in detailFields"
            :key="field.key"
            class="flex gap-ax-md px-ax-lg py-3"
          >
            <!-- 字段名 -->
            <div class="w-36 shrink-0 pt-0.5">
              <span class="text-[11px] font-semibold text-secondary font-mono">{{ field.key }}</span>
            </div>
            <!-- 字段值 -->
            <div class="flex-1 min-w-0 overflow-hidden">
              <!-- JSON 对象/数组 -->
              <template v-if="field.isJson">
                <div class="bg-surface-container-low rounded-lg border border-outline-variant p-ax-md">
                  <AxJsonViewer :data="field.parsed" :expand-level="1" :wrap-enabled="true" is-root />
                </div>
              </template>
              <!-- null -->
              <template v-else-if="field.raw === null || field.raw === undefined || field.raw === ''">
                <span class="text-xs text-outline italic">null</span>
              </template>
              <!-- 长文本 -->
              <template v-else-if="typeof field.raw === 'string' && field.raw.length > 60">
                <div class="bg-surface-container-low rounded-lg border border-outline-variant p-ax-sm">
                  <pre class="text-xs text-primary whitespace-pre-wrap break-all font-mono leading-relaxed">{{ field.raw }}</pre>
                </div>
              </template>
              <!-- 普通短值 -->
              <template v-else>
                <span class="text-xs text-primary break-all font-mono" v-html="linkify(String(field.raw))" />
              </template>
            </div>
          </div>
        </div>
      </div>
    </template>
    <template #footer="{ close }">
      <AxButton variant="outline" @click="close">关闭</AxButton>
    </template>
  </AxDialog>
  </div>
</template>
