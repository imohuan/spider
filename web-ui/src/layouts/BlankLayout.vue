<script setup lang="ts">
</script>

<template>
  <div class="h-screen w-screen overflow-hidden bg-background">
    <Toaster position="bottom-right" rich-colors close-button />
    <router-view v-slot="{ Component }">
      <component :is="Component" />
    </router-view>
  </div>
</template>
