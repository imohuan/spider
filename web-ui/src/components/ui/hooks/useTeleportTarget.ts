import { inject, provide, ref, type InjectionKey, type Ref } from 'vue'

export const TELEPORT_TARGET_KEY: InjectionKey<Ref<string | HTMLElement>> =
  Symbol('teleportTarget')

export function provideTeleportTarget(target: Ref<string | HTMLElement> | string | HTMLElement) {
  const targetRef = typeof target === 'object' && 'value' in target ? target : ref(target)
  provide(TELEPORT_TARGET_KEY, targetRef)
}

export function useTeleportTarget(): Ref<string | HTMLElement> {
  return inject(TELEPORT_TARGET_KEY, ref('body'))
}
