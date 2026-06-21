<script setup lang="ts">
import { computed } from 'vue'
import type { ControlSize } from './types'

const SIZE_CLASSES: Record<ControlSize, { track: string; thumb: string; translate: string }> = {
  xs: { track: 'h-[18px] w-[30px]', thumb: 'h-3 w-3', translate: 'translate-x-3.5' },
  sm: { track: 'h-5 w-[34px]', thumb: 'h-3.5 w-3.5', translate: 'translate-x-4' },
  md: { track: 'h-6 w-10', thumb: 'h-4 w-4', translate: 'translate-x-5' },
  lg: { track: 'h-7 w-11', thumb: 'h-5 w-5', translate: 'translate-x-5' },
  xl: { track: 'h-8 w-12', thumb: 'h-6 w-6', translate: 'translate-x-5' },
}

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    disabled?: boolean
    id?: string
    size?: ControlSize
  }>(),
  {
    disabled: false,
    size: 'md',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const trackClasses = computed(() => {
  const s = SIZE_CLASSES[props.size]
  return [
    'relative inline-flex flex-shrink-0 items-center rounded-full p-0.5 transition-colors duration-200 focus:outline-none focus:ring-1 focus:ring-primary',
    s.track,
    props.modelValue ? 'bg-primary' : 'bg-outline',
    props.disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
  ]
})

const thumbClasses = computed(() => {
  const s = SIZE_CLASSES[props.size]
  return [
    'pointer-events-none inline-block transform rounded-full bg-white shadow transition duration-200 ease-in-out',
    s.thumb,
    props.modelValue ? s.translate : 'translate-x-0',
  ]
})
</script>

<template>
  <button
    :id="id"
    role="switch"
    :aria-checked="modelValue"
    :disabled="disabled"
    :class="trackClasses"
    @click="emit('update:modelValue', !modelValue)"
  >
    <span :class="thumbClasses" />
  </button>
</template>
