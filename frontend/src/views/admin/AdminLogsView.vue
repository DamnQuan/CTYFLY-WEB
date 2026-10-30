<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { api } from '../../api.js';
import { fmtTime, showToast } from '../../utils.js';
import Icon from '../../components/Icon.vue';
import TrendLine from '../../components/TrendLine.vue';

const route = useRoute();
const kind = computed(() => route.meta.logKind || 'login');

const META = {
  login: { title: '登录日志', desc: '记录每次登录的账号、IP、地理位置、设备指纹与结果' },
  register: { title: '注册日志', desc: '记录每个新账号的注册来源 IP、地理位置与设备指纹' },
  network: { title: '网络日志', desc: '按接口统计访问量与错误率，覆盖全部 /api 请求' },
  audit: { title: '审计日志', desc: '记录所有用户行为、越权访问与系统事件' },
};

const loading = ref(false);
const logs = ref([]);
const total = ref(0);
const page = ref(1);
const failed = ref(0);
const q = ref('');
const days = ref(7);
const category = ref('');
const dayOptions = [
  { value: 1, label: '今天' },
  { value: 7, label: '近 7 天' },
  { value: 30, label: '近 30 天' },
];

const network = ref(null);
const categories = ref([]);
const categoryLabels = ref({});
const activeDay = ref(7);
const botFilter = ref('');          // '' | '1' | '0'
const botCount = ref(0);

const title = computed(() => META[kind.value]?.title || '日志');
const desc = computed(() => META[kind.value]?.desc || '');

async function load() {
  loading.value = true;
  try {
    if (kind.value === 'login' || kind.value === 'register') {
      const data = await api.get(
        `/api/admin/logs/${kind.value}?q=${encodeURIComponent(q.value)}&days=${days.value}&page=${page.value}&bot=${botFilter.value}`,
      );
      logs.value = data.logs;
      total.value = data.total;
      failed.value = data.failed || 0;
      botCount.value = data.botLogins || 0;
    } else if (kind.value === 'network') {
      network.value = await api.get(`/api/admin/logs/network?days=${days.value}`);
    } else {
      const data = await api.get(
        `/api/admin/logs/audit?category=${category.value}&q=${encodeURIComponent(q.value)}&days=${days.value}&page=${page.value}`,
      );
      logs.value = data.logs;
      total.value = data.total;
      categories.value = data.byCategory;
      categoryLabels.value = data.categoryLabels || {};
    }
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}

onMounted(load);
watch(kind, () => {
  logs.value = [];
  page.value = 1;
  network.value = null;
  botFilter.value = '';
  // 切换日志类型时清掉上一类的搜索词与分类筛选，避免残留条件带到新列表
  q.value = '';
  category.value = '';
  load();
});

function setBotFilter(v) {
  botFilter.value = v;
  page.value = 1;
  load();
}

function dayLabel(d) {
  return dayOptions.find((o) => o.value === d)?.label || `近 ${d} 天`;
}
function changeDays(v) {
  days.value = v;
  activeDay.value = v;
  page.value = 1;
  load();
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">{{ title }}</div>
      <div class="page-desc">{{ desc }}</div>
    </div>

    <!-- 筛选 -->
    <div class="glass card" style="margin-bottom: 16px">
      <div style="display: flex; gap: 10px; flex-wrap: wrap; align-items: center">
        <button
          v-for="o in dayOptions"
          :key="o.value"
          class="btn btn-sm"
          :class="days === o.value ? 'btn-dark' : 'btn-ghost'"
          @click="changeDays(o.value)"
        >{{ o.label }}</button>

        <template v-if="kind === 'login' || kind === 'register' || kind === 'audit'">
          <input
            v-model="q"
            class="input"
            style="max-width: 260px"
            :placeholder="kind === 'audit' ? '搜索操作人 / 动作 / 详情' : '搜索 CID / 用户名 / IP'"
            @keyup.enter="() => { page = 1; load(); }"
          />
          <button class="btn btn-primary btn-sm" @click="() => { page = 1; load(); }">搜索</button>
        </template>

        <template v-if="kind === 'login' || kind === 'register'">
          <button class="btn btn-sm" :class="botFilter === '' ? 'btn-dark' : 'btn-ghost'" @click="setBotFilter('')">全部来源</button>
          <button class="btn btn-sm" :class="botFilter === '0' ? 'btn-dark' : 'btn-ghost'" @click="setBotFilter('0')">仅浏览器</button>
          <button class="btn btn-sm" :class="botFilter === '1' ? 'btn-dark' : 'btn-ghost'" @click="setBotFilter('1')">
            仅脚本 / 爬虫，{{ botCount }}
          </button>
        </template>

        <template v-if="kind === 'audit'">
          <button class="btn btn-sm" :class="category === '' ? 'btn-dark' : 'btn-ghost'"
            @click="() => { category = ''; page = 1; load(); }">全部</button>
          <button v-for="c in categories" :key="c.category" class="btn btn-sm"
            :class="category === c.category ? 'btn-dark' : 'btn-ghost'"
            @click="() => { category = c.category; page = 1; load(); }">
            {{ categoryLabels[c.category] || c.category }}，{{ c.count }}
          </button>
        </template>
      </div>
    </div>

    <!-- 网络日志 -->
    <template v-if="kind === 'network'">
      <div v-if="loading" class="loading">加载中…</div>
      <template v-else-if="network">
        <div class="grid grid-3">
          <div class="stat"><div class="stat-num">{{ network.summary.total }}</div><div class="stat-label">{{ dayLabel(days) }}总请求量</div></div>
          <div class="stat"><div class="stat-num">{{ network.summary.errors }}</div><div class="stat-label">错误请求，4xx/5xx</div></div>
          <div class="stat"><div class="stat-num">{{ network.summary.total ? Math.round((network.summary.errors / network.summary.total) * 1000) / 10 : 0 }}%</div><div class="stat-label">错误率</div></div>
        </div>

        <div class="glass card" style="margin-top: 16px">
          <div class="card-title">每日请求量</div>
          <div v-if="!network.daily.length" class="empty">暂无数据</div>
          <TrendLine v-else :points="network.daily" />
        </div>

        <div class="glass card" style="margin-top: 16px">
          <div class="card-title">接口访问排行，Top 40</div>
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>方法</th><th>接口</th><th>请求量</th><th>错误数</th></tr></thead>
              <tbody>
                <tr v-for="p in network.topPaths" :key="p.method + p.path">
                  <td><span class="tag" :class="p.method === 'GET' ? 'tag-blue' : 'tag-orange'">{{ p.method }}</span></td>
                  <td><code style="font-size: 12px">{{ p.path }}</code></td>
                  <td>{{ p.count }}</td>
                  <td :style="p.errors ? 'color: var(--red)' : ''">{{ p.errors }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!network.topPaths.length" class="empty">暂无数据</div>
          </div>
        </div>
      </template>
    </template>

    <!-- 登录 / 注册日志 -->
    <template v-else-if="kind === 'login' || kind === 'register'">
      <div v-if="kind === 'login'" class="grid grid-4" style="margin-bottom: 16px">
        <div class="stat"><div class="stat-num">{{ total }}</div><div class="stat-label">{{ dayLabel(days) }}登录次数</div></div>
        <div class="stat"><div class="stat-num">{{ failed }}</div><div class="stat-label">失败次数</div></div>
        <div class="stat"><div class="stat-num">{{ total - failed }}</div><div class="stat-label">成功次数</div></div>
        <div class="stat"><div class="stat-num">{{ botCount }}</div><div class="stat-label">脚本 / 爬虫来源</div></div>
      </div>
      <div v-else class="grid grid-3" style="margin-bottom: 16px">
        <div class="stat"><div class="stat-num">{{ total }}</div><div class="stat-label">{{ dayLabel(days) }}注册次数</div></div>
        <div class="stat"><div class="stat-num">{{ botCount }}</div><div class="stat-label">脚本 / 爬虫来源</div></div>
        <div class="stat"><div class="stat-num">{{ total - botCount }}</div><div class="stat-label">浏览器来源</div></div>
      </div>

      <div class="glass card">
        <div v-if="loading" class="loading">加载中…</div>
        <div v-else class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>时间</th><th>账号</th><th>IP</th><th>地理位置</th><th>设备指纹</th>
                <th v-if="kind === 'register'">邮箱</th>
                <th v-if="kind === 'login'">结果</th>
                <th style="min-width: 200px">客户端</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="l in logs" :key="l.id">
                <td style="white-space: nowrap">{{ fmtTime(l.created_at) }}</td>
                <td>{{ l.username }}<div class="list-sub">CID {{ l.cid }}</div></td>
                <td>{{ l.ip || '—' }}</td>
                <td>{{ l.geo || '内网/未解析' }}</td>
                <td><code style="font-size: 11.5px">{{ l.fingerprint ? l.fingerprint.slice(0, 9) : '—' }}</code></td>
                <td v-if="kind === 'register'" style="font-size: 12.5px">{{ l.email }}</td>
                <td v-if="kind === 'login'">
                  <span :class="l.success ? 'tag tag-green' : 'tag tag-red'">{{ l.success ? '成功' : '失败' }}</span>
                  <div v-if="!l.success" class="list-sub">{{ l.reason }}</div>
                </td>
                <td>
                  <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
                    <span :class="l.ua_bot ? 'tag tag-red' : 'tag tag-green'">{{ l.ua_bot ? '脚本/爬虫' : '浏览器' }}</span>
                    <span style="font-size: 12.5px">{{ l.ua_label || '未知' }}</span>
                  </div>
                  <div class="list-sub" style="max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap" :title="l.ua">
                    {{ l.ua }}
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="!logs.length" class="empty">暂无日志</div>
        </div>
        <div v-if="total > 50" style="display: flex; gap: 10px; justify-content: center; margin-top: 14px; align-items: center">
          <button class="btn btn-ghost btn-sm" :disabled="page <= 1" @click="() => { page--; load(); }">上一页</button>
          <span class="list-sub">第 {{ page }} 页 / 共 {{ Math.ceil(total / 50) }} 页</span>
          <button class="btn btn-ghost btn-sm" :disabled="page >= Math.ceil(total / 50)" @click="() => { page++; load(); }">下一页</button>
        </div>
      </div>
    </template>

    <!-- 审计日志 -->
    <template v-else>
      <div class="glass card">
        <div v-if="loading" class="loading">加载中…</div>
        <div v-else class="table-wrap">
          <table class="table">
            <thead>
              <tr><th>时间</th><th>类别</th><th>操作人</th><th>行为</th><th>对象</th><th>详情</th><th>IP</th></tr>
            </thead>
            <tbody>
              <tr v-for="l in logs" :key="l.id">
                <td style="white-space: nowrap">{{ fmtTime(l.created_at) }}</td>
                <td><span class="tag" :class="l.category === 'risk' ? 'tag-red' : l.category === 'auth' ? 'tag-blue' : 'tag'">
                  {{ categoryLabels[l.category] || l.category }}
                </span></td>
                <td>{{ l.actor_name || '系统' }}<div class="list-sub">{{ l.actor_role || '' }}</div></td>
                <td>{{ l.action }}</td>
                <td style="font-size: 12.5px">{{ l.target_type }}<template v-if="l.target_id"> #{{ l.target_id }}</template></td>
                <td style="max-width: 320px; font-size: 12.5px">{{ l.detail }}</td>
                <td style="font-size: 12.5px">{{ l.ip || '—' }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="!logs.length" class="empty">
            <div class="empty-icon"><Icon name="shield" :size="22" /></div>
            <div>暂无审计记录</div>
          </div>
        </div>
        <div v-if="total > 50" style="display: flex; gap: 10px; justify-content: center; margin-top: 14px; align-items: center">
          <button class="btn btn-ghost btn-sm" :disabled="page <= 1" @click="() => { page--; load(); }">上一页</button>
          <span class="list-sub">第 {{ page }} 页 / 共 {{ Math.ceil(total / 50) }} 页</span>
          <button class="btn btn-ghost btn-sm" :disabled="page >= Math.ceil(total / 50)" @click="() => { page++; load(); }">下一页</button>
        </div>
      </div>
    </template>
  </div>
</template>
