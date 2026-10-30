<script setup>
/**
 * 事故记录：上报 + 我的记录 + 调查时间线
 *
 * 组件红线：事故等级、飞行阶段用自研 SelectMenu，替代 <select>，
 * 发生时间用 DatePicker 的 datetime 模式，替代 <input type="datetime-local">，
 * 提交确认走 confirmModal —— 页面没有任何原生表单控件。
 */
import { computed, onMounted, reactive, ref } from 'vue';
import { api } from '../api.js';
import { confirmModal } from '../modal.js';
import { showToast } from '../utils.js';
import Icon from '../components/Icon.vue';
import SelectMenu from '../components/SelectMenu.vue';
import DatePicker from '../components/DatePicker.vue';

const loading = ref(true);
const submitting = ref(false);
const items = ref([]);
const meta = ref({ severities: {}, phases: [], statuses: {}, isStaff: false });
const detail = ref(null);
const showForm = ref(false);
const page = ref(1);
const total = ref(0);
const pageSize = ref(15);

const form = reactive({
  severity: 'incident',
  phase: '',
  occurredAt: '',
  flightNo: '',
  dep: '',
  arr: '',
  location: '',
  summary: '',
  detail: '',
});

const severityOptions = computed(() =>
  Object.entries(meta.value.severities || {}).map(([value, label]) => ({ value, label })),
);
const phaseOptions = computed(() => [
  { value: '', label: '未选择' },
  ...(meta.value.phases || []).map((p) => ({ value: p, label: p })),
]);
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)));

async function load() {
  loading.value = true;
  try {
    const data = await api.get(`/api/incidents?page=${page.value}`);
    items.value = data.items || [];
    total.value = data.total || 0;
    pageSize.value = data.pageSize || 15;
    meta.value = {
      severities: data.severities || {},
      phases: data.phases || [],
      statuses: data.statuses || {},
      isStaff: !!data.isStaff,
    };
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}

onMounted(load);

function statusTag(s) {
  if (s === 'open') return 'tag-red';
  if (s === 'investigating') return 'tag-orange';
  return 'tag-green';
}
function severityTag(s) {
  if (s === 'hull_loss' || s === 'accident') return 'tag-red';
  if (s === 'serious') return 'tag-orange';
  return 'tag-blue';
}

async function submit() {
  if (form.summary.trim().length < 5) {
    showToast('请至少用 5 个字描述发生了什么');
    return;
  }
  const label = meta.value.severities[form.severity] || form.severity;
  const ok = await confirmModal({
    title: '提交事故报告',
    message: `将按「${label}」上报。上报会记录提交时的 IP 与浏览器信息用于事后溯源，提交后不可删除。`,
    confirmText: '确认提交',
  });
  if (!ok) return;
  submitting.value = true;
  try {
    const data = await api.post('/api/incidents', {
      severity: form.severity,
      phase: form.phase,
      occurredAt: form.occurredAt,
      flightNo: form.flightNo.toUpperCase(),
      dep: form.dep.toUpperCase(),
      arr: form.arr.toUpperCase(),
      location: form.location,
      summary: form.summary,
      detail: form.detail,
    });
    showToast(data.message || '已提交');
    showForm.value = false;
    form.summary = '';
    form.detail = '';
    await load();
  } catch (err) {
    showToast(err.message);
  }
  submitting.value = false;
}

async function openDetail(row) {
  try {
    const data = await api.get(`/api/incidents/${row.id}`);
    detail.value = data.incident;
  } catch (err) {
    showToast(err.message);
  }
}

async function changePage(delta) {
  const next = Math.min(totalPages.value, Math.max(1, page.value + delta));
  if (next === page.value) return;
  page.value = next;
  await load();
}
</script>

<template>
  <div class="page" style="max-width: clamp(720px, 58vw, 1100px)">
    <div class="page-header">
      <div class="page-title">事故记录</div>
      <div class="page-desc">
        飞行事故/事件上报与调查跟踪 · 上报时服务端自动记录 IP 与 UA，requestinfo 溯源，证据链长期留存
      </div>
    </div>

    <div class="glass card">
      <div class="inc-toolbar">
        <div class="card-sub" style="margin: 0">
          我的记录 {{ total }} 条<template v-if="meta.isStaff">含全部用户，可查看溯源字段</template>
        </div>
        <div style="display: flex; gap: 8px">
          <button class="btn btn-ghost btn-sm" @click="load">刷新</button>
          <button class="btn btn-primary btn-sm" @click="showForm = !showForm">
            {{ showForm ? '收起上报' : '上报事故' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="showForm" class="glass card" style="margin-top: 16px">
      <div class="card-title"><Icon name="shield" :size="16" /> 上报飞行事故 / 事件</div>
      <div class="inc-form">
        <div class="field">
          <div class="label">事故等级</div>
          <SelectMenu v-model="form.severity" :options="severityOptions" />
        </div>
        <div class="field">
          <div class="label">飞行阶段</div>
          <SelectMenu v-model="form.phase" :options="phaseOptions" />
        </div>
        <div class="field">
          <div class="label">发生时间</div>
          <DatePicker v-model="form.occurredAt" mode="datetime" placeholder="选择发生时间" />
        </div>
        <div class="field">
          <div class="label">航班号</div>
          <input v-model="form.flightNo" class="input" maxlength="16" placeholder="如 CTY900" />
        </div>
        <div class="field">
          <div class="label">起飞机场</div>
          <input v-model="form.dep" class="input" maxlength="4" placeholder="ICAO" />
        </div>
        <div class="field">
          <div class="label">落地机场</div>
          <input v-model="form.arr" class="input" maxlength="4" placeholder="ICAO" />
        </div>
        <div class="field">
          <div class="label">事发地点，可选</div>
          <input v-model="form.location" class="input" maxlength="64" placeholder="如 ZSPD 16R 跑道" />
        </div>
      </div>
      <div class="field">
        <div class="label">概述</div>
        <input v-model="form.summary" class="input" maxlength="200" placeholder="一句话说明发生了什么，至少 5 字" />
      </div>
      <div class="field">
        <div class="label">详细经过，可选</div>
        <textarea v-model="form.detail" class="input" rows="4" maxlength="2000" placeholder="时间线、动作、人员与飞机状况"></textarea>
      </div>
      <div class="modal-actions">
        <button class="btn btn-ghost" @click.prevent="showForm = false">取消</button>
        <button class="btn btn-primary" :disabled="submitting" @click.prevent="submit">
          {{ submitting ? '提交中…' : '提交报告' }}
        </button>
      </div>
    </div>

    <div class="glass card" style="margin-top: 16px">
      <div class="card-title"><Icon name="file" :size="16" /> 事故档案</div>
      <div v-if="loading" class="loading">加载中…</div>
      <div v-else-if="!items.length" class="empty">
        <div class="empty-icon"><Icon name="shield" :size="22" /></div>
        <div>暂无事故记录，这是好事</div>
      </div>
      <div v-else>
        <div v-for="row in items" :key="row.id" class="list-item inc-item" @click="openDetail(row)">
          <div class="list-main">
            <div class="list-title">
              <span class="tag" :class="severityTag(row.severity)" style="margin-right: 8px">{{ row.severityLabel }}</span>
              {{ row.report_no }}
              <span class="tag" :class="statusTag(row.status)" style="margin-left: 8px">{{ row.statusLabel }}</span>
            </div>
            <div class="list-sub">{{ row.summary }}</div>
            <div class="list-sub">
              {{ row.dep || '—' }} → {{ row.arr || '—' }}
              <template v-if="row.flight_no"> · {{ row.flight_no }}</template>
              <template v-if="row.phase"> · {{ row.phase }}</template>
              · 提交 {{ row.created_at?.slice(0, 16) }}
            </div>
            <div v-if="meta.isStaff && row.trace" class="list-sub" style="opacity: .8">
              溯源：{{ row.trace.ip }} · {{ row.trace.uaLabel }}
              <span v-if="row.trace.uaBot" class="tag tag-red" style="margin-left: 6px">脚本/爬虫</span>
              · 进程 {{ row.trace.pid }}
            </div>
          </div>
          <Icon name="chevron" :size="14" class="inc-arrow" />
        </div>
      </div>
      <div v-if="totalPages > 1" class="inc-pager">
        <button class="btn btn-ghost btn-sm" :disabled="page <= 1" @click="changePage(-1)">上一页</button>
        <span class="card-sub" style="margin: 0">{{ page }} / {{ totalPages }}</span>
        <button class="btn btn-ghost btn-sm" :disabled="page >= totalPages" @click="changePage(1)">下一页</button>
      </div>
    </div>

    <div v-if="detail" class="glass card inc-detail" style="margin-top: 16px">
      <div class="card-title">
        <Icon name="shield" :size="16" /> {{ detail.report_no }} · {{ detail.severityLabel }}
        <button class="btn btn-ghost btn-sm" style="margin-left: auto" @click="detail = null">关闭</button>
      </div>
      <div class="inc-detail-grid">
        <div class="inc-kv"><span>状态</span><b>{{ detail.statusLabel }}</b></div>
        <div class="inc-kv"><span>航班</span><b>{{ detail.flight_no || '—' }}</b></div>
        <div class="inc-kv"><span>航段</span><b>{{ detail.dep || '—' }} → {{ detail.arr || '—' }}</b></div>
        <div class="inc-kv"><span>阶段</span><b>{{ detail.phase || '—' }}</b></div>
        <div class="inc-kv"><span>发生时间</span><b>{{ detail.occurred_at || '—' }}</b></div>
        <div class="inc-kv"><span>地点</span><b>{{ detail.location || '—' }}</b></div>
      </div>
      <div class="inc-summary">{{ detail.summary }}</div>
      <div v-if="detail.detail" class="inc-text">{{ detail.detail }}</div>
      <div v-if="detail.conclusion" class="inc-conclusion">调查结论：{{ detail.conclusion }}</div>
      <div v-if="detail.trace" class="inc-trace">
        上报溯源 · IP {{ detail.trace.ip }} · {{ detail.trace.uaLabel }}
        <template v-if="detail.trace.uaBot"> · 判定为脚本/爬虫</template>
        · 进程 {{ detail.trace.pid }}
        <div class="inc-ua">{{ detail.trace.ua }}</div>
      </div>
      <div class="side-section" style="margin-top: 14px">处置时间线</div>
      <div v-for="u in detail.updates" :key="u.id" class="inc-update">
        <span class="inc-dot"></span>
        <div>
          <div class="list-title" style="font-size: 13px">
            {{ u.action === 'report' ? '提交上报' : (u.action === 'investigate' ? '受理调查' : (u.action === 'close' ? '结案' : '备注')) }}
            · {{ u.actor_name }}
          </div>
          <div class="list-sub">{{ u.note || '无备注' }} · {{ u.created_at }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.inc-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.inc-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0 16px; }
.inc-item { cursor: pointer; align-items: flex-start; }
.inc-arrow { color: var(--gray); flex-shrink: 0; margin-top: 6px; }
.inc-pager { display: flex; align-items: center; justify-content: center; gap: 14px; margin-top: 12px; }
.inc-detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px 16px; margin: 10px 0; }
.inc-kv { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; }
.inc-kv span { color: var(--text-2); }
.inc-summary { font-size: 14px; font-weight: 600; margin: 6px 0; }
.inc-text { font-size: 13px; color: var(--text-2); line-height: 1.7; white-space: pre-wrap; }
.inc-conclusion {
  margin-top: 10px; padding: 10px 12px; border-radius: var(--radius-sm);
  background: var(--surface); font-size: 13px;
}
.inc-trace {
  margin-top: 12px; padding: 10px 12px; border-radius: var(--radius-sm);
  background: var(--surface); font-size: 12px; color: var(--text-2);
}
.inc-ua { margin-top: 4px; word-break: break-all; opacity: 0.8; }
.inc-update { display: flex; gap: 10px; padding: 8px 0; }
.inc-dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--blue);
  margin-top: 6px; flex-shrink: 0;
}
</style>
