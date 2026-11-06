<script setup>
/**
 * IP 黑名单 / 白名单管理，2026-10-10 新增，见运维手册 §6.8
 *
 * 为什么要有这个页面：banned_ips 原来只能手工 SQL 维护 —— 脚本/爬虫自动封禁一旦
 * 误伤，动态 IP 被回收后再分配给真实用户，既无处可看也无人能解。这里补上：
 * 黑名单列表，原因/来源/到期，一键解封、手动封禁、白名单，优先于黑名单。
 */
import { computed, onMounted, ref } from 'vue';
import { api } from '../../api.js';
import { showToast } from '../../utils.js';
import Icon from '../../components/Icon.vue';
import SelectMenu from '../../components/SelectMenu.vue';

const loading = ref(false);
const bans = ref([]);
const whitelist = ref([]);
const q = ref('');

const form = ref({ ip: '', reason: '', days: 0, note: '' });
const submitting = ref(false);
const wl = ref({ ip: '', note: '' });
const wlSubmitting = ref(false);

const dayOptions = [
  { value: 0, label: '永久' },
  { value: 1, label: '1 天' },
  { value: 7, label: '7 天' },
  { value: 30, label: '30 天' },
  { value: 90, label: '90 天' },
  { value: 365, label: '365 天' },
];

const permanentCount = computed(() => bans.value.filter((b) => b.permanent).length);
const autoCount = computed(() => bans.value.filter((b) => b.source === 'auto').length);

async function load() {
  loading.value = true;
  try {
    const data = await api.get(`/api/admin/banned-ips?q=${encodeURIComponent(q.value)}`);
    bans.value = data.bans || [];
    whitelist.value = data.whitelist || [];
  } catch (err) {
    showToast(err.message);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

async function unban(ip) {
  if (!window.confirm(`确定要解封 ${ip} 吗？解除后该 IP 可以再次注册 / 登录。`)) return;
  try {
    const r = await api.delete(`/api/admin/banned-ips/${encodeURIComponent(ip)}`);
    showToast(r.message || '已解封');
    await load();
  } catch (err) {
    showToast(err.message);
  }
}

async function submitBan() {
  if (!form.value.ip.trim()) return showToast('请填写要封禁的 IP');
  submitting.value = true;
  try {
    const r = await api.post('/api/admin/banned-ips', {
      ip: form.value.ip.trim(),
      reason: form.value.reason.trim(),
      days: Number(form.value.days) || 0,
      note: form.value.note.trim(),
    });
    showToast(r.message || '已封禁');
    form.value = { ip: '', reason: '', days: 0, note: '' };
    await load();
  } catch (err) {
    showToast(err.message);
  } finally {
    submitting.value = false;
  }
}

async function addWhitelist() {
  if (!wl.value.ip.trim()) return showToast('请填写要加白的 IP');
  wlSubmitting.value = true;
  try {
    const r = await api.post('/api/admin/banned-ips/whitelist', {
      ip: wl.value.ip.trim(),
      note: wl.value.note.trim(),
    });
    showToast(r.message || '已加入白名单');
    wl.value = { ip: '', note: '' };
    await load();
  } catch (err) {
    showToast(err.message);
  } finally {
    wlSubmitting.value = false;
  }
}

async function removeWhitelist(ip) {
  try {
    const r = await api.delete(`/api/admin/banned-ips/whitelist/${encodeURIComponent(ip)}`);
    showToast(r.message || '已移出白名单');
    await load();
  } catch (err) {
    showToast(err.message);
  }
}

/** 到期时间显示：永久 / 剩余天数 */
function expiryText(b) {
  if (b.permanent) return '永久';
  const end = new Date(String(b.expiresAt).replace(' ', 'T'));
  const days = Math.ceil((end - new Date()) / 86400000);
  return days > 0 ? `${b.expiresAt}，剩 ${days} 天` : `${b.expiresAt}，已过期`;
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>IP 黑名单</h1>
        <p class="page-desc">
          脚本/爬虫自动封禁与手动封禁的 IP。自动封禁默认 90 天到期，动态 IP 复用不会永久误伤；
          白名单优先于黑名单。行为异常检测只写入风险事件、不自动封禁，留痕见「审计日志」。
        </p>
      </div>
      <button class="btn btn-ghost btn-sm" :disabled="loading" @click="load">
        <Icon name="radar" :size="14" /> 刷新
      </button>
    </div>

    <div class="grid grid-4" style="margin-bottom: 16px">
      <div class="stat">
        <div class="stat-num">{{ bans.length }}</div>
        <div class="stat-label">当前封禁</div>
      </div>
      <div class="stat">
        <div class="stat-num">{{ autoCount }}</div>
        <div class="stat-label">自动封禁</div>
      </div>
      <div class="stat">
        <div class="stat-num">{{ permanentCount }}</div>
        <div class="stat-label">永久封禁</div>
      </div>
      <div class="stat">
        <div class="stat-num">{{ whitelist.length }}</div>
        <div class="stat-label">白名单</div>
      </div>
    </div>

    <div class="glass card">
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap">
        <div class="card-title" style="margin: 0">封禁列表</div>
        <div class="input-row" style="max-width: 340px">
          <input v-model="q" class="input" placeholder="搜索 IP 或原因" @keyup.enter="load" />
          <button class="btn btn-primary btn-sm" @click="load">搜索</button>
        </div>
      </div>

      <div v-if="loading" class="loading">加载中…</div>
      <div v-else-if="!bans.length" style="padding: 14px 0; color: var(--gray); font-size: 13.5px">
        当前没有封禁记录。发现脚本/爬虫时，注册/登录入口会自动写入这里。
      </div>
      <div v-else class="table-wrap" style="margin-top: 12px">
        <table class="table">
          <thead>
            <tr>
              <th>IP</th>
              <th>原因</th>
              <th>来源</th>
              <th>封禁时间</th>
              <th>到期时间</th>
              <th style="width: 90px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in bans" :key="b.ip">
              <td><code>{{ b.ip }}</code></td>
              <td>
                {{ b.reason }}
                <div v-if="b.note" style="font-size: 12px; color: var(--gray)">{{ b.note }}</div>
              </td>
              <td>
                <span class="tag" :class="b.source === 'auto' ? 'tag-orange' : 'tag-blue'">
                  {{ b.source === 'auto' ? '自动' : '手动' }}
                </span>
              </td>
              <td style="color: var(--gray)">{{ b.createdAt }}</td>
              <td style="color: var(--gray)">{{ expiryText(b) }}</td>
              <td>
                <button class="btn btn-ghost btn-sm" @click="unban(b.ip)">解封</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="glass card" style="margin-top: 16px">
      <div class="card-title">手动封禁</div>
      <div class="grid grid-4">
        <div class="field">
          <label class="label">IP 地址</label>
          <input v-model="form.ip" class="input" placeholder="例如 203.0.113.7" />
        </div>
        <div class="field">
          <label class="label">原因</label>
          <input v-model="form.reason" class="input" placeholder="例如 批量注册小号" />
        </div>
        <div class="field">
          <label class="label">期限</label>
          <SelectMenu v-model="form.days" :options="dayOptions" />
        </div>
        <div class="field">
          <label class="label">备注（可选）</label>
          <input v-model="form.note" class="input" placeholder="留给自己看的说明" />
        </div>
      </div>
      <button class="btn btn-primary btn-sm" :disabled="submitting" style="margin-top: 14px" @click="submitBan">
        {{ submitting ? '提交中…' : '封禁该 IP' }}
      </button>
    </div>

    <div class="glass card" style="margin-top: 16px">
      <div class="card-title">白名单（优先于黑名单）</div>
      <div style="font-size: 13px; color: var(--gray); margin-bottom: 10px">
        误封后可把 IP 加白；加白会自动清除该 IP 的黑名单记录。办公室固定出口、服务器回连地址适合加白。
      </div>
      <div class="input-row" style="max-width: 560px">
        <input v-model="wl.ip" class="input" placeholder="IP 地址" />
        <input v-model="wl.note" class="input" placeholder="备注（谁 / 为什么）" />
        <button class="btn btn-primary btn-sm" :disabled="wlSubmitting" @click="addWhitelist">加入</button>
      </div>
      <div v-if="whitelist.length" class="table-wrap" style="margin-top: 12px">
        <table class="table">
          <thead>
            <tr><th>IP</th><th>备注</th><th>添加人</th><th>添加时间</th><th style="width: 90px">操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="w in whitelist" :key="w.ip">
              <td><code>{{ w.ip }}</code></td>
              <td>{{ w.note || '—' }}</td>
              <td style="color: var(--gray)">{{ w.createdBy || '—' }}</td>
              <td style="color: var(--gray)">{{ w.createdAt }}</td>
              <td><button class="btn btn-ghost btn-sm" @click="removeWhitelist(w.ip)">移出</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else style="font-size: 13px; color: var(--gray)">白名单为空。</div>
    </div>
  </div>
</template>
