<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { parsersApi } from '@/api'
import { useNotify } from '@/components/ui'
import CrawlerSettingsDialog from '@/components/CrawlerSettingsDialog.vue'

const { triggerNotify } = useNotify()
const parsers = ref<Array<{ name: string; pattern: string; table: string; fields: number; count: number }>>([])

const showTestDialog = ref(false)
const testParserName = ref('')

const fetchAll = async () => {
  try { parsers.value = await parsersApi.list() } catch {}
}

const doRescan = async () => {
  try { await parsersApi.rescan(); triggerNotify('重新扫描完成', 'success'); fetchAll() } catch {}
}

const doTest = (name: string) => {
  testParserName.value = name
  showTestDialog.value = true
}

onMounted(fetchAll)
</script>

<template>
  <div class="space-y-ax-md">
    <div class="grid grid-cols-2 gap-ax-sm">
      <div v-for="p in parsers" :key="p.name" class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="flex justify-between items-start mb-ax-xs">
          <div>
            <div class="text-sm font-medium text-primary">{{ p.name }}</div>
            <div class="text-[11px] text-secondary font-mono">{{ p.pattern }}</div>
          </div>
        </div>
        <div class="flex gap-ax-md text-[11px] text-secondary mb-ax-sm">
          <span>表: <code class="bg-surface-container-low px-1 rounded">{{ p.table }}</code></span>
          <span>字段: {{ p.fields }}</span>
          <span>已抓: {{ p.count }}</span>
        </div>
        <div class="flex gap-ax-xs">
          <AxButton variant="outline" size="lg" icon="play_arrow" @click="doTest(p.name)">测试 URL</AxButton>
        </div>
      </div>
      <div v-if="parsers.length === 0" class="col-span-2 text-center py-ax-xl text-secondary text-sm">暂无注册 Parser</div>
    </div>

    <div class="bg-surface-container-lowest border border-outline-variant border-dashed rounded-xl p-ax-md">
      <div class="text-sm font-medium text-primary mb-ax-xs">+ 注册新 Parser</div>
      <div class="text-xs text-secondary mb-ax-sm">把 .py 文件放到 parser/plugins/ 目录，点击重新扫描。</div>
      <AxButton variant="outline" size="lg" icon="search" @click="doRescan">重新扫描 plugins 目录</AxButton>
    </div>

    <CrawlerSettingsDialog v-model="showTestDialog" :parser-name="testParserName" />
  </div>
</template>
