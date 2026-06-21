/**
 * Ax* 组件库共享类型定义
 */

// ---- 尺寸 ----

/** 通用控件尺寸（input / select / switch 等） */
export type ControlSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl'

/** 输入框尺寸（与 ControlSize 一致） */
export type InputSize = ControlSize

/** 按钮尺寸（在 ControlSize 基础上增加 icon / icon-lg） */
export type ButtonSize = ControlSize | 'icon' | 'icon-lg'

/** 圆角档位 */
export type RoundedSize = 'none' | 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'full'

// ---- 业务类型 ----

/** 按钮视觉变体 */
export type ButtonVariant = 'primary' | 'outline' | 'ghost' | 'danger'

/** 警示框类型 */
export type AlertType = 'info' | 'success' | 'warning' | 'error'

/** 选择器选项 */
export interface SelectOption {
  label: string
  value: string | number
  disabled?: boolean
}

// ---- PropPanel ----

export type PropPanelItemType =
  | 'switch'
  | 'segmented'
  | 'select'
  | 'slider'
  | 'input'
  | 'textarea'

/** 属性面板单个 schema 项 */
export interface PropPanelSchemaItem {
  /** 对应 modelValue 的 key */
  key: string
  /** 标签文案 */
  label: string
  /** 描述文案（可选） */
  description?: string
  /** 控件类型 */
  type: PropPanelItemType
  /** select / segmented 模式的选项 */
  options?: SelectOption[]
  /** slider 最小值 */
  min?: number
  /** slider 最大值 */
  max?: number
  /** slider 步长 */
  step?: number
  /** input / textarea 占位符 */
  placeholder?: string
  /** textarea 行数 */
  rows?: number
}

/** 属性面板模型：key → 任意值 */
export type PropPanelModel = Record<string, unknown>
