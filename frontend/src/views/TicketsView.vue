<script setup>
import { computed, ref, onMounted } from 'vue';
import { confirmModal } from '../modal.js';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../api.js';
import { useAuthStore } from '../stores/auth.js';
import { fmtTime, TICKET_STATUS, showToast } from '../utils.js';
import UserAvatar from '../components/UserAvatar.vue';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const tickets = ref([]);
const categories = ref([]);
const loading = ref(true);

// 附件约束，与后端一致
const MAX_FILE_MB = 5;
const MAX_FILES = 6;
const ALLOWED_EXT = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'pdf', 'doc', 'docx'];

// 新建工单：由子路由 /tickets/new 驱动
const showNew = computed(() => route.name === 'tickets-new');
const form = ref({ title: '', category: '其他', content: '' });
const picked = ref([]);          // 待上传文件：{ file, name, size }
const uploading = ref(false);
const creating = ref(false);     // 建单 POST 阶段防重复提交

// 当前查看的工单
const current = ref(null);
const replies = ref([]);
const replyText = ref('');
const replyFiles = ref([]);      // 回复待上传
const attachments = ref([]);     // 当前工单全部附件
const replying = ref(false);

function fmtSize(n) {
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

function kindLabel(kind) {
  return { image: '图片', pdf: 'PDF', word: 'Word' }[kind] || '文件';
}

/** 选择文件：扩展名与大小先做前端粗检，后端仍按文件头二次校验*/
function pickFiles(ev, target) {
  const files = Array.from(ev.target.files || []);
  ev.target.value = '';
  for (const f of files) {
    const ext = (f.name.split('.').pop() || '').toLowerCase();
    if (!ALLOWED_EXT.includes(ext)) {
      showToast(`「${f.name}」格式不支持，仅图片 / PDF / Word`);
      continue;
    }
    if (f.size > MAX_FILE_MB * 1024 * 1024) {
      showToast(`「${f.name}」超过 ${MAX_FILE_MB} MB`);
      continue;
    }
    if (target.value.length >= MAX_FILES) {
      showToast(`最多 ${MAX_FILES} 个附件`);
      break;
    }
    target.value.push({ file: f, name: f.name, size: f.size });
  }
}


function pickVia(ev) {
  const input = ev.currentTarget.querySelector('input[type=file]');
  if (input) input.click();
}

function removePicked(target, i) {
  target.value.splice(i, 1);
}

/** 建单/回复成功后逐个上传附件；单个失败不中断，汇总提示 */
async function uploadAll(ticketId, replyId, target) {
  if (!target.value.length) return;
  uploading.value = true;
  const failed = [];
  for (const item of target.value) {
    const fd = new FormData();
    fd.append('file', item.file);
    if (replyId) fd.append('reply_id', String(replyId));
    try {
      await api.upload(`/api/tickets/${ticketId}/attachments`, fd);
    } catch (err) {
      failed.push(`${item.name}：${err.message}`);
    }
  }
  uploading.value = false;
  target.value = [];
  if (failed.length) showToast(`部分附件上传失败：${failed.join('；')}`);
}

async function load() {
  loading.value = true;
  try {
    const data = await api.get('/api/tickets');
    tickets.value = data.tickets;
    categories.value = data.categories;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);

async function create() {
  if (creating.value || uploading.value) return;
  if (!form.value.title.trim() || !form.value.content.trim()) {
    showToast('请填写标题与问题描述');
    return;
  }
  creating.value = true;
  try {
    const data = await api.post('/api/tickets', form.value);
    await uploadAll(data.id, 0, picked);
    showToast('工单已提交');
    form.value = { title: '', category: '其他', content: '' };
    router.push('/tickets');
    load();
  } catch (err) {
    showToast(err.message);
  } finally {
    creating.value = false;
  }
}

async function openTicket(t) {
  try {
    const data = await api.get(`/api/tickets/${t.id}`);
    current.value = data.ticket;
    replies.value = data.replies;
    replyFiles.value = [];
    const att = await api.get(`/api/tickets/${t.id}/attachments`).catch(() => ({ attachments: [] }));
    attachments.value = att.attachments;
  } catch (err) {
    showToast(err.message);
  }
}

async function sendReply() {
  if (!replyText.value.trim()) return;
  replying.value = true;
  try {
    const data = await api.post(`/api/tickets/${current.value.id}/reply`, { content: replyText.value });
    replyText.value = '';
    await uploadAll(current.value.id, data.id, replyFiles);
    openTicket(current.value);
    load();
  } catch (err) {
    showToast(err.message);
  }
  replying.value = false;
}

/** 查看 / 下载附件：带鉴权取 Blob；图片与 PDF 新窗口预览，Word 直接下载 */
async function openAttachment(a) {
  try {
    const blob = await api.blob(`/api/attachments/${a.id}`);
    const url = URL.createObjectURL(blob);
    if (a.kind === 'word') {
      const link = document.createElement('a');
      link.href = url;
      link.download = a.name;
      link.click();
    } else {
      window.open(url, '_blank', 'noopener');
    }
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (err) {
    showToast(err.message);
  }
}

async function removeAttachment(a) {
  if (!(await confirmModal({ title: '删除附件', danger: true, confirmText: '删除', message: `确定要删除附件「${a.name}」吗？删除后不可恢复。` }))) return;
  try {
    await api.delete(`/api/attachments/${a.id}`);
    attachments.value = attachments.value.filter((x) => x.id !== a.id);
  } catch (err) {
    showToast(err.message);
  }
}

async function setStatus(t, status) {
  try {
    await api.patch(`/api/tickets/${t.id}/status`, { status });
    if (current.value?.id === t.id) current.value.status = status;
    load();
    showToast(status === 'closed' ? '工单已关闭' : '工单已重开');
  } catch (err) {
    showToast(err.message);
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header" style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px">
      <div>
        <div class="page-title">工单中心</div>
        <div class="page-desc">{{ showNew ? '提交工单，管理团队会尽快回复' : '你提交过的全部工单与处理进度' }}</div>
      </div>
      <router-link class="btn btn-dark" :to="showNew ? '/tickets' : '/tickets/new'">
        {{ showNew ? '返回工单历史' : '+ 提交工单' }}
      </router-link>
    </div>

    <div v-if="showNew" class="glass card">
      <div class="card-title">提交工单</div>
      <div class="field"><label class="label">标题</label><input v-model="form.title" class="input" maxlength="20" placeholder="简要描述问题" /></div>
      <div class="field">
        <label class="label">问题描述</label>
        <textarea v-model="form.content" class="textarea" rows="4" placeholder="详细描述你遇到的问题"></textarea>
      </div>
      <div class="field">
        <label class="label">附件（可选）</label>
        <label class="attach-pick" @click.prevent="pickVia($event)">
          <input type="file" multiple :accept="ALLOWED_EXT.map((e) => '.' + e).join(',')" @change="pickFiles($event, picked)" />
          选择文件
        </label>
        <span class="attach-hint">支持图片 / PDF / Word，单个不超过 {{ MAX_FILE_MB }} MB，最多 {{ MAX_FILES }} 个</span>
        <div v-for="(p, i) in picked" :key="i" class="attach-item">
          <span class="attach-name">{{ p.name }}</span>
          <span class="attach-size">{{ fmtSize(p.size) }}</span>
          <button class="attach-del" type="button" @click="removePicked(picked, i)">移除</button>
        </div>
      </div>
      <button class="btn btn-primary" :disabled="creating || uploading" @click="create">
        {{ creating ? '提交中…' : uploading ? '正在上传附件…' : '提交工单' }}
      </button>
    </div>

    <div v-if="current" class="glass card" style="margin-bottom: 16px">
      <div style="display: flex; justify-content: space-between; align-items: center">
        <div>
          <div class="card-title" style="margin-bottom: 2px">{{ current.title }}</div>
          <div class="card-sub">{{ current.category }} · 提交于 {{ fmtTime(current.created_at) }}</div>
        </div>
        <div style="display: flex; gap: 8px; align-items: center">
          <span class="tag" :class="TICKET_STATUS[current.status]?.cls">{{ TICKET_STATUS[current.status]?.text }}</span>
          <button v-if="current.status !== 'closed'" class="btn btn-ghost btn-sm" @click="setStatus(current, 'closed')">关闭工单</button>
          <button v-else class="btn btn-ghost btn-sm" @click="setStatus(current, 'open')">重开</button>
          <button class="btn btn-ghost btn-sm" @click="current = null">返回列表</button>
        </div>
      </div>
      <div style="max-height: 420px; overflow-y: auto; padding: 16px 4px 4px">
        <div v-for="r in replies" :key="r.id" class="chat-row" :class="{ mine: r.user_id === auth.user?.id }">
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
      <!-- 附件区：工单全部附件，含回复中的，主人可删除自己的-->
      <div v-if="attachments.length" class="attach-list">
        <div class="attach-title">附件（{{ attachments.length }}）</div>
        <div v-for="a in attachments" :key="a.id" class="attach-item">
          <span class="tag">{{ kindLabel(a.kind) }}</span>
          <span class="attach-name" style="cursor: pointer" @click="openAttachment(a)">{{ a.name }}</span>
          <span class="attach-size">{{ fmtSize(a.size) }}</span>
          <button class="attach-view" type="button" @click="openAttachment(a)">
            {{ a.kind === 'word' ? '下载' : '查看' }}
          </button>
          <button
            v-if="a.uploader === auth.user?.username"
            class="attach-del"
            type="button"
            @click="removeAttachment(a)"
          >删除</button>
        </div>
      </div>

      <div v-if="current.status !== 'closed'" class="input-row" style="margin-top: 10px">
        <input v-model="replyText" class="input" placeholder="输入回复内容…" @keyup.enter="sendReply" />
        <button class="btn btn-primary" :disabled="replying" @click="sendReply">发送</button>
      </div>
      <div class="attach-row">
        <label class="attach-pick" @click.prevent="pickVia($event)">
          <input type="file" multiple :accept="ALLOWED_EXT.map((e) => '.' + e).join(',')" @change="pickFiles($event, replyFiles)" />
          添加附件
        </label>
        <span v-for="(p, i) in replyFiles" :key="i" class="tag">{{ p.name }} <button class="attach-del" type="button" @click="removePicked(replyFiles, i)">×</button></span>
      </div>
    </div>

    <div v-if="!showNew" class="glass card">
      <div class="card-title">工单历史</div>
      <div v-if="loading" class="loading">加载中…</div>
      <template v-else>
        <div v-for="t in tickets" :key="t.id" class="list-item" style="cursor: pointer" @click="openTicket(t)">
          <div class="list-main">
            <div class="list-title">
              <span class="tag" style="margin-right: 8px">{{ t.category }}</span>{{ t.title }}
            </div>
            <div class="list-sub">#{{ t.id }} · 更新于 {{ fmtTime(t.updated_at) }} · {{ t.reply_count }} 条回复</div>
          </div>
          <span class="tag" :class="TICKET_STATUS[t.status]?.cls">{{ TICKET_STATUS[t.status]?.text }}</span>
        </div>
        <div v-if="!tickets.length" class="empty">
          <div>暂无工单记录</div>
          <router-link class="btn btn-primary btn-sm" to="/tickets/new">提交工单</router-link>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
/* 附件选择与列表 */
.attach-pick {
  display: inline-block;
  padding: 6px 14px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  color: var(--text-2);
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease;
}
.attach-pick:hover { border-color: var(--blue); color: var(--text); }
/* display:none 会让 label 转发的点击在部分移动端浏览器失效，
   改用视觉隐藏，仍在布局内、不可见但可交互，全平台可靠*/
.attach-pick input[type='file'] {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  overflow: hidden;
}
.attach-hint { margin-left: 10px; color: var(--gray); font-size: 12px; }
.attach-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.attach-list {
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 10px);
}
.attach-title { font-size: 13px; font-weight: 600; color: var(--text); margin-bottom: 8px; }
.attach-item {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 5px 0;
  font-size: 13px;
}
.attach-name { color: var(--text); word-break: break-all; }
.attach-name:hover { color: var(--blue); }
.attach-size { color: var(--gray); font-size: 12px; }
.attach-del {
  border: 0;
  background: transparent;
  color: var(--gray);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
}
.attach-del:hover { color: var(--danger, #e5484d); }
.attach-view {
  border: 1px solid var(--border);
  background: transparent;
  border-radius: 6px;
  color: var(--text-2);
  font-size: 12px;
  padding: 2px 10px;
  cursor: pointer;
}
.attach-view:hover { border-color: var(--blue); color: var(--blue); }
</style>
