# UI 组件规则

本项目（`web-ui`）使用 Axiom UI 组件库（`src/components/ui/`）。

## 强制要求

- 所有 UI 界面必须使用 `Ax*` 组件，禁止手写原生 HTML 按钮/输入框/选择器
- 布局使用 Tailwind v4 class，间距使用 `gap-ax-sm` / `p-ax-md` 等 `ax-` 前缀间距
- 颜色使用语义 token（`text-primary` / `bg-surface-container-low`），禁止硬编码色值
- 图标使用 Material Symbols Outlined：`<span class="material-symbols-outlined">icon_name</span>`
- 通知使用 `useNotify()`，禁止手写通知逻辑
- 弹窗使用 `AxDialog`，浮层使用 `AxDropdown` / `AxTooltip`

## 可用组件清单

`AxButton`、`AxInput`、`AxSelect`、`AxDropdown`、`AxDialog`、`AxAlert`、
`AxSlider`、`AxTooltip`、`AxPropPanel`、`AxSwitch`、`AxImage`、
`AxJsonViewer`、`AxImageViewer`

## Hooks

`useNotify`、`useFloating`、`useLinkify`、`useTeleportTarget`、`provideTeleportTarget`

## Functional

`FloatingBall`、`useFloatingBall`

## 路径别名

`@` → `src`（已在 `vite.config.ts` 与 `tsconfig.app.json` 中配置）

## 使用方式

全局注册后直接使用标签：

```vue
<AxButton variant="primary">保存</AxButton>
<AxInput v-model="name" placeholder="名称" />
<AxSelect v-model="selected" :options="options" placeholder="请选择" />
```

按需导入：

```ts
import { AxButton, useNotify } from '@/components/ui'
```
