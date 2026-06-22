import { computed, toRef, type Ref } from 'vue'
import type { Placement } from '@floating-ui/vue'
import {
  useFloating as _useFloating,
  autoUpdate,
  offset,
  flip,
  shift,
  arrow
} from '@floating-ui/vue'

export interface UseFloatingOptions {
  placement?: string | Ref<string>
  offset?: number | Ref<number>
  matchWidth?: boolean | Ref<boolean>
  /** 箭头元素 ref，传入后才启用 arrow middleware */
  arrowRef?: Ref<HTMLElement | null>
}

/**
 * 基于 @floating-ui/vue 的浮动定位 hook。
 * placement 支持字符串或 Ref<string>，可响应式切换方向。
 * 配合 v-if 使用：元素挂载时 autoUpdate 自动启动、卸载时自动清理。
 */
export function useFloating(
  referenceRef: Ref<HTMLElement | null>,
  floatingRef: Ref<HTMLElement | null>,
  options: UseFloatingOptions = {},
) {
  const {
    arrowRef,
  } = options

  // 响应式 matchWidth：支持 Ref<boolean> 或静态布尔值
  const matchWidthRef = options.matchWidth instanceof Object && 'value' in (options.matchWidth as any)
    ? (options.matchWidth as Ref<boolean>)
    : toRef(() => (options.matchWidth as boolean) ?? false)

  // 响应式 placement：支持 Ref<string> 或静态字符串
  const placementRef = typeof options.placement === 'string'
    ? toRef(() => options.placement as string)
    : (options.placement ?? toRef(() => 'bottom-start'))

  // 响应式 offset：支持 Ref<number> 或静态数字
  const offsetRef = options.offset instanceof Object && 'value' in (options.offset as any)
    ? (options.offset as Ref<number>)
    : toRef(() => (options.offset as number) ?? 6)

  // 响应式 middleware：placement/offset/arrowRef 变化时重建
  const middlewareRef = computed(() => {
    const arr: any[] = [
      offset(offsetRef.value),
      flip(),
      shift({ padding: 5 }),
      // autoPlacement()
    ]
    if (arrowRef?.value) {
      arr.push(arrow({ element: arrowRef }))
    }
    return arr
  })

  const {
    floatingStyles,
    update,
    isPositioned,
    middlewareData,
    placement: finalPlacement,
  } = _useFloating(
    referenceRef,
    floatingRef,
    {
      placement: placementRef as Ref<Placement>,
      strategy: 'fixed',
      // 用 left/top 定位而非 transform:translate，避免与 Transition 的 scale 动画冲突
      transform: false,
      middleware: middlewareRef,
      // v-if 挂载时自动开始监听，卸载时自动清理
      whileElementsMounted: autoUpdate,
    },
  )

  // 合并 matchWidth：浮动元素宽度匹配参考元素宽度
  const mergedStyles = computed(() => {
    const base = { ...floatingStyles.value }
    if (matchWidthRef.value && referenceRef.value) {
      ;(base as any).width = `${referenceRef.value.getBoundingClientRect().width}px`
    }
    return base
  })

  return {
    floatingStyles: mergedStyles,
    updatePosition: update,
    /** 位置首次计算完成后变为 true，配合 visibility 防闪现 */
    isPositioned,
    /** arrow middleware 数据，用于定位箭头 */
    middlewareData,
    /** flip 后的最终 placement，用于计算箭头静态边 */
    placement: finalPlacement,
  }
}
