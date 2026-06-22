export type FloatingBallTheme = 'light' | 'dark'

export type DockSide = 'left' | 'right' | 'none'

export interface FloatingBallPrefs {
  shrunk: boolean
  hidden: boolean
  theme: FloatingBallTheme
  label?: string
}
