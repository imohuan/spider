<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: number
    min?: number
    max?: number
    showLabels?: boolean
    labelLeft?: string
    labelRight?: string
    showValue?: boolean
    valueLabel?: string
    labelPosition?: 'top' | 'right'
  }>(),
  {
    min: 0,
    max: 100,
    showLabels: false,
    labelLeft: '',
    labelRight: '',
    showValue: false,
    valueLabel: '',
    labelPosition: 'top',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: number]
}>()

// 内部值：拖拽时实时更新，松手后同步回 props.modelValue
// - v-model 场景：emit → 父组件更新 prop → nextTick 同步到新值 → 留在新位置
// - :model-value 固定值场景：emit 被忽略 → prop 不变 → nextTick 同步回原值 → 弹回原位
const internalValue = ref(props.modelValue)
const isDragging = ref(false)

// 外部 prop 变化时同步（仅在非拖拽中）
watch(() => props.modelValue, (val) => {
  if (!isDragging.value) {
    internalValue.value = val
  }
})

const percent = computed(() => {
  const range = props.max - props.min || 1
  return ((internalValue.value - props.min) / range) * 100
})

const displayValue = computed(() => {
  if (props.valueLabel) return props.valueLabel
  return `${internalValue.value}%`
})

const onInput = (e: Event) => {
  isDragging.value = true
  const val = Number((e.target as HTMLInputElement).value)
  internalValue.value = val
  // 拖拽过程中实时触发 v-model，父组件同步感知变化
  emit('update:modelValue', val)
}

const onChange = async () => {
  isDragging.value = false
  // 等父组件响应后，用 prop 值同步回来
  // v-model → prop 已更新 → 保持新值（input 阶段已 emit）
  // :model-value → prop 未变 → 弹回原值
  await nextTick()
  internalValue.value = props.modelValue
}
</script>

<template>
  <!-- right 布局：轨道在左，标签在右 -->
  <div v-if="labelPosition === 'right' && (showLabels || showValue)" class="flex items-center gap-ax-sm w-full">
    <div class="relative flex-1 flex items-center group py-1">
      <div
        class="absolute h-1.5 w-full bg-surface-container rounded-full pointer-events-none inset-y-0 my-auto"
      />
      <div
        :style="{ width: percent + '%' }"
        class="absolute h-1.5 bg-primary rounded-full pointer-events-none inset-y-0 my-auto"
      />
      <input
        type="range"
        :value="internalValue"
        :min="min"
        :max="max"
        class="w-full h-1.5 appearance-none bg-transparent cursor-pointer outline-none focus:outline-none relative z-10"
        @input="onInput"
        @change="onChange"
      />
    </div>
    <div class="flex items-center gap-ax-xs shrink-0">
      <span v-if="showLabels" class="text-[11px] font-label-md text-secondary">{{ labelLeft }}</span>
      <span
        v-if="showValue"
        class="text-[11px] font-label-md text-primary font-bold px-1 bg-surface-container border border-outline-variant rounded tabular-nums"
      >
        {{ displayValue }}
      </span>
      <span v-if="showLabels" class="text-[11px] font-label-md text-secondary">{{ labelRight }}</span>
    </div>
  </div>

  <!-- top 布局：标签在上，轨道在下 -->
  <div v-else class="relative w-full">
    <div
      v-if="showLabels || showValue"
      :class="[
        'text-[11px] font-label-md text-secondary mb-1',
        showLabels ? 'flex justify-between' : 'flex justify-end',
      ]"
    >
      <span v-if="showLabels">{{ labelLeft }}</span>
      <span
        v-if="showValue"
        class="text-primary font-bold px-1 bg-surface-container border border-outline-variant rounded"
      >
        {{ displayValue }}
      </span>
      <span v-if="showLabels">{{ labelRight }}</span>
    </div>
    <div class="relative flex items-center group py-2">
      <div
        class="absolute h-1.5 w-full bg-surface-container rounded-full pointer-events-none inset-y-0 my-auto"
      />
      <div
        :style="{ width: percent + '%' }"
        class="absolute h-1.5 bg-primary rounded-full pointer-events-none inset-y-0 my-auto"
      />
      <input
        type="range"
        :value="internalValue"
        :min="min"
        :max="max"
        class="w-full h-1.5 appearance-none bg-transparent cursor-pointer outline-none focus:outline-none relative z-10"
        @input="onInput"
        @change="onChange"
      />
    </div>
  </div>
</template>
