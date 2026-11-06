<script setup>
/**
 * 用户名 + 已装备的称号/徽章角标
 * 用法：<UserTag :badge="u.equipped_badge" :title="u.equipped_title">{{ u.username }}</UserTag>
 * 默认插槽放用户名原文，便于外层套 router-link 或加粗
 *
 * 徽章内容：payload 为 `icon:star` 这种形式时渲染 SVG 图标，推荐，否则渲染文字
 */
import { computed } from 'vue';
import Icon from './Icon.vue';

const props = defineProps({
  badge: { type: String, default: '' },
  title: { type: String, default: '' },
  size: { type: String, default: 'md' }, // sm | md | lg
});

const iconName = computed(() =>
  props.badge.startsWith('icon:') ? props.badge.slice(5) : '',
);
const iconSize = computed(() => ({ sm: 11, md: 13, lg: 15 }[props.size] || 13));
</script>

<template>
  <span class="utag" :class="`utag-${size}`">
    <span v-if="badge" class="utag-badge" :title="`徽章：${badge}`">
      <Icon v-if="iconName" :name="iconName" :size="iconSize" />
      <template v-else>{{ badge }}</template>
    </span>
    <span class="utag-name"><slot /></span>
    <span v-if="title" class="utag-title">{{ title }}</span>
  </span>
</template>

<style scoped>
.utag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  max-width: 100%;
}
.utag-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 徽章：小圆角方块，坐落在用户名前面 */
.utag-badge {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 5px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1;
  font-weight: 600;
  color: #fff;
  background: var(--blue);
  box-shadow: 0 2px 6px rgba(0, 113, 227, 0.28);
}

/* 称号：淡蓝胶囊，跟在用户名后面 */
.utag-title {
  flex-shrink: 0;
  padding: 2px 7px;
  border-radius: 980px;
  font-size: 11.5px;
  line-height: 1.5;
  font-weight: 500;
  color: var(--blue);
  background: rgba(0, 113, 227, 0.12);
  border: 1px solid rgba(0, 113, 227, 0.18);
}

/* 尺寸 */
.utag-sm .utag-badge { min-width: 17px; height: 17px; font-size: 10.5px; border-radius: 5px; padding: 0 4px; }
.utag-sm .utag-title { font-size: 10.5px; padding: 1px 6px; }
.utag-lg .utag-badge { min-width: 24px; height: 24px; font-size: 14px; border-radius: 7px; }
.utag-lg .utag-title { font-size: 12.5px; padding: 3px 9px; }
</style>
