<script setup>
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';
import { useAuthStore } from '../stores/auth.js';
import { getFingerprint } from '../fingerprint.js';
import { showToast } from '../utils.js';
import { useFieldFeedback } from '../fieldFeedback.js';
import Icon from '../components/Icon.vue';
import CheckBox from '../components/CheckBox.vue';
import PoWCaptcha from '../components/PoWCaptcha.vue';
import AuthSplitLayout from '../components/AuthSplitLayout.vue';
import logoMark from '../assets/logo-mark.webp';

const router = useRouter();
const auth = useAuthStore();
const agree = ref(false);

const form = ref({
  cid: '',
  username: '',
  email: '',
  qq: '',
  code: '',
  password: '',
  confirmPassword: '',
});

const cidState = ref({ checked: false, ok: false, message: '' });
const randomLeft = ref(15);
const devCode = ref('');
const codeSent = ref(false);
const countdown = ref(0);
const sending = ref(false);
const loading = ref(false);
const error = ref('');

/* 字段级校验反馈：红边 + 水平轻晃 + 提示从下方滑入，一改就收起，见 fieldFeedback.js*/
const fb = useFieldFeedback(['cid', 'username', 'email', 'code', 'qq', 'password', 'confirmPassword']);

// 工作量证明人机验证：全程静默，失败也不向用户暴露具体原因
const powRef = ref(null);

let sid = ''
onMounted(() => {
  try {
    sid = localStorage.getItem('ctyfly_reg_sid') || crypto.randomUUID()
    localStorage.setItem('ctyfly_reg_sid', sid)
  } catch (e) {
    sid = String(Date.now()) + Math.random().toString(16).slice(2)
  }
})

/* ---------- CID ---------- */
let cidTimer = null;
function onCidInput() {
  fb.input('cid');   // 一改就收起错误提示
  // 只允许数字：非数字字符直接剥掉，最多 4 位
  const digits = form.value.cid.replace(/\D/g, '').slice(0, 4);
  if (digits !== form.value.cid) form.value.cid = digits;
  cidState.value = { checked: false, ok: false, message: '' };
  clearTimeout(cidTimer);
  const cid = form.value.cid.trim();
  if (!/^\d{4}$/.test(cid)) return;
  cidTimer = setTimeout(checkCid, 350);
}
async function checkCid() {
  const cid = form.value.cid.trim();
  if (!/^\d{4}$/.test(cid)) return;
  try {
    const data = await api.get(`/api/auth/cid/check?cid=${cid}`);
    cidState.value = { checked: true, ok: data.available, message: data.message };
  } catch {
    cidState.value = { checked: true, ok: false, message: '检查失败，请重试' };
  }
}
async function randomCid() {
  try {
    const data = await api.get(`/api/auth/cid/random?sid=${sid}`);
    form.value.cid = data.cid;
    randomLeft.value = data.remaining;
    cidState.value = { checked: true, ok: true, message: `已生成随机 CID：${data.cid}` };
  } catch (err) {
    showToast(err.message);
  }
}

/* ---------- 验证码 ---------- */
async function sendCode() {
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(form.value.email)) {
    fb.fail('email', '请先填写正确的邮箱地址');
    return;
  }
  sending.value = true;
  try {
    const powToken = await powRef.value.ensure();
    const data = await api.post('/api/auth/send-code', {
      email: form.value.email,
      purpose: 'register',
    }, { headers: { 'X-PoW-Token': powToken } });
    powRef.value?.invalidate(); // 令牌一次性，发码后作废，下次提交自动重算
    codeSent.value = true;
    countdown.value = 60;
    const t = setInterval(() => {
      countdown.value -= 1;
      if (countdown.value <= 0) clearInterval(t);
    }, 1000);
    if (data.devCode) {
      devCode.value = data.devCode;
      showToast('服务器未配置 SMTP，验证码已直接显示在页面');
    } else {
      showToast('验证码已发送，请查收邮件，注意垃圾箱');
    }
  } catch (err) {
    showToast(err.message);
    powRef.value?.invalidate();
  } finally {
    sending.value = false;
  }
}

/* ---------- 提交 ---------- */
async function submit() {
  error.value = '';
  fb.clearAll();
  const f = form.value;
  if (!/^\d{4}$/.test(f.cid)) return fb.fail('cid', 'CID 必须是 4 位数字');
  if (cidState.value.checked && !cidState.value.ok) return fb.fail('cid', cidState.value.message);
  if (!/^[\u4e00-\u9fa5A-Za-z0-9_]{2,16}$/.test(f.username))
    return fb.fail('username', '用户名需 2-16 位，支持中文、字母、数字、下划线');
  if (f.qq && !/^[1-9][0-9]{4,10}$/.test(f.qq)) return fb.fail('qq', 'QQ 号格式不正确');
  if (!codeSent.value) return fb.fail('code', '请先点击「发送验证码」并查收邮件');
  if (!f.code) return fb.fail('code', '请输入邮箱验证码');
  if (!/^\d{6}$/.test(f.code)) return fb.fail('code', '验证码应为 6 位数字');
  if (f.password.length < 8 || f.password.length > 64)
    return fb.fail('password', '密码长度需 8-64 位，需包含字母和数字');
  if (!/[A-Za-z]/.test(f.password) || !/\d/.test(f.password))
    return fb.fail('password', '密码需同时包含字母和数字');
  if (f.password !== f.confirmPassword) return fb.fail('confirmPassword', '两次输入的密码不一致');
  if (!agree.value) return (error.value = '请先阅读并勾选同意《用户政策》与《隐私政策》');

  loading.value = true;
  try {
    const powToken = await powRef.value.ensure();
    const data = await api.post('/api/auth/register', {
      ...f,
      qq: f.qq || undefined,
      fingerprint: await getFingerprint(),
    }, { headers: { 'X-PoW-Token': powToken } });
    auth.loginSuccess(data.token, data.user);
    localStorage.removeItem('ctyfly_reg_sid');
    showToast('注册成功，欢迎加入 CTYFLY！');
    router.push('/home');
  } catch (err) {
    error.value = err.message;
    powRef.value?.invalidate();
  } finally {
    loading.value = false;
  }
}

const qqAvatar = () =>
  /^[1-9][0-9]{4,10}$/.test(form.value.qq)
    ? `https://q1.qlogo.cn/g?b=qq&nk=${form.value.qq}&s=100`
    : '';
</script>

<template>
  <!-- 6:4 分屏：左品牌实景 / 右无卡片表单，与登录页同一套布局，见 AuthSplitLayout-->
  <AuthSplitLayout
    headline="加入 CTYFLY，<br />从第一次连飞开始"
    sub="训练 · 考核 · 连飞 · 和飞友一起飞"
    pane-width="440px"
  >
    <div class="auth-brand">
      <div class="logo-big"><img :src="logoMark" alt="CTYFLY" width="46" height="46" /></div>
      <h1>创建 CTY 账号</h1>
      <p>加入 CTYFLY，开启您的连飞之旅</p>
    </div>

      <div v-if="error" class="alert alert-err">{{ error }}</div>
      <div v-if="devCode" class="alert alert-info">
        开发模式验证码：<strong style="letter-spacing: 3px">{{ devCode }}</strong>
      </div>

      <form @submit.prevent="submit">
        <div class="field" :class="{ 'is-error': fb.errors.cid, 'is-shake': fb.shaking.cid }" @animationend="fb.shaking.cid = false">
          <label class="label">CID <span style="color: var(--red)">*</span></label>
          <div class="input-row">
            <input v-model="form.cid" class="input" inputmode="numeric" maxlength="4" placeholder="4 位数字" @input="onCidInput" @blur="checkCid" />
            <button class="btn btn-ghost" type="button" :disabled="randomLeft <= 0" @click="randomCid">
              <Icon name="dice" :size="15" /> 随机
            </button>
          </div>
          <div v-if="cidState.checked" class="hint" :class="cidState.ok ? 'ok' : 'err'">{{ cidState.message }}</div>
          <div v-else class="hint">4 位数字，注册后不可修改；随机 CID 每会话限 {{ randomLeft }} 次</div>
          <div class="field-hint" :class="{ show: !!fb.errors.cid }">
            <div class="field-hint-text">{{ fb.errors.cid }}</div>
          </div>
        </div>

        <div class="field" :class="{ 'is-error': fb.errors.username, 'is-shake': fb.shaking.username }" @animationend="fb.shaking.username = false">
          <label class="label">用户名 <span style="color: var(--red)">*</span></label>
          <input v-model="form.username" class="input" placeholder="2-16 位，中英文/数字/下划线" @input="fb.input('username')" />
          <div class="field-hint" :class="{ show: !!fb.errors.username }">
            <div class="field-hint-text">{{ fb.errors.username }}</div>
          </div>
        </div>

        <div class="field" :class="{ 'is-error': fb.errors.email, 'is-shake': fb.shaking.email }" @animationend="fb.shaking.email = false">
          <label class="label">邮箱 <span style="color: var(--red)">*</span></label>
          <div class="input-row">
            <input v-model="form.email" class="input" type="email" placeholder="用于接收验证码" @input="fb.input('email')" />
            <button class="btn btn-ghost" type="button" :disabled="sending || countdown > 0" @click="sendCode">
              {{ countdown > 0 ? `${countdown}s` : sending ? '发送中…' : '发送验证码' }}
            </button>
          </div>
          <div class="field-hint" :class="{ show: !!fb.errors.email }">
            <div class="field-hint-text">{{ fb.errors.email }}</div>
          </div>
        </div>

        <div class="field" :class="{ 'is-error': fb.errors.code, 'is-shake': fb.shaking.code }" @animationend="fb.shaking.code = false">
          <label class="label">邮箱验证码 <span style="color: var(--red)">*</span></label>
          <input
            v-model="form.code"
            class="input"
            inputmode="numeric"
            maxlength="6"
            :disabled="!codeSent"
            :placeholder="codeSent ? '6 位验证码' : '输入验证码'"
            @input="fb.input('code')"
          />
          <div v-if="codeSent && devCode" class="hint ok">验证码已显示在页面顶部，直接填写即可</div>
          <div class="field-hint" :class="{ show: !!fb.errors.code }">
            <div class="field-hint-text">{{ fb.errors.code }}</div>
          </div>
        </div>

        <div class="field" :class="{ 'is-error': fb.errors.qq, 'is-shake': fb.shaking.qq }" @animationend="fb.shaking.qq = false">
          <label class="label">QQ 号 <span class="optional">选填，填写后自动绑定 QQ 头像</span></label>
          <div class="input-row" style="align-items: center">
            <input v-model="form.qq" class="input" inputmode="numeric" placeholder="用于展示头像，可不填" @input="fb.input('qq')" />
            <img v-if="qqAvatar()" :src="qqAvatar()" style="width: 40px; height: 40px; border-radius: 50%; flex-shrink: 0" alt="QQ头像" />
          </div>
          <div class="field-hint" :class="{ show: !!fb.errors.qq }">
            <div class="field-hint-text">{{ fb.errors.qq }}</div>
          </div>
        </div>

        <div class="field" :class="{ 'is-error': fb.errors.password, 'is-shake': fb.shaking.password }" @animationend="fb.shaking.password = false">
          <label class="label">密码 <span style="color: var(--red)">*</span></label>
          <input v-model="form.password" class="input" type="password" placeholder="8-64 位，含字母和数字" autocomplete="new-password" @input="fb.input('password')" />
          <div class="field-hint" :class="{ show: !!fb.errors.password }">
            <div class="field-hint-text">{{ fb.errors.password }}</div>
          </div>
        </div>

        <div class="field" :class="{ 'is-error': fb.errors.confirmPassword, 'is-shake': fb.shaking.confirmPassword }" @animationend="fb.shaking.confirmPassword = false">
          <label class="label">确认密码 <span style="color: var(--red)">*</span></label>
          <input v-model="form.confirmPassword" class="input" type="password" placeholder="再次输入密码" autocomplete="new-password" @input="fb.input('confirmPassword')" />
          <div class="field-hint" :class="{ show: !!fb.errors.confirmPassword }">
            <div class="field-hint-text">{{ fb.errors.confirmPassword }}</div>
          </div>
        </div>

        <div class="field">
          <div style="display: flex; align-items: flex-start; gap: 9px; font-size: 13px; color: var(--text-2)">
            <CheckBox v-model="agree" />
            <span style="margin-top: 1px">
              我已阅读并同意
              <router-link class="text-link" to="/terms" target="_blank">《用户政策》</router-link>
              与
              <router-link class="text-link" to="/privacy" target="_blank">《隐私政策》</router-link>
            </span>
          </div>
        </div>

        <!-- 自研工作量证明：完全不可见，用户感知不到这道校验 -->
        <PoWCaptcha ref="powRef" />

        <button class="btn btn-primary btn-lg btn-block" :disabled="loading" type="submit">
          {{ loading ? '注册中…' : '注 册' }}
        </button>
      </form>

      <div class="auth-foot">
        已有账号？<router-link class="text-link" to="/login">直接登录</router-link>
        <span style="margin: 0 8px; color: var(--gray)">·</span>
        <router-link class="text-link" to="/" style="color: var(--text-2)">← 返回首页</router-link>
      </div>
  </AuthSplitLayout>
</template>
