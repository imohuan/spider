<script setup lang="ts">
import { ref, computed } from 'vue'
import { useFloating } from './hooks/useFloating'
import { useTeleportTarget } from './hooks/useTeleportTarget'

const props = withDefaults(
  defineProps<{
    content?: string
    placement?: string
    offset?: number
    arrow?: boolean
  }>(),
  {
    content: '',
    placement: 'top',
    offset: 8,
    arrow: true,
  },
)

const teleportTarget = useTeleportTarget()
const triggerRef = ref<HTMLElement | null>(null)
const tooltipRef = ref<HTMLElement | null>(null)
const arrowRef = ref<HTMLElement | null>(null)
const visible = ref(false)

const { floatingStyles, isPositioned, middlewareData, placement } = useFloating(
  triggerRef,
  tooltipRef,
  {
    // 使用 computed ref 保证 placement/offset 变化时重新定位
    placement: computed(() => props.placement),
    offset: computed(() => props.offset),
    // 仅当 arrow 启用时才传 arrowRef
    arrowRef: props.arrow ? arrowRef : undefined,
  },
)

// 防闪：位置就绪前放在视口外
const tooltipStyle = computed(() =>
  isPositioned.value
    ? floatingStyles.value
    : { position: 'fixed' as const, left: '-9999px', top: '-9999px' },
)

// 箭头定位：动态轴由 middlewareData.arrow 提供（x 或 y 之一）
// 静态轴由 placement 决定（箭头在 tooltip 的哪一边）
const staticSideMap: Record<string, string> = {
  top: 'bottom',
  bottom: 'top',
  left: 'right',
  right: 'left',
}

const ARROW_HALF = 5 // 10px 方块旋转 45° 后视觉突出约为 5px

const arrowStyle = computed(() => {
  const arrowData = middlewareData.value?.arrow
  const side = placement.value?.split('-')[0] ?? 'top'
  const staticSide = staticSideMap[side] ?? 'bottom'

  const style: Record<string, string> = {
    position: 'absolute',
    [staticSide]: `-${ARROW_HALF}px`,
  }

  if (arrowData) {
    if (arrowData.x != null) style.left = `${arrowData.x}px`
    if (arrowData.y != null) style.top = `${arrowData.y}px`
  }

  return style
})

const show = () => {
  visible.value = true
}

const hide = () => {
  visible.value = false
}
</script>

<template>
  <span
    ref="triggerRef"
    class="inline-flex"
    @mouseenter="show"
    @mouseleave="hide"
    @focus="show"
    @blur="hide"
  >
    <slot />
  </span>
  <Teleport :to="teleportTarget">
    <Transition
      enter-active-class="transition duration-100 ease-out"
      enter-from-class="opacity-0 scale-95"
      enter-to-class="opacity-100 scale-100"
      leave-active-class="transition duration-75 ease-in"
      leave-from-class="opacity-100 scale-100"
      leave-to-class="opacity-0 scale-95"
    >
      <div
        v-if="visible"
        ref="tooltipRef"
        :style="tooltipStyle"
        class="z-50 bg-primary text-on-primary font-body-sm text-[11px] py-1.5 px-3 rounded-lg shadow-lg pointer-events-none whitespace-nowrap pro-shadow"
      >
        <slot name="content">{{ content }}</slot>
        <div
          v-if="props.arrow"
          ref="arrowRef"
          :style="arrowStyle"
          class="w-2.5 h-2.5 bg-primary rotate-45"
        />
      </div>
    </Transition>
  </Teleport>
</template>
