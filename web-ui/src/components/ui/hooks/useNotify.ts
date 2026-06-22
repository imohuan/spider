import { ref, h } from 'vue'
import { toast } from 'vue-sonner'

type NotifyType = 'info' | 'success' | 'error' | 'warning' | 'secondary'

export interface NotificationLog {
  id: number
  time: string
  title: string
  message: string
  type: NotifyType
}

const getToastIcon = (type: NotifyType) => {
  if (type === 'success') return 'check_circle'
  if (type === 'error') return 'error'
  if (type === 'secondary') return 'settings'
  return 'info'
}

export function useNotify() {
  const activeNotificationCount = ref(0)
  const notificationHistory = ref<NotificationLog[]>([])

  const triggerNotify = (
    message: string,
    type: NotifyType = 'info',
    title = '',
  ) => {
    const id = Date.now()

    toast.custom(
      (props: { onCloseToast: () => void }) =>
        h(
          'div',
          {
            class:
              'flex items-start gap-ax-sm bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md pro-shadow pointer-events-auto w-80 text-left',
          },
          [
            h(
              'span',
              {
                class:
                  'material-symbols-outlined mt-0.5 ' +
                  (type === 'error'
                    ? 'text-error'
                    : type === 'secondary'
                      ? 'text-secondary'
                      : 'text-primary'),
              },
              getToastIcon(type),
            ),
            h('div', { class: 'flex-1' }, [
              title ? h(
                'h4',
                {
                  class:
                    'font-headline-sm text-body-md font-semibold text-primary mb-0.5',
                },
                title,
              ) : null,
              h(
                'p',
                {
                  class:
                    'font-body-sm text-body-sm text-on-surface-variant leading-normal',
                },
                message,
              ),
            ]),
            h(
              'button',
              {
                onClick: props.onCloseToast,
                class:
                  'w-6 h-6 flex items-center justify-center text-secondary hover:bg-surface-container-low rounded-lg transition-colors shrink-0',
              },
              [h('span', { class: 'material-symbols-outlined text-[16px]' }, 'close')],
            ),
          ],
        ),
      {
        duration: 4000,
        onDismiss: () => {
          activeNotificationCount.value = Math.max(0, activeNotificationCount.value - 1)
        },
        onAutoClose: () => {
          activeNotificationCount.value = Math.max(0, activeNotificationCount.value - 1)
        },
      },
    )

    activeNotificationCount.value++

    const now = new Date()
    const timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`
    notificationHistory.value.unshift({ id, time: timeStr, title, message, type })
  }

  const clearLogs = () => {
    notificationHistory.value = []
    triggerNotify('本地日志缓存序列已执行物理刷洗。', 'secondary', '日志洗刷完毕')
  }

  return {
    activeNotificationCount,
    notificationHistory,
    triggerNotify,
    clearLogs,
  }
}
