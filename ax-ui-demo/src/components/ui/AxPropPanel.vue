<script setup lang="ts">
import type { PropPanelModel, PropPanelSchemaItem } from './types'
import AxSwitch from './AxSwitch.vue'
import AxButton from './AxButton.vue'
import AxSelect from './AxSelect.vue'
import AxSlider from './AxSlider.vue'
import AxInput from './AxInput.vue'

const props = withDefaults(
  defineProps<{
    modelValue: PropPanelModel
    schema: PropPanelSchemaItem[]
    title?: string
  }>(),
  {
    title: '属性配置',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: PropPanelModel]
}>()

const set = (key: string, value: unknown) => {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>

<template>
  <div class="w-full space-y-0.5">
    <p
      v-if="title"
      class="font-label-md text-[10px] text-secondary uppercase tracking-wider px-1 pb-2"
    >
      {{ title }}
    </p>

    <div
      v-for="item in schema"
      :key="item.key"
      class="flex items-start justify-between gap-ax-md py-2 px-1 rounded-lg"
    >
      <div class="flex-1 pt-0.5" style="min-width: 48px;">
        <p class="font-body-sm text-[12px] font-semibold text-primary leading-tight break-words">
          {{ item.label }}
        </p>
        <p
          v-if="item.description"
          class="font-body-sm text-[10px] text-secondary mt-0.5 leading-relaxed break-words"
        >
          {{ item.description }}
        </p>
      </div>

      <div class="flex items-center min-w-0">
        <template v-if="item.type === 'switch'">
          <AxSwitch
            :model-value="!!modelValue[item.key]"
             size="lg"
            @update:model-value="set(item.key, $event)"
          />
        </template>

        <template v-else-if="item.type === 'segmented'">
          <div class="flex items-center flex-wrap bg-surface-container rounded-lg p-0.5 gap-0.5 max-w-full">
            <AxButton
              v-for="opt in item.options"
              :key="opt.value"
              :variant="modelValue[item.key] === opt.value ? 'primary' : 'ghost'"
               size="lg"
              @click="set(item.key, opt.value)"
            >
              {{ opt.label }}
            </AxButton>
          </div>
        </template>

        <template v-else-if="item.type === 'select'">
          <div class="w-48">
            <AxSelect
              :model-value="modelValue[item.key] as string | number"
              :options="item.options"
              size="sm"
              @update:model-value="set(item.key, $event)"
            />
          </div>
        </template>

        <template v-else-if="item.type === 'slider'">
          <div class="flex items-center gap-ax-sm w-48">
            <AxSlider
              :model-value="modelValue[item.key] as number"
              :min="item.min || 0"
              :max="item.max || 100"
              class="flex-1"
              @update:model-value="set(item.key, $event)"
            />
            <span
              class="font-label-md text-[10px] text-primary font-semibold w-6 text-right tabular-nums"
            >
              {{ modelValue[item.key] }}
            </span>
          </div>
        </template>

        <template v-else-if="item.type === 'input'">
          <AxInput
            resize="none"
            :model-value="modelValue[item.key] as string"
            :placeholder="item.placeholder || ''"
             size="lg"
            class="w-48"
            @update:model-value="set(item.key, $event)"
          />
        </template>

        <template v-else-if="item.type === 'textarea'">
          <AxInput
            multiline
            :model-value="modelValue[item.key] as string"
            :placeholder="item.placeholder || ''"
            resize="vertical"
            :rows="item.rows || 3"
             size="lg"
            class="w-56"
            @update:model-value="set(item.key, $event)"
          />
        </template>
      </div>
    </div>
  </div>
</template>
