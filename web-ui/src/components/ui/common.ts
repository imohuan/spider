import type { ControlSize, RoundedSize } from './types'

/**
 * 圆角样式映射（Tailwind v4 token，对应 @theme 中的 --radius-*）。
 */
export const ROUNDED_CLASSES: Record<RoundedSize, string> = {
  none: 'rounded-none',
  xs: 'rounded-sm',
  sm: 'rounded-md',
  md: 'rounded-lg',
  lg: 'rounded-xl',
  xl: 'rounded-2xl',
  full: 'rounded-full',
}

/**
 * 通用控件尺寸样式映射（高度 + padding + 字号）。
 * 用于 AxButton / AxInput / AxSelect 等控件。
 */
export const CONTROL_SIZE_CLASSES: Record<ControlSize, string> = {
  xs: 'h-[18px] px-1.5 text-body-sm gap-0.5',
  sm: 'h-5 px-2 text-body-sm gap-1',
  md: 'h-6 px-2.5 text-label-md gap-1',
  lg: 'h-7 px-3 text-label-md gap-1',
  xl: 'h-8 px-3.5 text-label-md gap-1.5',
}
