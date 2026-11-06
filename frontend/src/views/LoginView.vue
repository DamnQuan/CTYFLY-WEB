<script setup>
import { onBeforeUnmount, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../api.js';
import { useAuthStore } from '../stores/auth.js';
import { getFingerprint } from '../fingerprint.js';
import { showToast } from '../utils.js';
import { useFieldFeedback } from '../fieldFeedback.js';
import PoWCaptcha from '../components/PoWCaptcha.vue';
import MorphLoginButton from '../components/MorphLoginButton.vue';
import AuthSplitLayout from '../components/AuthSplitLayout.vue';
import logoMark from '../assets/logo-mark.webp';

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

const account = ref('');
const password = ref('');
/* 提交状态机：idle → loading → success / error →，error 摇晃完 idle
   驱动 MorphLoginButton 的样式类；loading/success 期间按钮禁用，杜绝重复提交*/
const status = ref('idle');
const error = ref('');
let successTimer = null;
onBeforeUnmount(() => clearTimeout(successTimer));

/* 字段级校验反馈：红边 + 水平轻晃 + 提示从下方滑入，一改就收起，见 fieldFeedback.js*/
const fb = useFieldFeedback(['account', 'password']);

// 工作量证明人机验证：全程静默，失败也不向用户暴露具体原因
const powRef = ref(null);

async function submit() {
  if (status.value !== 'idle') return; // 状态机层面拦截重复提交，按钮也会禁用
  error.value = '';
  fb.clearAll();
  if (!account.value.trim()) {
    fb.fail('account', '请填写 CID 或用户名');
    return;
  }
  if (!password.value) {
    fb.fail('password', '请填写密码');
    return;
  }
  let powToken = '';
  try {
    powToken = await powRef.value.ensure();
  } catch {
    error.value = '操作未完成，请稍后重试';
    return;
  }
  status.value = 'loading';
  try {
    const data = await api.post('/api/auth/login', {
      account: account.value.trim(),
      password: password.value,
      fingerprint: await getFingerprint(),
    }, { headers: { 'X-PoW-Token': powToken } });
    auth.loginSuccess(data.token, data.user);
    showToast(`欢迎回来，${data.user.username}`);
    status.value = 'success';
    // 留一点时间让绿色对勾被看见，跳转后组件就卸载了
    successTimer = setTimeout(() => router.push(route.query.redirect || '/home'), 650);
  } catch (err) {
    error.value = err.message;
    status.value = 'error'; // 红球摇晃约 1.2s，组件 emit settle 后回到 idle
    powRef.value?.invalidate();
  }
}
</script>

<template>
  <!-- 6:4 分屏：左品牌实景 / 右无卡片表单；移动端折叠品牌栏，布局见 AuthSplitLayout-->
  <AuthSplitLayout>
    <div class="auth-brand">
      <div class="logo-big"><img :src="logoMark" alt="CTYFLY" width="46" height="46" /></div>
      <h1>登录</h1>
      <p>使用 CID 或用户名登录</p>
    </div>

    <div v-if="error" class="alert alert-err">{{ error }}</div>

    <form @submit.prevent="submit">
      <div class="field" :class="{ 'is-error': fb.errors.account, 'is-shake': fb.shaking.account }" @animationend="fb.shaking.account = false">
        <label class="label">CID / 用户名</label>
        <input v-model="account" class="input" placeholder="例如 5966" autocomplete="username" @input="fb.input('account')" />
        <div class="field-hint" :class="{ show: !!fb.errors.account }">
          <div class="field-hint-text">{{ fb.errors.account }}</div>
        </div>
      </div>
      <div class="field" :class="{ 'is-error': fb.errors.password, 'is-shake': fb.shaking.password }" @animationend="fb.shaking.password = false">
        <label class="label">密码</label>
        <input v-model="password" class="input" type="password" placeholder="请输入密码" autocomplete="current-password" @input="fb.input('password')" />
        <div class="field-hint" :class="{ show: !!fb.errors.password }">
          <div class="field-hint-text">{{ fb.errors.password }}</div>
        </div>
      </div>

      <!-- 自研工作量证明：完全不可见，用户感知不到这道校验 -->
      <PoWCaptcha ref="powRef" />

      <MorphLoginButton :status="status" label="登录" @settle="status = 'idle'" />
    </form>

    <div class="auth-foot">
      <router-link class="text-link" to="/forgot">忘记密码？</router-link>
      <span style="margin: 0 8px; color: var(--gray)">·</span>
      还没有账号？<router-link class="text-link" to="/register">立即注册</router-link>
    </div>
    <div class="auth-foot" style="margin-top: 10px">
      <router-link class="text-link" to="/" style="color: var(--text-2)">← 返回首页</router-link>
    </div>
  </AuthSplitLayout>
</template>
