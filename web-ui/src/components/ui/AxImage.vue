<script setup lang="ts">
/**
 * LazyImage — 懒加载图片组件
 *
 * 支持：loading / loaded / error 三态，点击放大预览，
 * hover 放大图标，自适应宽高比。
 */
import { ref, computed, watch } from 'vue';

const props = withDefaults(defineProps<{
  /** 图片 URL */
  src: string;
  /** 替代文字 */
  alt?: string;
  /** 预览图片列表（用于 ImageViewer 多图浏览） */
  previewList?: string[] | null;
  /** 当前图片在 previewList 中的索引 */
  previewIndex?: number;
  /** 图片填充模式 */
  objectFit?: 'cover' | 'contain';
  /** 是否自适应宽高比（加载前保持正方形占位） */
  adaptiveAspect?: boolean;
}>(), {
  adaptiveAspect: false,
  objectFit: 'cover',
});

/** blob URL 不能用 loading="lazy" — 浏览器在延迟加载窗口中可能已回收 blob */
const imgLoading = computed<'lazy' | 'eager'>(() =>
  props.src.startsWith('blob:') ? 'eager' : 'lazy',
);

const emit = defineEmits<{
  load: [event: Event];
  error: [event: Event];
  /** 点击预览 */
  preview: [src: string, list: string[], index: number];
}>();

const loadState = ref<'loading' | 'loaded' | 'error'>('loading');
const retryKey = ref(0);

// 调试：追踪 src 变化和加载状态
watch(() => props.src, (newSrc, oldSrc) => {
  console.log(`[LazyImage] src changed:`, { oldSrc, newSrc, isBlob: newSrc?.startsWith('blob:') });
  loadState.value = 'loading';
  retryKey.value = 0;
});

const imageSrc = computed(() => {
  // blob URL 不支持 query 参数，只在 HTTP URL 上加 retry 缓存穿透
  if (props.src.startsWith('blob:')) return props.src;
  if (retryKey.value <= 0) return props.src;
  const sep = props.src.includes('?') ? '&' : '?';
  return `${props.src}${sep}_retry=${retryKey.value}`;
});

/** blob URL retry 需要强制重新创建 img 元素 */
const imgKey = computed(() => {
  if (!props.src.startsWith('blob:')) return props.src;
  return `${props.src}#${retryKey.value}`;
});

function handleLoad(e: Event): void {
  console.log(`[LazyImage] load success:`, { src: props.src, isBlob: props.src?.startsWith('blob:') });
  loadState.value = 'loaded';
  emit('load', e);
}

function handleError(e: Event): void {
  const img = e.target as HTMLImageElement;
  console.warn(`[LazyImage] load error:`, {
    src: props.src,
    isBlob: props.src?.startsWith('blob:'),
    complete: img?.complete,
    naturalWidth: img?.naturalWidth,
    naturalHeight: img?.naturalHeight,
  });
  loadState.value = 'error';
  emit('error', e);
}

function handleClick(): void {
  if (loadState.value === 'loaded') {
    const list = props.previewList ?? [imageSrc.value];
    const index = props.previewList ? (props.previewIndex ?? 0) : 0;
    emit('preview', imageSrc.value, list, index);
  } else if (loadState.value === 'error') {
    loadState.value = 'loading';
    retryKey.value++;
  }
}
</script>

<template>
  <div
    class="group relative w-full cursor-pointer overflow-hidden bg-surface-container-low"
    :class="[!adaptiveAspect ? 'h-full' : 'h-auto', adaptiveAspect && loadState !== 'loaded' ? 'aspect-square' : '']"
    @click="handleClick"
  >
    <!-- 加载中 -->
    <div v-if="loadState === 'loading'"
      class="absolute inset-0 flex flex-col items-center justify-center text-outline">
      <span class="material-symbols-outlined mb-ax-xs text-xl animate-spin">progress_activity</span>
      <span class="text-[10px]">加载中...</span>
    </div>

    <!-- 加载失败 -->
    <div v-else-if="loadState === 'error'"
      class="absolute inset-0 flex flex-col items-center justify-center text-error cursor-pointer">
      <span class="material-symbols-outlined mb-ax-xs text-xl">broken_image</span>
      <span class="text-[10px] font-medium">加载失败</span>
      <span class="mt-0.5 text-[9px] text-outline">点击重试</span>
    </div>

    <img
      :key="imgKey"
      :src="imageSrc"
      :alt="alt"
      class="w-full transition-all duration-300"
      :class="[
        !adaptiveAspect ? 'h-full' : 'h-auto',
        objectFit === 'cover' ? 'object-cover' : 'object-contain',
        loadState === 'loaded' ? 'opacity-100' : 'opacity-0',
      ]"
      :loading="imgLoading"
      @load="handleLoad"
      @error="handleError"
    />

    <!-- Hover 放大提示 -->
    <div v-if="loadState === 'loaded'"
      class="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition-all group-hover:bg-black/30 group-hover:opacity-100">
      <span class="material-symbols-outlined text-2xl text-white drop-shadow-md scale-75 transition-transform group-hover:scale-100">
        zoom_in
      </span>
    </div>
  </div>
</template>
