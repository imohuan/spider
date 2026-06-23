<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()

const groups = [
  {
    section: '监控',
    items: [
      { id: 'dashboard', name: 'Dashboard', icon: 'dashboard', path: '/dashboard' },
      { id: 'queue', name: '任务队列', icon: 'list_alt', path: '/queue' },
    ],
  },
  {
    section: '数据',
    items: [
      { id: 'preview', name: '预览UI', icon: 'grid_view', path: '/preview' },
      { id: 'data', name: '数据浏览', icon: 'table_chart', path: '/data' },
      { id: 'proxy', name: 'IP 池', icon: 'vpn_lock', path: '/proxy' },
      { id: 'amap', name: '地图搜索', icon: 'map', path: '/amap' },
      { id: 'shengyi-ai', name: '生意转让', icon: 'psychology', path: '/shengyi-ai' },
    ],
  },
  {
    section: '运维',
    items: [
      { id: 'captcha', name: '验证码日志', icon: 'verified_user', path: '/captcha' },
      { id: 'config', name: '配置', icon: 'settings', path: '/config' },
      { id: 'parsers', name: 'Parser 管理', icon: 'extension', path: '/parsers' },
      { id: 'cookie-presets', name: 'Cookie 预设', icon: 'cookie', path: '/cookie-presets' },
    ],
  },
  {
    section: '系统',
    items: [
      { id: 'logs', name: '日志', icon: 'terminal', path: '/logs' },
    ],
  },
]
</script>

<template>
  <aside class="w-56 bg-surface-container-lowest border-r border-outline-variant flex flex-col flex-shrink-0">
    <div class="px-5 py-4 border-b border-outline-variant">
      <div class="flex items-center gap-ax-sm">
        <div class="w-7 h-7 rounded-md flex items-center justify-center bg-primary text-on-primary text-xs font-bold">58</div>
        <div>
          <div class="text-sm font-medium text-primary leading-tight">爬虫管理后台</div>
          <div class="text-[10px] text-secondary leading-tight">v0.1 · localhost</div>
        </div>
      </div>
    </div>

    <div class="px-4 py-3 border-b border-outline-variant">
      <div class="flex items-center gap-ax-sm mb-1">
        <span class="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></span>
        <span class="text-xs font-medium text-primary">爬虫运行中</span>
      </div>
      <div class="text-[10px] text-secondary">PID 3852 · 运行 2h17m</div>
    </div>

    <nav class="flex-1 py-ax-sm overflow-y-auto">
      <template v-for="group in groups" :key="group.section">
        <p class="text-[10px] text-secondary uppercase tracking-wider px-5 py-2 font-medium">{{ group.section }}</p>
        <router-link
          v-for="item in group.items"
          :key="item.id"
          :to="item.path"
          class="flex items-center gap-ax-sm px-5 py-2 text-sm transition-colors rounded-[10px] mx-ax-xs"
          :class="route.path === item.path
            ? 'bg-secondary-container text-on-secondary-container font-medium'
            : 'text-secondary hover:bg-surface-container-low'"
        >
          <span class="material-symbols-outlined text-[18px]"
            :style="route.path === item.path ? 'font-variation-settings: \'FILL\' 1' : ''">{{ item.icon }}</span>
          <span>{{ item.name }}</span>
        </router-link>
      </template>
    </nav>

    <div class="px-4 py-3 border-t border-outline-variant text-[10px] text-secondary space-y-0.5">
      <div class="flex justify-between"><span>SQLite</span><span>WAL · 12.4 MB</span></div>
      <div class="flex justify-between"><span>Flask</span><span>:5000</span></div>
    </div>
  </aside>
</template>