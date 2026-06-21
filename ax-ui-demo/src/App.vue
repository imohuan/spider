<script setup lang="ts">
import CrawlerSidebar from '@/components/layout/CrawlerSidebar.vue'
import CrawlerHeader from '@/components/layout/CrawlerHeader.vue'
import CrawlerFooter from '@/components/layout/CrawlerFooter.vue'
</script>

<template>
  <div class="flex h-screen w-screen overflow-hidden bg-background">
    <Toaster position="bottom-right" rich-colors close-button />
    <CrawlerSidebar />
    <div class="flex-1 flex flex-col overflow-hidden">
      <CrawlerHeader />
      <main class="flex-1 overflow-y-auto p-margin">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
      <CrawlerFooter />
    </div>
  </div>
</template>

<style>
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>