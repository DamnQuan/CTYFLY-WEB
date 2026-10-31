<script setup>
/**
 * 飞圈事件编辑器：投稿页与后台审核页共用。
 * 只负责编辑与校验，提交动作由页面决定；管理员模式额外开放个人信息处理选项。
 */
import { ref } from 'vue';
import { api } from '../../api.js';
import { showToast } from '../../utils.js';
import Icon from '../Icon.vue';
import DatePicker from '../DatePicker.vue';
import SelectMenu from '../SelectMenu.vue';

const props = defineProps({
  initial: { type: Object, default: () => ({}) },
  adminMode: { type: Boolean, default: false },
});

const CATEGORIES = ['事故与事件', '平台与规则', '社区与活动', '人物与账号', '其他'];
const categoryOptions = CATEGORIES.map((value) => ({ value, label: value }));

function blank() {
  return {
    title: '',
    occurred_at: '',
    category: '社区与活动',
    summary: '',
    tags: [],
    blocks: [{ type: 'text', text: '' }],
    sources: [{ title: '', url: '', publisher: '', published_at: '' }],
    contact: '',
    personal_info_mode: 'public',
  };
}

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}));
}

const form = ref({ ...blank(), ...clone(props.initial) });
if (!form.value.blocks?.length) form.value.blocks = [{ type: 'text', text: '' }];
if (!form.value.sources?.length) form.value.sources = [{ title: '', url: '', publisher: '', published_at: '' }];
const tagsText = ref((form.value.tags || []).join('，'));
const uploading = ref(false);

function textBlock() {
  form.value.blocks.push({ type: 'text', text: '' });
}
function imageBlock() {
  form.value.blocks.push({ type: 'image', url: '', caption: '' });
}
function removeBlock(index) {
  if (form.value.blocks.length <= 1) {
    showToast('至少保留一个内容块');
    return;
  }
  form.value.blocks.splice(index, 1);
}
function moveBlock(index, step) {
  const target = index + step;
  if (target < 0 || target >= form.value.blocks.length) return;
  const list = form.value.blocks;
  [list[index], list[target]] = [list[target], list[index]];
}
function addSource() {
  form.value.sources.push({ title: '', url: '', publisher: '', published_at: '' });
}
function removeSource(index) {
  if (form.value.sources.length <= 1) {
    showToast('至少保留一个资料来源');
    return;
  }
  form.value.sources.splice(index, 1);
}

async function pickImage(block, event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  if (file.size > 2 * 1024 * 1024) {
    showToast('图片不能超过 2 MB');
    return;
  }
  uploading.value = true;
  try {
    const fd = new FormData();
    fd.append('file', file);
    const data = await api.upload('/api/uploads/archive-image', fd);
    block.url = data.url;
    showToast('图片已上传');
  } catch (err) {
    showToast(err.message);
  } finally {
    uploading.value = false;
  }
}

function getPayload() {
  const tags = tagsText.value
    .split(/[，,]/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 10);
  return {
    ...clone(form.value),
    tags,
    personal_info_mode: props.adminMode ? form.value.personal_info_mode : 'public',
  };
}

defineExpose({ getPayload });
</script>

<template>
  <div class="archive-editor">
    <div class="grid grid-2">
      <div>
        <div class="label">事件标题</div>
        <input v-model="form.title" class="input" maxlength="120" placeholder="例如：某平台规则调整引发社区讨论" />
      </div>
      <div>
        <div class="label">发生时间</div>
        <DatePicker v-model="form.occurred_at" mode="date" placeholder="选择事件发生日期" />
      </div>
    </div>

    <div class="grid grid-2" style="margin-top: 14px">
      <div>
        <div class="label">分类</div>
        <SelectMenu v-model="form.category" :options="categoryOptions" />
      </div>
      <div>
        <div class="label">标签</div>
        <input v-model="tagsText" class="input" placeholder="用逗号分隔，例如：平台规则，连飞" />
      </div>
    </div>

    <div style="margin-top: 14px">
      <div class="label">摘要</div>
      <textarea v-model="form.summary" class="input" rows="3" maxlength="300" placeholder="一两句话概括事件，会显示在检索结果里" />
    </div>

    <div class="editor-section">
      <div class="editor-head">
        <div class="label" style="margin: 0">正文与图片</div>
        <div class="editor-actions">
          <button class="btn btn-ghost btn-sm" type="button" @click="textBlock"><Icon name="file" :size="14" /> 文字块</button>
          <button class="btn btn-ghost btn-sm" type="button" @click="imageBlock"><Icon name="globe" :size="14" /> 图片块</button>
        </div>
      </div>

      <div v-for="(block, index) in form.blocks" :key="index" class="block-card">
        <div class="block-head">
          <span class="tag" :class="block.type === 'image' ? 'tag-blue' : 'tag-green'">
            {{ block.type === 'image' ? '图片' : '文字' }}
          </span>
          <div class="block-tools">
            <button class="btn btn-ghost btn-sm" type="button" @click="moveBlock(index, -1)">上移</button>
            <button class="btn btn-ghost btn-sm" type="button" @click="moveBlock(index, 1)">下移</button>
            <button class="btn btn-ghost btn-sm" type="button" @click="removeBlock(index)">删除</button>
          </div>
        </div>
        <template v-if="block.type === 'image'">
          <img v-if="block.url" :src="block.url" alt="" class="block-image" />
          <div class="block-image-row">
            <label class="btn btn-ghost btn-sm" style="cursor: pointer">
              {{ block.url ? '更换图片' : '上传图片' }}
              <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden @change="pickImage(block, $event)" />
            </label>
            <input v-model="block.caption" class="input" maxlength="200" placeholder="图片说明，选填" />
          </div>
        </template>
        <textarea v-else v-model="block.text" class="input" rows="6" maxlength="8000" placeholder="事件经过、背景与结果" />
      </div>
    </div>

    <div class="editor-section">
      <div class="editor-head">
        <div class="label" style="margin: 0">资料来源</div>
        <button class="btn btn-ghost btn-sm" type="button" @click="addSource"><Icon name="plus" :size="14" /> 添加来源</button>
      </div>
      <div v-for="(source, index) in form.sources" :key="index" class="source-row">
        <input v-model="source.title" class="input" maxlength="120" placeholder="来源标题，必填" />
        <input v-model="source.url" class="input" maxlength="800" placeholder="https:// 链接，必填" />
        <input v-model="source.publisher" class="input" maxlength="80" placeholder="发布方，选填" />
        <button class="btn btn-ghost btn-sm" type="button" @click="removeSource(index)">删除</button>
      </div>
    </div>

    <div class="grid grid-2" style="margin-top: 14px">
      <div>
        <div class="label">联系 QQ</div>
        <input v-model="form.contact" class="input" maxlength="100" placeholder="仅管理员可见，用于核实情况" />
      </div>
      <div v-if="adminMode">
        <div class="label">个人信息处理</div>
        <SelectMenu
          v-model="form.personal_info_mode"
          :options="[
            { value: 'public', label: '公开显示' },
            { value: 'masked', label: '脱敏显示' },
            { value: 'hidden', label: '隐藏联系方式' },
          ]"
        />
      </div>
    </div>
    <div v-if="uploading" class="card-sub" style="margin-top: 10px">图片上传中…</div>
  </div>
</template>

<style scoped>
.archive-editor { display: flex; flex-direction: column; }
.editor-section { margin-top: 18px; }
.editor-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
.editor-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.block-card {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  margin-bottom: 10px;
}
.block-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
.block-tools { display: flex; gap: 4px; flex-wrap: wrap; }
.block-image { width: 100%; max-height: 320px; object-fit: contain; border-radius: var(--radius-sm); background: var(--surface-solid); margin-bottom: 8px; }
.block-image-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.block-image-row .input { flex: 1; min-width: 180px; }
.source-row { display: grid; grid-template-columns: 1.1fr 1.8fr 0.9fr auto; gap: 8px; margin-bottom: 8px; }
@media (max-width: 800px) {
  .source-row { grid-template-columns: 1fr; }
}
</style>
