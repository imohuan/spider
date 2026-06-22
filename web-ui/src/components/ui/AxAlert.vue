<script setup lang="ts">
import { computed } from 'vue'
import type { AlertType } from './types'

interface AlertConfig {
  container: string
  icon: string
  iconColor: string
  titleColor: string
  descColor: string
  closeBtn: string
}

const TYPE_CONFIG: Record<AlertType, AlertConfig> = {
  info: {
    container:
      'text-on-surface-variant bg-surface-container-lowest border border-outline-variant border-l-2 border-l-primary',
    icon: 'info',
    iconColor: 'text-primary',
    titleColor: 'text-primary',
    descColor: 'text-secondary',
    closeBtn: 'text-secondary hover:bg-surface-container-low',
  },
  error: {
    container:
      'text-on-error-container bg-error-container border border-error-container border-l-2 border-l-error',
    icon: 'error',
    iconColor: 'text-error',
    titleColor: 'text-on-error-container',
    descColor: 'text-on-error-container opacity-90',
    closeBtn: 'text-on-error-container hover:bg-error/10',
  },
  success: {
    container:
      'text-on-surface-variant bg-surface-container-lowest border border-outline-variant border-l-2 border-l-primary',
    icon: 'check_circle',
    iconColor: 'text-primary',
    titleColor: 'text-primary',
    descColor: 'text-secondary',
    closeBtn: 'text-secondary hover:bg-surface-container-low',
  },
  warning: {
    container:
      'text-on-surface-variant bg-surface-container-lowest border border-outline-variant border-l-2 border-l-primary',
    icon: 'warning',
    iconColor: 'text-primary',
    titleColor: 'text-primary',
    descColor: 'text-secondary',
    closeBtn: 'text-secondary hover:bg-surface-container-low',
  },
}

const props = withDefaults(
  defineProps<{
    type?: AlertType
    title?: string
    modelValue?: boolean
    dismissible?: boolean
  }>(),
  {
    type: 'info',
    title: '',
    modelValue: true,
    dismissible: true,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  dismiss: []
}>()

const config = computed(() => TYPE_CONFIG[props.type])

const dismiss = () => {
  emit('update:modelValue', false)
  emit('dismiss')
}
</script>

<template>
  <Transition
    leave-active-class="transition duration-200 ease-in"
    leave-from-class="opacity-100 translate-y-0"
    leave-to-class="opacity-0 -translate-y-1"
  >
    <div
      v-show="modelValue"
      :class="['flex items-start justify-between gap-ax-sm p-2.5 rounded-r-lg', config.container]"
    >
      <div class="flex items-start gap-ax-xs">
        <span :class="['material-symbols-outlined text-[16px] mt-0.5', config.iconColor]">
          {{ config.icon }}
        </span>
        <div>
          <p v-if="title" :class="['font-body-sm text-[11px] font-semibold', config.titleColor]">
            {{ title }}
          </p>
          <p :class="['text-[10px] leading-relaxed mt-0.5', config.descColor]">
            <slot />
          </p>
        </div>
      </div>
      <button
        v-if="dismissible"
        :class="[
          'w-5 h-5 flex items-center justify-center rounded transition-colors shrink-0',
          config.closeBtn,
        ]"
        @click="dismiss"
      >
        <span class="material-symbols-outlined text-[14px]">close</span>
      </button>
    </div>
  </Transition>
</template>
