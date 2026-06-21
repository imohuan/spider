import type { App } from 'vue'

// 组件
import AxAlert from './AxAlert.vue'
import AxButton from './AxButton.vue'
import AxDialog from './AxDialog.vue'
import AxDropdown from './AxDropdown.vue'
import AxImage from './AxImage.vue'
import AxImageViewer from './AxImageViewer.vue'
import AxInput from './AxInput.vue'
import AxJsonViewer from './AxJsonViewer.vue'
import AxPagination from './AxPagination.vue'
import AxPropPanel from './AxPropPanel.vue'
import AxSelect from './AxSelect.vue'
import AxSlider from './AxSlider.vue'
import AxSwitch from './AxSwitch.vue'
import AxTooltip from './AxTooltip.vue'

// Hooks
export { useNotify } from './hooks/useNotify'
export type { NotificationLog } from './hooks/useNotify'
export { useFloating } from './hooks/useFloating'
export type { UseFloatingOptions } from './hooks/useFloating'
export { useLinkify } from './hooks/useLinkify'
export {
  provideTeleportTarget,
  useTeleportTarget,
  TELEPORT_TARGET_KEY,
} from './hooks/useTeleportTarget'

// Functional
export { FloatingBall, useFloatingBall } from './functional'
export type { FloatingBallPrefs, FloatingBallTheme, DockSide } from './functional'

// 按需导入：直接 export 组件
export {
  AxAlert,
  AxButton,
  AxDialog,
  AxDropdown,
  AxImage,
  AxImageViewer,
  AxInput,
  AxJsonViewer,
  AxPagination,
  AxPropPanel,
  AxSelect,
  AxSlider,
  AxSwitch,
  AxTooltip,
}

const components = {
  AxAlert,
  AxButton,
  AxDialog,
  AxDropdown,
  AxImage,
  AxImageViewer,
  AxInput,
  AxJsonViewer,
  AxPagination,
  AxPropPanel,
  AxSelect,
  AxSlider,
  AxSwitch,
  AxTooltip,
}

/**
 * 全局注册所有 Ax* 组件。
 * 注册后可在模板中直接使用：<AxButton>、<AxInput> 等。
 */
export function registerComponents(app: App) {
  for (const [name, comp] of Object.entries(components)) {
    app.component(name, comp as any)
  }
}
