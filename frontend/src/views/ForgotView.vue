<script setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';
import { showToast } from '../utils.js';
import Icon from '../components/Icon.vue';
import PoWCaptcha from '../components/PoWCaptcha.vue';
import AuthSplitLayout from '../components/AuthSplitLayout.vue';

const router = useRouter();

const email = ref('');
const code = ref('');
const password = ref('');
const confirmPassword = ref('');
const devCode = ref('');
const countdown = ref(0);
const sending = ref(false);
const loading = ref(false);
const error = ref('');
const success = ref(false);

// 工作量证明人机验证：全程静默，失败也不向用户暴露具体原因
const powRef = ref(null);

async function sendCode() {
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email.value)) {
    showToast('请先填写正确的邮箱地址');
    return;
  }
  sending.value = true;
  try {
    const powToken = await powRef.value.ensure();
    const data = await api.post('/api/auth/send-code', {
      email: email.value,
      purpose: 'reset',
    }, { headers: { 'X-PoW-Token': powToken } });
    powRef.value?.invalidate(); // 令牌一次性，发码后作废
    countdown.value = 60;
    const t = setInterval(() => {
      countdown.value -= 1;
      if (countdown.value <= 0) clearInterval(t);
    }, 1000);
    if (data.devCode) {
      devCode.value = data.devCode;
      showToast('服务器未配置 SMTP，验证码已直接显示在页面');
    } else {
      showToast('重置验证码已发送，请查收邮件');
    }
  } catch (err) {
    showToast(err.message);
    powRef.value?.invalidate();
  } finally {
    sending.value = false;
  }
}

async function submit() {
  error.value = '';
  if (!email.value || !code.value) return (error.value = '请填写邮箱与验证码');
  if (password.value.length < 8) return (error.value = '新密码长度至少 8 位，需包含字母和数字');
  if (!/[A-Za-z]/.test(password.value) || !/\d/.test(password.value))
    return (error.value = '新密码需同时包含字母和数字');
  if (password.value !== confirmPassword.value) return (error.value = '两次输入的密码不一致');

  loading.value = true;
  try {
    const powToken = await powRef.value.ensure();
    await api.post('/api/auth/reset-password', {
      email: email.value,
      code: code.value,
      password: password.value,
      confirmPassword: confirmPassword.value,
    }, { headers: { 'X-PoW-Token': powToken } });
    success.value = true;
    showToast('密码重置成功，请重新登录');
    setTimeout(() => router.push('/login'), 1500);
  } catch (err) {
    error.value = err.message;
    powRef.value?.invalidate();
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <!-- 6:4 分屏：左品牌实景 / 右无卡片表单，与登录页同一套布局，见 AuthSplitLayout-->
  <AuthSplitLayout
    headline="别担心，<br />找回只需一封邮件"
    sub="绑定邮箱验证 · 重置后请使用新密码登录"
  >
    <div class="auth-brand">
      <div class="logo-big" style="color: var(--blue)"><Icon name="key" :size="42" /></div>
      <h1>重置密码</h1>
      <p>通过绑定邮箱验证码找回您的密码</p>
    </div>

      <div v-if="error" class="alert alert-err">{{ error }}</div>
      <div v-if="success" class="alert alert-ok">重置成功，正在跳转登录页…</div>
      <div v-if="devCode" class="alert alert-info">
        开发模式验证码：<strong style="letter-spacing: 3px">{{ devCode }}</strong>
      </div>

      <form @submit.prevent="submit">
        <div class="field">
          <label class="label">绑定邮箱</label>
          <div class="input-row">
            <input v-model="email" class="input" type="email" placeholder="注册时填写的邮箱" />
            <button class="btn btn-ghost" type="button" :disabled="sending || countdown > 0" @click="sendCode">
              {{ countdown > 0 ? `${countdown}s` : sending ? '发送中…' : '发送验证码' }}
            </button>
          </div>
        </div>

        <div class="field">
          <label class="label">邮箱验证码</label>
          <input v-model="code" class="input" inputmode="numeric" maxlength="6" placeholder="6 位验证码" />
        </div>

        <div class="field">
          <label class="label">新密码</label>
          <input v-model="password" class="input" type="password" placeholder="至少 8 位，含字母和数字" autocomplete="new-password" />
        </div>

        <div class="field">
          <label class="label">确认新密码</label>
          <input v-model="confirmPassword" class="input" type="password" placeholder="再次输入新密码" autocomplete="new-password" />
        </div>

        <!-- 自研工作量证明：完全不可见，用户感知不到这道校验 -->
        <PoWCaptcha ref="powRef" />

        <button class="btn btn-primary btn-lg btn-block" :disabled="loading || success" type="submit">
          {{ loading ? '提交中…' : '重置密码' }}
        </button>
      </form>

      <div class="auth-foot">
        <router-link class="text-link" to="/login">← 返回登录</router-link>
      </div>
  </AuthSplitLayout>
</template>
