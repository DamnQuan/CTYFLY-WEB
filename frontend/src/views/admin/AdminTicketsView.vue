<script setup>
import { onMounted, ref } from 'vue';
import { api } from '../../api.js';
import { fmtTime, TICKET_STATUS, showToast } from '../../utils.js';
import UserAvatar from '../../components/UserAvatar.vue';

const tickets = ref([]);
const loading = ref(true);
const viewing = ref(null);
const replies = ref([]);
const replyText = ref('');
const replying = ref(false);   // 回复防重复提交

async function load() {
  loading.value = true;
  try {
    const data = await api.get('/api/tickets?scope=all');
    tickets.value = data.tickets;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);

async function open(t) {
  try {
    const data = await api.get(`/api/tickets/${t.id}`);
    viewing.value = data.ticket;
    replies.value = data.replies;
  } catch (err) {
    showToast(err.message);
  }
}

async function send() {
  if (replying.value) return;
  if (!replyText.value.trim()) return;
  replying.value = true;
  try {
    await api.post(`/api/tickets/${viewing.value.id}/reply`, { content: replyText.value });
    replyText.value = '';
    open(viewing.value);
    load();
  } catch (err) {
    showToast(err.message);
  } finally {
    replying.value = false;
  }
}

async function close(t, status) {
  try {
    await api.patch(`/api/tickets/${t.id}/status`, { status });
    if (viewing.value?.id === t.id) viewing.value.status = status;
    load();
    showToast(status === 'closed' ? '工单已关闭' : '工单已重开');
  } catch (err) {
    showToast(err.message);
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">工单管理</div>
      <div class="page-desc">以客服身份回复用户工单，处理完成后关闭</div>
    </div>

    <div v-if="viewing" class="glass card" style="margin-bottom: 16px">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px">
        <div>
          <div class="card-title" style="margin-bottom: 2px">{{ viewing.title }}</div>
          <div class="card-sub">{{ viewing.category }} · 由 {{ viewing.username }}，CID {{ viewing.cid }}提交</div>
        </div>
        <div style="display: flex; gap: 8px; align-items: center">
          <span class="tag" :class="TICKET_STATUS[viewing.status]?.cls">{{ TICKET_STATUS[viewing.status]?.text }}</span>
          <button v-if="viewing.status !== 'closed'" class="btn btn-ghost btn-sm" @click="close(viewing, 'closed')">关闭</button>
          <button v-else class="btn btn-ghost btn-sm" @click="close(viewing, 'open')">重开</button>
          <button class="btn btn-ghost btn-sm" @click="viewing = null">返回</button>
        </div>
      </div>
      <div style="max-height: 360px; overflow-y: auto">
        <div v-for="r in replies" :key="r.id" class="chat-row" :class="{ mine: r.is_staff }">
          <UserAvatar class="chat-avatar" :user="r" :size="34" />
          <div>
            <div class="chat-meta">
              {{ r.username }}
              <span v-if="r.is_staff" class="tag tag-blue" style="margin-left: 4px">客服</span>
              · {{ fmtTime(r.created_at) }}
            </div>
            <div class="chat-bubble">{{ r.content }}</div>
          </div>
        </div>
      </div>
      <div v-if="viewing.status !== 'closed'" class="input-row" style="margin-top: 10px">
        <input v-model="replyText" class="input" placeholder="以客服身份回复…" @keyup.enter="send" />
        <button class="btn btn-primary" :disabled="replying" @click="send">
          {{ replying ? '发送中…' : '回复' }}
        </button>
      </div>
    </div>

    <div class="glass card">
      <div v-if="loading" class="loading">加载中…</div>
      <template v-else-if="tickets.length">
        <div v-for="t in tickets" :key="t.id" class="list-item" style="cursor: pointer" @click="open(t)">
          <div class="list-main">
            <div class="list-title"><span class="tag" style="margin-right: 8px">{{ t.category }}</span>{{ t.title }}</div>
            <div class="list-sub">#{{ t.id }} · {{ t.username }}，CID {{ t.cid }}· 更新于 {{ fmtTime(t.updated_at) }}</div>
          </div>
          <span class="tag" :class="TICKET_STATUS[t.status]?.cls">{{ TICKET_STATUS[t.status]?.text }}</span>
        </div>
      </template>
      <div v-else class="empty">暂无工单</div>
    </div>
  </div>
</template>
