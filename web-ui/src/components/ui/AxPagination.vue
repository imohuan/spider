<script setup lang="ts">
import { computed } from 'vue'
import AxSelect from './AxSelect.vue'
import AxInput from './AxInput.vue'
import AxButton from './AxButton.vue'

const props = withDefaults(
  defineProps<{
    page: number
    size: number
    total: number
    sizes?: number[]
  }>(),
  {
    sizes: () => [20, 50, 100],
  },
)

const emit = defineEmits<{
  'update:page': [v: number]
  'update:size': [v: number]
}>()

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.size)))

const pages = computed(() => {
  const t = totalPages.value
  const p = props.page
  const result: (number | '...')[] = []

  if (t <= 7) {
    for (let i = 1; i <= t; i++) result.push(i)
    return result
  }

  // 始终显示首页、末页 + 当前页附近
  result.push(1)
  if (p > 3) result.push('...')

  const start = Math.max(2, p - 1)
  const end = Math.min(t - 1, p + 1)
  for (let i = start; i <= end; i++) result.push(i)

  if (p < t - 2) result.push('...')
  result.push(t)

  return result
})

const sizeOptions = computed(() =>
  props.sizes.map((s) => ({ label: `${s}条/页`, value: s })),
)

const goTo = (p: number) => {
  if (p >= 1 && p <= totalPages.value && p !== props.page) {
    emit('update:page', p)
  }
}

const changeSize = (s: string | number | (string | number)[]) => {
  if (Array.isArray(s)) { s = s[0] }
  emit('update:size', Number(s))
  emit('update:page', 1)
}

const jumpInput = (e: Event) => {
  const target = e.target as HTMLInputElement
  const v = parseInt(target.value, 10)
  if (!isNaN(v)) goTo(v)
  target.value = String(props.page)
}
</script>

<template>
  <div class="flex items-center gap-ax-sm text-xs">
    <!-- 每页条数 -->
    <div class="flex items-center gap-ax-xs text-secondary">
      <span class="text-[11px]">每页</span>
      <AxSelect
        :model-value="size"
        :options="sizeOptions"
        size="sm"
        trigger-width="90px"
        @update:model-value="changeSize"
      />
    </div>

    <!-- 总数 -->
    <span class="text-secondary text-[11px] ml-ax-xs">
      共 <span class="text-primary font-medium">{{ total }}</span> 条
    </span>

    <!-- 页码 -->
    <div class="flex items-center ml-auto gap-0.5">
      <AxButton
        variant="ghost"
        size="sm"
        :disabled="page <= 1"
        @click="goTo(page - 1)"
      >
        <span class="material-symbols-outlined text-[14px]">chevron_left</span>
      </AxButton>

      <template v-for="p in pages" :key="p">
        <span v-if="p === '...'" class="px-1 text-secondary select-none">…</span>
        <AxButton
          v-else
          variant="ghost"
          size="sm"
          :class="p === page ? '!bg-primary/10 !text-primary font-semibold' : ''"
          @click="goTo(p as number)"
        >
          {{ p }}
        </AxButton>
      </template>

      <AxButton
        variant="ghost"
        size="sm"
        :disabled="page >= totalPages"
        @click="goTo(page + 1)"
      >
        <span class="material-symbols-outlined text-[14px]">chevron_right</span>
      </AxButton>
    </div>

    <!-- 跳转 -->
    <div class="flex items-center gap-ax-xs text-secondary ml-ax-sm">
      <span class="text-[11px]">跳至</span>
      <AxInput
        :model-value="String(page)"
        size="xs"
        class="!w-12"
        @change="jumpInput"
      />
      <span class="text-[11px]">页</span>
    </div>
  </div>
</template>