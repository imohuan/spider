<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { AxDialog, AxButton, AxInput, AxSwitch, useNotify } from '@/components/ui'
import { cookiePresetsApi } from '@/api'

const { triggerNotify } = useNotify()
const presets = ref<any[]>([])
const dialogOpen = ref(false)
const editing = ref<{ id?: number; name: string; domain: string; cookies_json: string }>({
  name: '', domain: '', cookies_json: '',
})

async function load() {
  const res = await cookiePresetsApi.list()
  presets.value = res.data.items
}

function openAdd() {
  editing.value = { name: '', domain: '', cookies_json: '' }
  dialogOpen.value = true
}

function openEdit(p: any) {
  editing.value = { id: p.id, name: p.name, domain: p.domain, cookies_json: p.cookies_json }
  dialogOpen.value = true
}

async function save(close: () => void) {
  const { name, domain, cookies_json, id } = editing.value
  if (!name.trim() || !domain.trim()) {
    triggerNotify('名称和域名不能为空', 'warning')
    return
  }
  await cookiePresetsApi.save({ name: name.trim(), domain: domain.trim(), cookies_json, id })
  triggerNotify(id ? '已更新' : '已创建', 'success')
  close()
  load()
}

async function remove(id: number) {
  await cookiePresetsApi.delete(id)
  triggerNotify('已删除', 'success')
  load()
}

async function toggle(id: number) {
  await cookiePresetsApi.toggle(id)
  load()
}

function cookieCount(cookiesJson: string): string {
  try {
    const arr = JSON.parse(cookiesJson)
    return Array.isArray(arr) ? `${arr.length} 条 cookie` : ''
  } catch {
    return '格式异常'
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-primary">Cookie 预设</h2>
      <AxButton icon="add" @click="openAdd">添加预设</AxButton>
    </div>

    <!-- 空状态 -->
    <div v-if="!presets.length" class="text-center py-12 text-secondary text-sm">
      暂无 Cookie 预设，点击「添加预设」创建
    </div>

    <!-- 预设卡片列表 -->
    <div class="grid gap-3">
      <div
        v-for="p in presets" :key="p.id"
        class="flex items-center justify-between p-4 rounded-lg border border-outline-variant bg-surface-container-low"
      >
        <div class="flex-1 min-w-0">
          <div class="text-sm font-medium text-primary truncate">{{ p.name }}</div>
          <div class="text-xs text-secondary mt-0.5">{{ p.domain }}</div>
          <div class="text-[10px] text-secondary mt-1">{{ cookieCount(p.cookies_json) }}</div>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <AxSwitch :model-value="p.enabled" @update:model-value="toggle(p.id)" />
          <AxButton variant="ghost" size="icon" icon="edit" @click="openEdit(p)" />
          <AxButton variant="ghost" size="icon" icon="delete" @click="remove(p.id)" />
        </div>
      </div>
    </div>

    <!-- 弹窗 -->
    <AxDialog v-model="dialogOpen" :title="editing.id ? '编辑预设' : '添加预设'" icon="cookie">
      <template #default>
        <div class="space-y-3">
          <AxInput v-model="editing.name" placeholder="预设名称（如：58同城-已登录）" />
          <AxInput v-model="editing.domain" placeholder="匹配域名（如：jianyangshi.58.com）" />
          <AxInput
            v-model="editing.cookies_json"
            placeholder="EditThisCookie 导出的 JSON（粘贴到这里）"
            multiline :rows="8"
          />
          <p class="text-[10px] text-secondary">
            使用 EditThisCookie 浏览器插件 → 导出 → 复制 JSON → 粘贴到上方输入框
          </p>
        </div>
      </template>
      <template #footer="{ close }">
        <AxButton variant="outline" @click="close">取消</AxButton>
        <AxButton @click="save(close)">保存</AxButton>
      </template>
    </AxDialog>
  </div>
</template>
