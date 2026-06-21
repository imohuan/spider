<script setup lang="ts">
import { ref, watch, nextTick, onBeforeUnmount, onMounted } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue?: boolean
    title?: string
    icon?: string
    maxWidth?: string
    closeOnOverlay?: boolean
    bodyClass?: string
  }>(),
  {
    modelValue: false,
    title: '',
    icon: '',
    maxWidth: 'max-w-xl',
    closeOnOverlay: true,
    bodyClass: '',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  close: []
}>()

const dialogRef = ref<HTMLElement | null>(null)
const closeBtnRef = ref<HTMLButtonElement | null>(null)
const triggerElement = ref<HTMLElement | null>(null)
const focusableRefs = ref<HTMLElement[]>([])

const registerFocusable = (el: HTMLElement) => {
  if (el && !focusableRefs.value.includes(el)) {
    focusableRefs.value.push(el)
  }
}

const open = () => {
  triggerElement.value = document.activeElement as HTMLElement | null
  emit('update:modelValue', true)
  document.body.style.overflow = 'hidden'
  nextTick(() => {
    const first = focusableRefs.value.find((el) => el)
    if (first) first.focus()
  })
}

const close = () => {
  emit('update:modelValue', false)
  emit('close')
  document.body.style.overflow = ''
  nextTick(() => {
    if (triggerElement.value) triggerElement.value.focus()
  })
}

watch(
  () => props.modelValue,
  (val) => {
    if (val) {
      triggerElement.value = document.activeElement as HTMLElement | null
      document.body.style.overflow = 'hidden'
      nextTick(() => {
        const first = focusableRefs.value.find((el) => el)
        if (first) first.focus()
      })
    } else {
      document.body.style.overflow = ''
    }
  },
)

onMounted(() => {
  if (closeBtnRef.value) registerFocusable(closeBtnRef.value)
})

onBeforeUnmount(() => {
  document.body.style.overflow = ''
})

const handleOverlayClick = () => {
  if (props.closeOnOverlay) close()
}

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Tab') {
    const elements = focusableRefs.value.filter((el) => el)
    if (elements.length === 0) return

    const first = elements[0]
    const last = elements[elements.length - 1]

    if (e.shiftKey) {
      if (document.activeElement === first) {
        last.focus()
        e.preventDefault()
      }
    } else if (document.activeElement === last) {
      first.focus()
      e.preventDefault()
    }
  }
}

const setFocusableRef = (el: HTMLElement | null) => {
  if (el) registerFocusable(el)
}

defineExpose({ open, close, setFocusableRef, dialogRef })
</script>

<template>
  <Transition
    enter-active-class="transition duration-300 ease-out"
    enter-from-class="opacity-0"
    enter-to-class="opacity-100"
    leave-active-class="transition duration-200 ease-in"
    leave-from-class="opacity-100"
    leave-to-class="opacity-0"
  >
    <div
      v-show="modelValue"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-ax-md"
      @click.self="handleOverlayClick"
    >
      <Transition
        enter-active-class="transition duration-300 ease-out transform"
        enter-from-class="scale-95 translate-y-4"
        enter-to-class="scale-100 translate-y-0"
        leave-active-class="transition duration-200 ease-in transform"
        leave-from-class="scale-100 translate-y-0"
        leave-to-class="scale-95 translate-y-4"
      >
        <div
          v-show="modelValue"
          ref="dialogRef"
          :class="[
            'bg-surface-container-lowest border border-outline-variant rounded-xl w-full overflow-hidden flex flex-col pro-shadow max-h-[85vh]',
            maxWidth,
          ]"
          role="dialog"
          aria-modal="true"
          @keydown="handleKeyDown"
        >
          <div
            class="h-12 border-b border-outline-variant flex items-center justify-between px-ax-md shrink-0"
          >
            <div class="flex items-center gap-ax-sm min-w-0">
              <span
                v-if="icon"
                class="material-symbols-outlined text-primary font-bold shrink-0"
              >
                {{ icon }}
              </span>
              <slot name="header">
                <h3 class="font-headline-sm text-body-md font-semibold text-primary truncate">
                  {{ title }}
                </h3>
              </slot>
            </div>
            <button
              ref="closeBtnRef"
              class="w-8 h-8 flex items-center justify-center text-secondary hover:bg-surface-container-low rounded-lg transition-colors shrink-0"
              aria-label="关闭弹窗"
              @click="close"
            >
              <span class="material-symbols-outlined">close</span>
            </button>
          </div>

          <div :class="['p-ax-lg overflow-y-auto space-y-ax-lg scrollbar-hide flex-1', bodyClass]">
            <slot :close="close" :set-focusable-ref="setFocusableRef" />
          </div>

          <div
            v-if="$slots.footer"
            class="h-14 border-t border-outline-variant bg-surface-container-low flex items-center justify-end px-ax-md gap-ax-sm shrink-0"
          >
            <slot name="footer" :close="close" :set-focusable-ref="setFocusableRef" />
          </div>
        </div>
      </Transition>
    </div>
  </Transition>
</template>
