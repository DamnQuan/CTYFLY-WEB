<script setup>
/**
 * 飞圈事件投稿：登录用户填写，管理员审核通过后自动发布。
 */
import { onMounted, ref } from 'vue';
import { api } from '../api.js';
import { showToast } from '../utils.js';
import ArchiveEditor from '../components/archive/ArchiveEditor.vue';

const editorRef = ref(null);
const submitting = ref(false);
const agreed = ref(false);
const editorKey = ref(0);
const mine = ref([]);
const loadingMine = ref(false);

const STATUS = {
  pending: { text: '审核中', cls: 'tag-orange' },
  approved: { text: '已发布', cls: 'tag-green' },
  rejected: { text: '已驳回', cls: 'tag-red' },
};

async function loadMine() {
  loadingMine.value = true;
  try {
    const data = await api.get('/api/archive/mine');
    mine.value = data.items || [];
  } catch (err) {
    showToast(err.message);
  } finally {
    loadingMine.value = false;
  }
}

async function submit() {
  if (!agreed.value) {
    showToast('请先确认投稿内容真实并同意免责声明');
    return;
  }
  const payload = editorRef.value?.getPayload();
  if (!payload) return;
  submitting.value = true;
  try {
    const data = await api.post('/api/archive/submissions', payload);
    showToast(data.message || '投稿已提交');
    editorKey.value += 1;
    agreed.value = false;
    loadMine();
  } catch (err) {
    showToast(err.message);
  } finally {
    submitting.value = false;
  }
}

onMounted(loadMine);
</script>

<template>
  <div class="page archive-submit-page">
    <div class="page-header">
      <div>
        <div class="page-title">投稿飞圈事件</div>
        <div class="page-desc">提交后由管理员审核编辑，审核通过会自动发布到飞圈事件检索</div>
      </div>
      <router-link class="btn btn-ghost btn-sm" to="/archive">返回检索</router-link>
    </div>

    <div class="glass card">
      <ArchiveEditor :key="editorKey" ref="editorRef" :initial="{}" />
      <div class="submit-footer">
        <label class="agree-row">
          <input v-model="agreed" type="checkbox" />
          <span>我确认事件资料来自可公开的来源，并同意平台在审核后编辑与发布</span>
        </label>
        <button class="btn btn-primary" type="button" :disabled="submitting" @click="submit">
          {{ submitting ? '提交中…' : '提交投稿' }}
        </button>
      </div>
      <div class="archive-disclaimer">
        投稿人信息不会公开展示。事件资料来自公开渠道与社区整理，仅供参考，不构成事实认定或法律意见。
      </div>
    </div>

    <div class="glass card" style="margin-top: 16px">
      <div class="card-title" style="font-size: 15px">我的投稿</div>
      <div v-if="loadingMine" class="loading">加载中…</div>
      <div v-else-if="!mine.length" class="empty" style="padding: 22px 0">
        <div>还没有投稿记录</div>
      </div>
      <div v-else class="mine-list">
        <div v-for="row in mine" :key="row.id" class="mine-item">
          <div class="mine-main">
            <div class="mine-title">{{ row.title || '未命名投稿' }}</div>
            <div class="mine-sub">{{ row.created_at }}<template v-if="row.review_note"> · {{ row.review_note }}</template></div>
          </div>
          <span class="tag" :class="STATUS[row.status]?.cls || 'tag-blue'">{{ STATUS[row.status]?.text || row.status }}</span>
          <router-link v-if="row.event_id" class="btn btn-ghost btn-sm" :to="`/archive/${row.event_id}`">查看</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.archive-submit-page { max-width: clamp(760px, 62vw, 1120px); }
.submit-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--border); }
.agree-row { display: flex; align-items: flex-start; gap: 8px; font-size: 12.5px; color: var(--text-2); line-height: 1.6; }
.agree-row input { margin-top: 3px; }
.mine-list { display: flex; flex-direction: column; }
.mine-item { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px dashed var(--border); }
.mine-item:last-child { border-bottom: none; }
.mine-main { flex: 1; min-width: 0; }
.mine-title { font-size: 14px; font-weight: 500; }
.mine-sub { margin-top: 4px; color: var(--gray); font-size: 12px; }
.archive-disclaimer { margin-top: 14px; color: var(--gray); font-size: 12px; line-height: 1.7; }
</style>
