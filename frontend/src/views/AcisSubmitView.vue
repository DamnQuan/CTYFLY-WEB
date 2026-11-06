<script setup>
/**
 * ACIS 免登录投稿：匿名身份由本机 ID 标识，内容进入管理员审核队列。
 */
import { ref } from 'vue';
import { api } from '../api.js';
import { acisAnonId, showToast } from '../utils.js';
import ArchiveEditor from '../components/archive/ArchiveEditor.vue';
import AcisAgreementModal from '../components/acis/AcisAgreementModal.vue';
import acisLogo from '../assets/acis-glyph.png';

acisAnonId();

const editorRef = ref(null);
const editorKey = ref(0);
const submitting = ref(false);
const submittedId = ref(0);

async function submit() {
  const payload = editorRef.value?.getPayload();
  if (!payload) return;
  submitting.value = true;
  try {
    const data = await api.post('/api/archive/submissions', payload);
    submittedId.value = data.id;
    showToast(data.message || '投稿已提交');
    editorKey.value += 1;
  } catch (err) {
    showToast(err.message);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="acis-submit-page">
    <AcisAgreementModal />
    <div class="page acis-submit-inner">
      <div class="page-header">
        <div class="acis-submit-brand">
          <img :src="acisLogo" alt="ACIS" class="acis-submit-logo" />
          <div class="acis-submit-sub">投稿新事件 · 无需登录</div>
        </div>
        <router-link class="btn btn-ghost btn-sm" to="/acis">返回 ACIS</router-link>
      </div>

      <div v-if="submittedId" class="glass card acis-success">
        <div class="acis-success-icon">✓</div>
        <div class="acis-success-title">投稿已提交</div>
        <div class="card-sub">编号 #{{ submittedId }}，管理员审核通过后会自动进入 ACIS 资料库。</div>
        <div class="acis-success-actions">
          <button class="btn btn-primary" type="button" @click="submittedId = 0">继续投稿</button>
          <router-link class="btn btn-ghost" to="/acis">返回检索</router-link>
        </div>
      </div>

      <div v-else class="glass card">
        <div class="card-title" style="font-size: 16px">事件投稿</div>
        <div class="card-sub" style="margin-bottom: 14px">可填写文字与图片，提交后由 CTY 行政部审核；投稿人信息不会公开展示。</div>
        <ArchiveEditor :key="editorKey" ref="editorRef" :initial="{}" />
        <div class="acis-submit-actions">
          <button class="btn btn-primary" type="button" :disabled="submitting" @click="submit">
            {{ submitting ? '提交中…' : '提交投稿' }}
          </button>
          <span class="acis-submit-note">无需登录，请确保内容真实、合法、不包含他人隐私。</span>
        </div>
      </div>

      <div class="acis-disclaimer">
        ACIS 资料来自公开渠道与社区投稿，仅供参考，不构成事实认定或法律意见。管理员有权修改、删减或不予收录。
      </div>
    </div>
  </div>
</template>

<style scoped>
.acis-submit-page {
  min-height: calc(100vh - 56px);
  background:
    radial-gradient(circle at 20% 0%, rgba(10, 132, 255, 0.1), transparent 45%),
    radial-gradient(circle at 90% 80%, rgba(100, 210, 255, 0.1), transparent 40%);
}
.acis-submit-inner { max-width: clamp(760px, 62vw, 1120px); }
.acis-submit-brand { display: flex; align-items: center; gap: 12px; }
.acis-submit-logo { width: 138px; height: 44px; object-fit: contain; }
.acis-submit-sub { margin-top: 4px; color: var(--text-2); font-size: 12.5px; }
.acis-submit-actions { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--border); }
.acis-submit-note { color: var(--gray); font-size: 12px; }
.acis-success { text-align: center; padding: 42px 24px; }
.acis-success-icon { width: 54px; height: 54px; margin: 0 auto 12px; border-radius: 50%; background: rgba(52, 199, 89, 0.16); color: #34c759; font-size: 28px; line-height: 54px; }
.acis-success-title { font-size: 20px; font-weight: 700; }
.acis-success-actions { display: flex; justify-content: center; gap: 10px; margin-top: 18px; flex-wrap: wrap; }
.acis-disclaimer { margin-top: 18px; color: var(--gray); font-size: 12px; line-height: 1.7; }
</style>
