<script setup>
/**
 * 飞圈事件详情：论坛式互动，点赞、收藏、评论、回复、举报与相关事件。
 */
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../api.js';
import { fmtMonth, fmtTime, showToast } from '../utils.js';
import { confirmModal, promptModal } from '../modal.js';
import { useAuthStore } from '../stores/auth.js';
import Icon from '../components/Icon.vue';
import SelectMenu from '../components/SelectMenu.vue';
import AcisAgreementModal from '../components/acis/AcisAgreementModal.vue';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const isAcis = computed(() => Boolean(route.meta.acis));

const item = ref(null);
const comments = ref([]);
const commentsTotal = ref(0);
const loading = ref(true);
const notFound = ref(false);
const busy = ref(false);
const commentText = ref('');
const commentBusy = ref(false);
const replyTo = ref(null);
const showCorrection = ref(false);
const submitting = ref(false);
const correction = ref({ field: 'title', proposed_value: '', reason: '', source_url: '' });
const correctionOptions = [
  { value: 'title', label: '标题' },
  { value: 'summary', label: '摘要' },
  { value: 'occurred_at', label: '发生月份' },
  { value: 'category', label: '分类' },
  { value: 'other', label: '其他内容' },
];

function needLogin() {
  if (auth.isLoggedIn) return false;
  router.push({ name: 'login', query: { redirect: route.fullPath } });
  return true;
}

async function loadDetail() {
  loading.value = true;
  notFound.value = false;
  try {
    item.value = await api.get(`/api/archive/${route.params.id}`);
  } catch (err) {
    if (err.status === 404) notFound.value = true;
    else showToast(err.message);
  } finally {
    loading.value = false;
  }
}

async function loadComments() {
  try {
    const data = await api.get(`/api/archive/${route.params.id}/comments`);
    comments.value = data.items || [];
    commentsTotal.value = data.total || 0;
  } catch (err) {
    showToast(err.message);
  }
}

async function toggleLike() {
  if (needLogin() || busy.value) return;
  busy.value = true;
  try {
    const data = await api.post(`/api/archive/${route.params.id}/like`);
    item.value.liked = data.liked;
    item.value.like_count = data.count;
  } catch (err) {
    showToast(err.message);
  } finally {
    busy.value = false;
  }
}

async function toggleFavorite() {
  if (needLogin() || busy.value) return;
  busy.value = true;
  try {
    const data = await api.post(`/api/archive/${route.params.id}/favorite`);
    item.value.favorited = data.favorited;
    item.value.favorite_count = data.count;
  } catch (err) {
    showToast(err.message);
  } finally {
    busy.value = false;
  }
}

function startReply(comment) {
  if (needLogin()) return;
  replyTo.value = comment;
  commentText.value = '';
}

function cancelReply() {
  replyTo.value = null;
}

async function submitComment() {
  if (needLogin()) return;
  const content = commentText.value.trim();
  if (content.length < 2) {
    showToast('评论至少需要 2 个字');
    return;
  }
  commentBusy.value = true;
  try {
    await api.post(`/api/archive/${route.params.id}/comments`, {
      content,
      parent_id: replyTo.value?.id || null,
    });
    commentText.value = '';
    replyTo.value = null;
    await loadComments();
    if (item.value) item.value.comment_count = commentsTotal.value;
    showToast('评论已发布');
  } catch (err) {
    showToast(err.message);
  } finally {
    commentBusy.value = false;
  }
}

async function deleteComment(comment) {
  const ok = await confirmModal({
    title: '删除评论',
    message: '删除后无法恢复，确认删除这条评论吗？',
    confirmText: '删除',
  });
  if (ok === null || ok === false) return;
  try {
    await api.delete(`/api/archive/comments/${comment.id}`);
    await loadComments();
    if (item.value) item.value.comment_count = commentsTotal.value;
    showToast('评论已删除');
  } catch (err) {
    showToast(err.message);
  }
}

async function reportComment(comment) {
  if (needLogin()) return;
  const reason = await promptModal({
    title: '举报评论',
    message: '请填写举报原因，管理员会尽快处理。',
    inputPlaceholder: '例如：人身攻击、泄露隐私、广告',
    confirmText: '提交举报',
  });
  if (reason === null) return;
  try {
    const data = await api.post(`/api/archive/comments/${comment.id}/report`, { reason: reason || '' });
    showToast(data.message || '举报已提交');
  } catch (err) {
    showToast(err.message);
  }
}

function openCorrection() {
  if (!isAcis.value && needLogin()) return;
  showCorrection.value = true;
}

function closeCorrection() {
  showCorrection.value = false;
  correction.value = { field: 'title', proposed_value: '', reason: '', source_url: '' };
}

async function submitCorrection() {
  if (!correction.value.proposed_value.trim()) {
    showToast('请填写需要更正的内容');
    return;
  }
  submitting.value = true;
  try {
    const data = await api.post(`/api/archive/${route.params.id}/corrections`, correction.value);
    showToast(data.message || '纠错已提交');
    closeCorrection();
  } catch (err) {
    showToast(err.message);
  } finally {
    submitting.value = false;
  }
}

async function init() {
  await loadDetail();
  if (!notFound.value) await loadComments();
}

init();
</script>

<template>
  <div class="page archive-detail-page">
    <AcisAgreementModal v-if="isAcis" />
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="notFound" class="glass card">
      <div class="empty">
        <div class="empty-icon"><Icon name="book" :size="22" /></div>
        <div>事件不存在或已下线</div>
        <router-link class="btn btn-ghost btn-sm" :to="isAcis ? '/acis' : '/archive'" style="margin-top: 12px">返回检索</router-link>
      </div>
    </div>
    <template v-else-if="item">
      <div class="detail-top">
        <router-link class="back-link" :to="isAcis ? '/acis' : '/archive'"><Icon name="chevron" :size="14" style="transform: rotate(90deg)" /> 返回检索</router-link>
        <button class="btn btn-ghost btn-sm" type="button" @click="openCorrection"><Icon name="file" :size="14" /> 纠错</button>
      </div>

      <div class="glass card detail-card">
        <div class="detail-meta">
          <span v-if="item.featured" class="tag tag-orange">精选</span>
          <span class="tag tag-blue">{{ item.category }}</span>
          <span>{{ fmtMonth(item.occurred_at) }}</span>
          <span class="detail-stat"><Icon name="eye" :size="13" /> {{ item.view_count }} 次浏览</span>
        </div>
        <h1 class="detail-title">{{ item.title }}</h1>
        <div v-if="item.summary" class="detail-summary">{{ item.summary }}</div>
        <div v-if="item.tags?.length" class="detail-tags">
          <span v-for="tag in item.tags" :key="tag" class="archive-tag">#{{ tag }}</span>
        </div>

        <div class="detail-actions">
          <button class="stat-btn" :class="{ on: item.liked }" type="button" @click="toggleLike">
            <Icon name="heart" :size="16" /> {{ item.liked ? '已点赞' : '点赞' }} {{ item.like_count }}
          </button>
          <button class="stat-btn" :class="{ on: item.favorited }" type="button" @click="toggleFavorite">
            <Icon name="bookmark" :size="16" /> {{ item.favorited ? '已收藏' : '收藏' }} {{ item.favorite_count }}
          </button>
          <a class="stat-btn" href="#comments">
            <Icon name="message" :size="16" /> 评论 {{ item.comment_count }}
          </a>
        </div>

        <div class="detail-blocks">
          <template v-for="(block, index) in item.blocks" :key="index">
            <p v-if="block.type === 'text'" class="detail-text">{{ block.text }}</p>
            <figure v-else class="detail-figure">
              <img :src="block.url" :alt="block.caption || item.title" loading="lazy" />
              <figcaption v-if="block.caption">{{ block.caption }}</figcaption>
            </figure>
          </template>
        </div>

        <div class="detail-footer">
          <span>最后更新：{{ item.updated_at }}</span>
          <span>{{ item.disclaimer }}</span>
        </div>
      </div>

      <div id="comments" class="glass card comments-card">
        <div class="comments-head">
          <div class="card-title" style="font-size: 16px">评论 {{ commentsTotal }}</div>
          <span class="card-sub">友善讨论，涉及隐私与人身攻击会被处理</span>
        </div>

        <div v-if="auth.isLoggedIn" class="comment-form">
          <div v-if="replyTo" class="reply-hint">
            正在回复 {{ replyTo.username }}：{{ replyTo.content.slice(0, 40) }}
            <button class="link-btn" type="button" @click="cancelReply">取消</button>
          </div>
          <textarea v-model="commentText" class="input" rows="3" maxlength="500" :placeholder="replyTo ? `回复 ${replyTo.username}` : '写下你的评论…'" />
          <div class="comment-form-actions">
            <button class="btn btn-primary btn-sm" type="button" :disabled="commentBusy" @click="submitComment">发布评论</button>
          </div>
        </div>
        <div v-else class="login-comment">
          <router-link class="btn btn-primary btn-sm" :to="{ name: 'login', query: { redirect: route.fullPath } }">登录后评论</router-link>
        </div>

        <div v-if="!comments.length" class="empty" style="padding: 24px 0">
          <div>还没有评论，来抢沙发</div>
        </div>
        <div v-else class="comment-list">
          <div v-for="comment in comments" :key="comment.id" class="comment">
            <div class="comment-avatar">
              <img v-if="comment.avatar_url" :src="comment.avatar_url" alt="" />
              <span v-else>{{ comment.username.slice(0, 1) }}</span>
            </div>
            <div class="comment-main">
              <div class="comment-head">
                <span class="comment-name">{{ comment.username }}</span>
                <span class="comment-time">{{ fmtTime(comment.created_at) }}</span>
              </div>
              <div class="comment-content">{{ comment.content }}</div>
              <div class="comment-actions">
                <button class="link-btn" type="button" @click="startReply(comment)">回复</button>
                <button v-if="comment.is_mine" class="link-btn" type="button" @click="deleteComment(comment)">删除</button>
                <button v-else class="link-btn" type="button" @click="reportComment(comment)">举报</button>
              </div>
              <div v-if="comment.replies?.length" class="comment-replies">
                <div v-for="reply in comment.replies" :key="reply.id" class="comment reply">
                  <div class="comment-avatar small">
                    <img v-if="reply.avatar_url" :src="reply.avatar_url" alt="" />
                    <span v-else>{{ reply.username.slice(0, 1) }}</span>
                  </div>
                  <div class="comment-main">
                    <div class="comment-head">
                      <span class="comment-name">{{ reply.username }}</span>
                      <span class="comment-time">{{ fmtTime(reply.created_at) }}</span>
                    </div>
                    <div class="comment-content">{{ reply.content }}</div>
                    <div class="comment-actions">
                      <button class="link-btn" type="button" @click="startReply(comment)">回复</button>
                      <button v-if="reply.is_mine" class="link-btn" type="button" @click="deleteComment(reply)">删除</button>
                      <button v-else class="link-btn" type="button" @click="reportComment(reply)">举报</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="item.related?.length" class="related-block">
        <div class="card-title" style="font-size: 15px; margin-bottom: 10px">相关事件</div>
        <div class="related-list">
          <router-link v-for="rel in item.related" :key="rel.id" class="glass card related-card" :to="`${isAcis ? '/acis' : '/archive'}/${rel.id}`">
            <div class="related-title">{{ rel.title }}</div>
            <div class="related-meta">{{ fmtMonth(rel.occurred_at) }} · {{ rel.like_count }} 赞 · {{ rel.comment_count }} 评论</div>
          </router-link>
        </div>
      </div>

      <div v-if="showCorrection" class="glass card correction-card">
        <div class="card-title" style="font-size: 15px">提交纠错</div>
        <div class="card-sub" style="margin-bottom: 12px">管理员审核后会更新事件，并保留修订记录。</div>
        <div class="grid grid-2">
          <div>
            <div class="label">需要更正的部分</div>
            <SelectMenu v-model="correction.field" :options="correctionOptions" />
          </div>
          <div>
            <div class="label">来源链接</div>
            <input v-model="correction.source_url" class="input" maxlength="800" placeholder="https:// 选填" />
          </div>
        </div>
        <div style="margin-top: 12px">
          <div class="label">建议更正为</div>
          <textarea v-model="correction.proposed_value" class="input" rows="4" maxlength="8000" placeholder="写清楚正确内容，便于管理员核对" />
        </div>
        <div style="margin-top: 12px">
          <div class="label">理由</div>
          <input v-model="correction.reason" class="input" maxlength="500" placeholder="为什么需要更正，选填" />
        </div>
        <div class="correction-actions">
          <button class="btn btn-primary" type="button" :disabled="submitting" @click="submitCorrection">提交纠错</button>
          <button class="btn btn-ghost" type="button" @click="closeCorrection">取消</button>
        </div>
      </div>

      <div class="archive-disclaimer">{{ item.correction_notice }}</div>
    </template>
  </div>
</template>

<style scoped>
.archive-detail-page { max-width: clamp(760px, 62vw, 1040px); }
.detail-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.back-link { display: inline-flex; align-items: center; gap: 6px; color: var(--text-2); font-size: 13px; text-decoration: none; }
.detail-meta { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; color: var(--gray); font-size: 12.5px; }
.detail-stat { display: inline-flex; align-items: center; gap: 4px; }
.detail-title { font-size: 26px; line-height: 1.35; margin: 12px 0 10px; }
.detail-summary { color: var(--text-2); font-size: 14.5px; line-height: 1.8; padding: 12px 14px; border-radius: var(--radius-sm); background: var(--surface); }
.detail-tags { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
.archive-tag { color: var(--blue); font-size: 12px; }
.detail-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
.stat-btn {
  display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--border);
  background: transparent; color: var(--text-2); border-radius: 999px; padding: 7px 13px;
  font-size: 12.5px; cursor: pointer; text-decoration: none; transition: all 0.18s ease;
}
.stat-btn:hover { color: var(--text); border-color: rgba(10, 132, 255, 0.4); }
.stat-btn.on { color: var(--blue); border-color: rgba(10, 132, 255, 0.45); background: rgba(10, 132, 255, 0.08); }
.detail-blocks { margin-top: 22px; }
.detail-text { white-space: pre-wrap; line-height: 1.9; font-size: 14.5px; color: var(--text); margin: 0 0 16px; }
.detail-figure { margin: 18px 0; }
.detail-figure img { width: 100%; border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--surface-solid); }
.detail-figure figcaption { margin-top: 6px; text-align: center; color: var(--gray); font-size: 12px; }
.detail-footer { margin-top: 22px; padding-top: 14px; border-top: 1px dashed var(--border); color: var(--gray); font-size: 12px; line-height: 1.7; display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.comments-card { margin-top: 16px; }
.comments-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.comment-form { margin-top: 12px; }
.comment-form-actions { display: flex; justify-content: flex-end; margin-top: 8px; }
.reply-hint { margin-bottom: 8px; padding: 8px 10px; border-radius: var(--radius-sm); background: rgba(10, 132, 255, 0.08); color: var(--text-2); font-size: 12.5px; }
.login-comment { margin-top: 12px; }
.comment-list { margin-top: 14px; display: flex; flex-direction: column; gap: 14px; }
.comment { display: flex; gap: 10px; }
.comment.reply { margin-top: 10px; }
.comment-avatar {
  width: 34px; height: 34px; flex: none; border-radius: 50%; overflow: hidden;
  display: flex; align-items: center; justify-content: center;
  background: var(--surface-solid); color: var(--text-2); font-size: 14px;
}
.comment-avatar.small { width: 28px; height: 28px; font-size: 12px; }
.comment-avatar img { width: 100%; height: 100%; object-fit: cover; }
.comment-main { flex: 1; min-width: 0; }
.comment-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.comment-name { font-size: 13px; font-weight: 600; }
.comment-time { color: var(--gray); font-size: 11.5px; }
.comment-content { margin-top: 4px; font-size: 13.5px; line-height: 1.7; white-space: pre-wrap; }
.comment-actions { display: flex; gap: 12px; margin-top: 4px; }
.link-btn { border: none; background: transparent; color: var(--gray); font-size: 12px; cursor: pointer; padding: 0; }
.link-btn:hover { color: var(--blue); }
.comment-replies { margin-top: 4px; padding-left: 12px; border-left: 2px solid var(--border); }
.related-block { margin-top: 20px; }
.related-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.related-card { text-decoration: none; color: inherit; padding: 12px; transition: border-color 0.18s ease; }
.related-card:hover { border-color: rgba(10, 132, 255, 0.4); }
.related-title { font-size: 13.5px; font-weight: 500; line-height: 1.5; }
.related-meta { margin-top: 5px; color: var(--gray); font-size: 11.5px; }
.correction-card { margin-top: 16px; }
.correction-actions { display: flex; gap: 10px; margin-top: 14px; }
.archive-disclaimer { margin-top: 18px; color: var(--gray); font-size: 12px; line-height: 1.7; }
@media (max-width: 720px) {
  .detail-title { font-size: 21px; }
  .related-list { grid-template-columns: 1fr; }
}
</style>
