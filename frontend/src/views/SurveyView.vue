<script setup>
/**
 * 平台发展问卷，公开路由 /docs
 *
 * 题目不写死在前端：挂载时向 /api/survey/schema 取题，
 * 单选、多选、评分、文本四种题型按同一套结构渲染，
 * 服务端改题或加题时这个页面不用改代码。
 */
import { computed, onMounted, reactive, ref } from 'vue';
import { api } from '../api.js';
import { useAuthStore } from '../stores/auth.js';
import { showToast } from '../utils.js';
import Icon from '../components/Icon.vue';
import PoWCaptcha from '../components/PoWCaptcha.vue';
import logoMark from '../assets/logo-mark.png';

const auth = useAuthStore();
const loading = ref(true);
const loadError = ref('');
const submitting = ref(false);
const submitted = ref(false);
const submittedTitle = ref('已收到你的反馈');
const schema = ref({ intro: '', questions: [], version: 0 });
const answers = reactive({});
const nickname = ref('');
const contact = ref('');
const powRef = ref(null);

const identity = computed(() => {
  if (!auth.isLoggedIn || !auth.user) return '';
  return `${auth.user.username} · CID ${auth.user.cid}`;
});

function initAnswers(questions) {
  for (const q of questions) {
    if (q.type === 'multi') answers[q.key] = [];
    else if (q.type === 'rating') answers[q.key] = 0;
    else answers[q.key] = '';
  }
}

async function loadSchema() {
  loading.value = true;
  loadError.value = '';
  try {
    const data = await api.get('/api/survey/schema');
    schema.value = data;
    initAnswers(data.questions || []);
    // 服务端按账号或匿名浏览器标识判断，已经交过就不再展示表单
    if (data.submitted) {
      submittedTitle.value = '你已经提交过问卷';
      submitted.value = true;
    }
  } catch (err) {
    loadError.value = err.message;
  } finally {
    loading.value = false;
  }
}
onMounted(loadSchema);

function pickSingle(q, value) {
  answers[q.key] = value;
}

function toggleMulti(q, value) {
  const list = Array.isArray(answers[q.key]) ? answers[q.key] : [];
  const index = list.indexOf(value);
  if (index >= 0) {
    list.splice(index, 1);
  } else {
    if (q.max && list.length >= q.max) {
      showToast(`「${q.title}」最多选择 ${q.max} 项`);
      return;
    }
    list.push(value);
  }
  answers[q.key] = [...list];
}

function isPicked(q, value) {
  const value0 = answers[q.key];
  return q.type === 'multi' ? value0.includes(value) : value0 === value;
}

function validate() {
  for (const q of schema.value.questions) {
    const value = answers[q.key];
    if (q.required) {
      if (q.type === 'multi' && (!value || value.length < (q.min || 1))) {
        return `请完成「${q.title}」`;
      }
      if (q.type !== 'multi' && !value) return `请完成「${q.title}」`;
    }
    if (q.type === 'text' && value) {
      if (q.minLength && value.trim().length < q.minLength) {
        return `「${q.title}」至少填写 ${q.minLength} 个字`;
      }
      if (value.length > q.maxLength) {
        return `「${q.title}」最多填写 ${q.maxLength} 个字`;
      }
    }
  }
  return '';
}

async function submit() {
  if (submitting.value) return;
  const message = validate();
  if (message) {
    showToast(message);
    return;
  }
  submitting.value = true;
  try {
    const powToken = await powRef.value.ensure();
    await api.post('/api/survey', {
      answers,
      nickname: nickname.value.trim(),
      contact: contact.value.trim(),
    }, { headers: { 'X-PoW-Token': powToken } });
    submitted.value = true;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (err) {
    if (err.status === 409) {
      // 服务端判定已经交过，直接切到完成态，不再提示错误
      submittedTitle.value = '你已经提交过问卷';
      submitted.value = true;
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }
    showToast(err.message);
    powRef.value?.invalidate();
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="page survey-page">
    <div class="page-header">
      <div class="survey-head">
        <img class="survey-logo" :src="logoMark" alt="" width="42" height="42" />
        <div>
          <div class="page-title">平台发展问卷</div>
          <div class="page-desc">无需登录，两分钟说说你对平台发展的想法</div>
        </div>
      </div>
    </div>

    <div v-if="loading" class="glass card survey-loading">
      <span class="survey-spinner" aria-hidden="true"></span>
      正在加载问卷…
    </div>

    <div v-else-if="loadError" class="glass card survey-loading">
      <div>问卷暂时无法加载：{{ loadError }}</div>
      <button class="btn btn-ghost btn-sm" type="button" @click="loadSchema">重新加载</button>
    </div>

    <div v-else-if="submitted" class="glass card survey-done">
      <div class="survey-done-icon"><Icon name="check" :size="30" /></div>
      <h2>{{ submittedTitle }}</h2>
      <p>感谢你花时间参与，平台会认真阅读每一条建议，按大家真实的需求持续迭代。每人限填一份。</p>
      <div class="survey-done-actions">
        <router-link class="btn btn-primary" to="/">返回首页</router-link>
      </div>
    </div>

    <form v-else class="glass card survey-card" @submit.prevent="submit">
      <p class="survey-intro">{{ schema.intro }}</p>
      <div v-if="identity" class="survey-identity">
        <Icon name="user" :size="15" />
        当前身份：{{ identity }}
      </div>
      <div v-else class="survey-identity">
        <Icon name="user" :size="15" />
        无需登录，可直接匿名提交；留下联系方式方便我们回访
      </div>

      <section
        v-for="(q, index) in schema.questions"
        :key="q.key"
        class="survey-question"
      >
        <div class="survey-question-head">
          <span class="survey-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <div>
            <div class="survey-title">
              {{ q.title }}
              <span v-if="q.required" class="survey-required">必填</span>
            </div>
            <div v-if="q.hint" class="survey-hint">{{ q.hint }}</div>
          </div>
        </div>

        <div v-if="q.type === 'single'" class="survey-options">
          <button
            v-for="opt in q.options"
            :key="opt.value"
            class="survey-chip"
            :class="{ picked: isPicked(q, opt.value) }"
            type="button"
            @click="pickSingle(q, opt.value)"
          >
            {{ opt.label }}
          </button>
        </div>

        <div v-else-if="q.type === 'multi'" class="survey-options">
          <button
            v-for="opt in q.options"
            :key="opt.value"
            class="survey-chip"
            :class="{ picked: isPicked(q, opt.value) }"
            type="button"
            @click="toggleMulti(q, opt.value)"
          >
            {{ opt.label }}
          </button>
          <span class="survey-count">已选 {{ (answers[q.key] || []).length }} 项</span>
        </div>

        <div v-else-if="q.type === 'rating'" class="survey-rating">
          <button
            v-for="score in 5"
            :key="score"
            class="survey-score"
            :class="{ picked: answers[q.key] === score }"
            type="button"
            :aria-label="`${score} 分`"
            @click="answers[q.key] = score"
          >
            {{ score }}
          </button>
          <span class="survey-rating-label">
            {{ answers[q.key] ? `${answers[q.key]} 分` : '请选择 1 到 5 分' }}
          </span>
          <span class="survey-rating-ends">{{ q.lowLabel }} · {{ q.highLabel }}</span>
        </div>

        <div v-else-if="q.type === 'text'" class="survey-text">
          <textarea
            v-model="answers[q.key]"
            class="input survey-textarea"
            :placeholder="q.placeholder"
            :maxlength="q.maxLength"
            rows="4"
          ></textarea>
          <div class="survey-counter">
            {{ (answers[q.key] || '').length }} / {{ q.maxLength }}
            <span v-if="q.minLength">至少 {{ q.minLength }} 字</span>
          </div>
        </div>
      </section>

      <section class="survey-question survey-contact">
        <div class="survey-question-head">
          <span class="survey-index">附</span>
          <div>
            <div class="survey-title">留个称呼与联系方式</div>
            <div class="survey-hint">选填，仅用于必要时回访，不会公开</div>
          </div>
        </div>
        <div class="survey-contact-row">
          <input v-model="nickname" class="input" maxlength="40" placeholder="怎么称呼你" />
          <input v-model="contact" class="input" maxlength="120" placeholder="QQ / 邮箱 / 其他联系方式" />
        </div>
      </section>

      <div class="survey-submit">
        <PoWCaptcha ref="powRef" />
        <button class="btn btn-primary btn-lg" type="submit" :disabled="submitting">
          {{ submitting ? '提交中…' : '提交问卷' }}
        </button>
        <span class="survey-submit-hint">答案只用于产品改进，不会公开展示</span>
      </div>
    </form>
  </div>
</template>

<style scoped>
.survey-page { max-width: 820px; padding-top: 20px; }
.survey-head { display: flex; align-items: center; gap: 14px; }
.survey-logo {
  border-radius: 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  padding: 4px;
}
.survey-card { padding: 28px 30px 32px; }
.survey-loading {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 26px 30px;
  color: var(--text-2);
  font-size: 14px;
}
.survey-loading .btn { margin-left: auto; }
.survey-spinner {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid color-mix(in srgb, var(--blue) 25%, transparent);
  border-top-color: var(--blue);
  animation: survey-spin 0.7s linear infinite;
}
@keyframes survey-spin { to { transform: rotate(360deg); } }
.survey-intro {
  margin: 0 0 18px;
  color: var(--text-2);
  font-size: 14px;
  line-height: 1.8;
}
.survey-identity {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 22px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-2);
  font-size: 12.5px;
}
.survey-question {
  padding: 20px 0;
  border-top: 1px solid var(--border);
}
.survey-question-head { display: flex; gap: 12px; align-items: flex-start; }
.survey-index {
  flex: none;
  width: 28px;
  height: 28px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: var(--surface);
  color: var(--blue);
  font-size: 12px;
  font-weight: 700;
}
.survey-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text);
  font-size: 15px;
  font-weight: 600;
  line-height: 1.5;
}
.survey-required {
  padding: 1px 6px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--blue) 12%, transparent);
  color: var(--blue);
  font-size: 11px;
  font-weight: 500;
}
.survey-hint { margin-top: 3px; color: var(--gray); font-size: 12.5px; }
.survey-options {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  margin: 14px 0 0 40px;
}
.survey-chip {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-2);
  border-radius: 999px;
  padding: 8px 15px;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.16s ease;
}
.survey-chip:hover { border-color: color-mix(in srgb, var(--blue) 45%, var(--border)); color: var(--text); }
.survey-chip.picked {
  border-color: var(--blue);
  background: color-mix(in srgb, var(--blue) 12%, var(--surface));
  color: var(--blue);
  font-weight: 600;
}
.survey-count { align-self: center; color: var(--gray); font-size: 12px; }
.survey-rating {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 14px 0 0 40px;
  flex-wrap: wrap;
}
.survey-score {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-2);
  font: inherit;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.16s ease;
}
.survey-score.picked {
  border-color: var(--blue);
  background: var(--blue);
  color: #fff;
  font-weight: 700;
}
.survey-rating-label { color: var(--text-2); font-size: 12.5px; }
.survey-rating-ends { color: var(--gray); font-size: 12px; }
.survey-text { margin: 14px 0 0 40px; }
.survey-textarea { resize: vertical; min-height: 96px; line-height: 1.7; }
.survey-counter {
  margin-top: 6px;
  display: flex;
  justify-content: space-between;
  color: var(--gray);
  font-size: 12px;
}
.survey-contact-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin: 14px 0 0 40px;
}
.survey-submit {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-top: 24px;
  border-top: 1px solid var(--border);
  flex-wrap: wrap;
}
.survey-submit-hint { color: var(--gray); font-size: 12.5px; }
.survey-done { padding: 46px 30px; text-align: center; }
.survey-done-icon {
  width: 58px;
  height: 58px;
  margin: 0 auto 18px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: color-mix(in srgb, var(--blue) 14%, transparent);
  color: var(--blue);
}
.survey-done h2 { margin: 0 0 8px; color: var(--text); font-size: 20px; }
.survey-done p { margin: 0 0 22px; color: var(--text-2); font-size: 14px; }
.survey-done-actions { display: flex; justify-content: center; gap: 12px; }
@media (max-width: 640px) {
  .survey-card { padding: 22px 18px 26px; }
  .survey-options, .survey-rating, .survey-text, .survey-contact-row { margin-left: 0; }
  .survey-contact-row { grid-template-columns: 1fr; }
  .survey-submit { align-items: stretch; }
  .survey-submit .btn { width: 100%; }
}
</style>
