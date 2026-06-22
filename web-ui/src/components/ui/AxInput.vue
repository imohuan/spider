<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import type { InputSize, RoundedSize } from './types'
import { ROUNDED_CLASSES, CONTROL_SIZE_CLASSES } from './common'

const SIZE_CLASSES = CONTROL_SIZE_CLASSES as Record<InputSize, string>

const ICON_SIZE_CLASSES: Record<InputSize, string> = {
  xs: '!text-[12px]',
  sm: '!text-[14px]',
  md: '!text-[16px]',
  lg: '!text-[18px]',
  xl: '!text-[20px]',
}

/** textarea 模式只用 padding + font，不定高 */
const TEXTAREA_SIZE_CLASSES: Record<InputSize, string> = {
  xs: 'px-1.5 py-px text-body-sm',
  sm: 'px-2 py-0.5 text-body-sm',
  md: 'px-2.5 py-1 text-label-md',
  lg: 'px-3 py-1.5 text-label-md',
  xl: 'px-3.5 py-2 text-label-md',
}

const RESIZE_CLASSES: Record<string, string> = {
  none: 'resize-none',
  vertical: 'resize-y',
  horizontal: 'resize-x',
  both: 'resize',
}

const props = withDefaults(
  defineProps<{
    modelValue?: string | number
    type?: string
    placeholder?: string
    disabled?: boolean
    size?: InputSize
    rounded?: RoundedSize
    password?: boolean
    /** 密码框默认 new-password；登录场景可传 current-password */
    autocomplete?: string
    /** 多行文本模式（textarea） */
    multiline?: boolean
    /** textarea 行数 */
    rows?: number
    /** textarea resize 行为：none | vertical | horizontal | both */
    resize?: 'none' | 'vertical' | 'horizontal' | 'both'
  }>(),
  {
    modelValue: '',
    type: 'text',
    placeholder: '',
    disabled: false,
    size: 'md',
    rounded: 'md',
    password: false,
    autocomplete: undefined,
    multiline: false,
    rows: 3,
    resize: 'vertical',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  keydown: [event: KeyboardEvent]
  blur: [event: FocusEvent]
  focus: [event: FocusEvent]
}>()

const inputRef = ref<HTMLInputElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const passwordVisible = ref(false)

const resolvedType = computed(() => {
  if (props.password) return passwordVisible.value ? 'text' : 'password'
  return props.type
})

const resolvedAutocomplete = computed(() => {
  if (props.autocomplete != null && props.autocomplete !== '') return props.autocomplete
  if (props.password) return 'new-password'
  // 避免与同表单密码框混排时 Chrome 误判为登录表单并刷 DOM 警告
  return 'off'
})

const inputClasses = computed(() => [
  'w-full font-label-md bg-surface-container-low border border-outline-variant',
  ROUNDED_CLASSES[props.rounded],
  'focus:ring-1 focus:ring-primary focus:border-primary placeholder:text-outline',
  'transition-all',
  'disabled:opacity-50 disabled:cursor-not-allowed',
  SIZE_CLASSES[props.size],
])

const textareaClasses = computed(() => [
  'w-full font-label-md bg-surface-container-low border border-outline-variant',
  ROUNDED_CLASSES[props.rounded],
  'focus:ring-1 focus:ring-primary focus:border-primary placeholder:text-outline',
  'transition-all',
  'disabled:opacity-50 disabled:cursor-not-allowed',
  TEXTAREA_SIZE_CLASSES[props.size],
  RESIZE_CLASSES[props.resize],
])

const onInput = (e: Event) => {
  emit('update:modelValue', (e.target as HTMLInputElement).value)
}

const onTextareaInput = (e: Event) => {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
}

const togglePassword = () => {
  const input = inputRef.value
  // 切换 type 属性会重置光标，先保存位置再恢复
  const savedStart = input?.selectionStart ?? null
  const savedEnd = input?.selectionEnd ?? null
  passwordVisible.value = !passwordVisible.value
  nextTick(() => {
    input?.focus()
    if (savedStart !== null) {
      input?.setSelectionRange(savedStart, savedEnd ?? savedStart)
    }
  })
}

const focus = () => {
  if (props.multiline) {
    textareaRef.value?.focus()
  } else {
    inputRef.value?.focus()
  }
}

defineExpose({ focus, inputRef, textareaRef })
</script>

<template>
  <!-- textarea 多行模式 -->
  <textarea
    v-if="multiline"
    ref="textareaRef"
    :value="modelValue"
    :placeholder="placeholder"
    :disabled="disabled"
    :rows="rows"
    :class="textareaClasses"
    @input="onTextareaInput"
    @keydown="emit('keydown', $event)"
    @blur="emit('blur', $event)"
    @focus="emit('focus', $event)"
  />

  <!-- 单行 input 模式 -->
  <div v-else class="relative flex items-center w-full">
    <div
      v-if="$slots.prefix"
      class="absolute left-2.5 flex items-center text-secondary pointer-events-none z-10"
    >
      <slot name="prefix" />
    </div>
    <input
      ref="inputRef"
      :type="resolvedType"
      :value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      :autocomplete="resolvedAutocomplete"
      :class="[inputClasses, $slots.prefix ? 'pl-8' : '', ($slots.suffix || password) ? 'pr-8' : '']"
      @input="onInput"
      @keydown="emit('keydown', $event)"
      @blur="emit('blur', $event)"
      @focus="emit('focus', $event)"
    />
    <!-- suffix slot (hidden when password mode is on) -->
    <div
      v-if="$slots.suffix && !password"
      class="absolute right-2.5 flex items-center text-secondary z-10"
    >
      <slot name="suffix" />
    </div>
    <!-- password visibility toggle -->
    <button
      v-if="password"
      type="button"
      class="absolute right-2.5 flex items-center text-secondary hover:text-primary z-10 cursor-pointer transition-colors"
      :disabled="disabled"
      tabindex="-1"
      @click="togglePassword"
    >
      <span class="material-symbols-outlined" :class="ICON_SIZE_CLASSES[size]">
        {{ passwordVisible ? 'visibility' : 'visibility_off' }}
      </span>
    </button>
  </div>
</template>
