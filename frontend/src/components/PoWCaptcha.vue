<script setup>
/**
 * 自研工作量证明人机验证，完全静默
 *
 * 行为：
 * 1. 挂载即向 /api/captcha/challenge 取题，难度与 challenge 都由服务端决定；
 * 2. 把题丢进 Web Worker 枚举 nonce，主线程完全不被占用；
 * 3. 算完静默提交 /api/captcha/verify 换取一次性令牌，通过 verified 事件抛给父组件；
 * 4. 不渲染任何可见内容，用户全程感知不到这道校验。
 *
 * 父组件用法：
 *   const token = await powRef.value.ensure();
 *   api.post(url, body, { headers: { 'X-PoW-Token': token } });
 * 提交失败后调用 powRef.value.invalidate()，下次提交会自动重新求解。
 */
import { onBeforeUnmount, onMounted } from 'vue';
import { api } from '../api.js';

const emit = defineEmits(['verified', 'error']);
let token = '';
let tokenAt = 0;
let worker = null;
let solving = null;
let attempted = 0;

const TOKEN_FRESH_MS = 8 * 60 * 1000;
const MAX_ATTEMPTS = 3;
const GENERIC_ERROR = '操作未完成，请稍后重试';

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function stopWorker() {
  if (worker) {
    worker.terminate();
    worker = null;
  }
}

/** 在 Worker 里求解，返回 nonce 字符串；Worker 出错或超时会 reject */
function runWorker(challenge, difficulty) {
  return new Promise((resolve, reject) => {
    stopWorker();
    worker = new Worker(new URL('../pow.worker.js', import.meta.url), { type: 'module' });
    const timer = setTimeout(() => {
      stopWorker();
      reject(new Error('超时'));
    }, 15000);
    worker.onmessage = (event) => {
      const data = event.data || {};
      if (data.type === 'solved') {
        clearTimeout(timer);
        stopWorker();
        resolve(String(data.nonce));
      } else if (data.type === 'error') {
        clearTimeout(timer);
        stopWorker();
        reject(new Error(data.message || '计算失败'));
      }
    };
    worker.onerror = () => {
      clearTimeout(timer);
      stopWorker();
      reject(new Error('加载失败'));
    };
    worker.postMessage({ type: 'solve', challenge, difficulty });
  });
}

async function doSolve() {
  const info = await api.get('/api/captcha/challenge');
  if (!info.required) {
    // 本机开发等豁免来源：后端不会校验令牌，这里直接放行
    return '';
  }
  const nonce = await runWorker(info.challenge, Number(info.difficulty) || 0);
  const result = await api.post('/api/captcha/verify', {
    challenge: info.challenge,
    nonce,
  });
  return String(result.token || '');
}

/** 求解并返回一次性令牌；并发调用共享同一次计算 */
async function ensure() {
  if (token && Date.now() - tokenAt < TOKEN_FRESH_MS) return token;
  if (solving) return solving;
  solving = (async () => {
    attempted = 0;
    for (;;) {
      try {
        const value = await doSolve();
        token = value;
        tokenAt = Date.now();
        emit('verified', value);
        return value;
      } catch {
        attempted += 1;
        if (attempted >= MAX_ATTEMPTS) {
          emit('error', GENERIC_ERROR);
          throw new Error(GENERIC_ERROR);
        }
        await sleep(400 * attempted);
      }
    }
  })();
  try {
    return await solving;
  } finally {
    solving = null;
  }
}

/** 令牌已被服务端消费或校验失败时调用，下次 ensure 会重新求解 */
function invalidate() {
  token = '';
  tokenAt = 0;
}

onMounted(() => {
  // 挂载即预解一次，用户点提交时通常已经拿到令牌
  ensure().catch(() => {});
});

onBeforeUnmount(stopWorker);

defineExpose({ ensure, invalidate, reset: ensure });
</script>

<template>
  <span class="pow-captcha" aria-hidden="true"></span>
</template>

<style scoped>
.pow-captcha { display: none; }
</style>
