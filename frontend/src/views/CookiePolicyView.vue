<script setup>
import { computed, ref } from 'vue';
import { getConsent, resetConsent } from '../consent.js';
import { showToast } from '../utils.js';
import Icon from '../components/Icon.vue';

const consentKey = ref(getConsent());
const consentText = computed(() => {
  if (consentKey.value === 'all') return '你已同意使用全部存储项，包括必需项与偏好项。';
  if (consentKey.value === 'essential') return '你选择了仅使用必需存储项，偏好设置中的主题与时区不会被保存。';
  return '你尚未作出选择，偏好存储项暂未写入。';
});

function resetChoice() {
  resetConsent();
  consentKey.value = '';
  showToast('已清除你的选择，刷新页面后将再次弹出提示');
}

const items = [
  {
    key: 'ctyfly_token',
    name: '登录凭据 JWT',
    purpose: '在你登录后维持登录状态，请求需要鉴权的接口时随请求头发送',
    duration: '7 天，或直到你退出登录 / 修改密码',
    necessary: true,
  },
  {
    key: 'ctyfly_theme',
    name: '外观偏好',
    purpose: '记住你在顶栏选择的主题模式，AUTO 跟随系统 / 浅色 / 深色',
    duration: '长期保存，直到手动清除',
    necessary: false,
  },
  {
    key: 'ctyfly_tz',
    name: '时区偏好',
    purpose: '记住仪表盘时钟的时区选择，UTC / 北京时间',
    duration: '长期保存，直到手动清除',
    necessary: false,
  },
  {
    key: 'ctyfly_reg_sid',
    name: '注册会话标识',
    purpose: '限制"随机 CID"功能每会话最多 15 次，防止滥用',
    duration: '注册成功后自动清除；也可手动清除',
    necessary: true,
  },
];
</script>

<template>
  <div class="policy-shell">
  <div class="page legal-page">
    <div class="page-header" style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px">
      <div>
        <div class="page-title">Cookie 政策</div>
        <div class="page-desc">更新日期：2026 年 9 月 11 日 · 生效日期：2026 年 9 月 11 日</div>
      </div>
      <router-link class="btn btn-ghost btn-sm" to="/">
        <Icon name="chevron" :size="14" style="transform: rotate(90deg)" /> 返回首页
      </router-link>
    </div>

    <div class="glass card legal-card">
      <h2>一、概述</h2>
      <p>
        CTYFLY 以下简称「本站」，重视你的隐私。本政策说明本站如何使用 Cookie 及等效的本地存储技术，
        也就是 localStorage，以下统称「存储项」，以及你如何管理它们。
      </p>
      <p>
        关于我们如何收集、使用与保护你的个人信息，包括账号、日志、第三方服务等，请另见
        <router-link class="text-link" to="/privacy">《隐私政策》</router-link>。
      </p>
      <p>
        本站<strong>不使用</strong>任何用于广告、跨站追踪或行为分析的第三方 Cookie。
        所有存储项仅用于维持站点核心功能与你的个人偏好设置。
      </p>

      <h2>二、我们使用的存储项</h2>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr><th>名称</th><th>用途</th><th>期限</th><th>性质</th></tr>
          </thead>
          <tbody>
            <tr v-for="it in items" :key="it.key">
              <td><code>{{ it.key }}</code></td>
              <td>{{ it.purpose }}</td>
              <td>{{ it.duration }}</td>
              <td>
                <span :class="it.necessary ? 'tag tag-blue' : 'tag'">
                  {{ it.necessary ? '必需' : '偏好' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="legal-note">
        其中 <code>ctyfly_token</code> 与 <code>ctyfly_reg_sid</code> 为站点运行所必需：
        拒绝或清除它们将导致无法保持登录状态、随机 CID 次数限制失效。
        偏好类存储项可随意清除，只会使设置恢复默认值。
      </p>

      <h2>三、安全审计数据，服务端记录</h2>
      <p>
        为保障账号与站点安全，本站会在<strong>服务端</strong>记录以下安全审计数据，不使用 Cookie，也不写入你的浏览器：
      </p>
      <ul>
        <li><strong>登录与注册信息</strong>：IP 地址、由 IP 解析得到的粗略地理位置，也就是国家 / 省份 / 城市 / 运营商，以及 User-Agent；</li>
        <li><strong>设备指纹哈希</strong>：由浏览器特征，也就是 UA、语言、时区、屏幕参数、Canvas 渲染等，计算出的<strong>不可逆摘要</strong>，
          仅用于识别「同一设备异常登录」，不采集任何个人身份信息，也无法反推出你的原始特征；</li>
        <li><strong>行为日志</strong>：登录结果，包括成功 / 失败原因、敏感操作记录，也就是权限变更、封禁、删除账户、公告与活动增删等、
          越权访问与限流触发记录、接口访问量统计。</li>
      </ul>
      <p>
        <strong>用途</strong>：账号安全保护、异常登录识别、防止暴力破解与恶意注册、处理纠纷与违规调查。
        <strong>我们不会</strong>将这些数据用于广告投放、用户画像或向第三方出售。
      </p>
      <p class="legal-note">
        说明：IP 地理位置通过第三方服务 ip-api.com 查询，查询时仅发送 IP 地址本身，结果在本站缓存 24 小时。
        如需查询或删除与你的账号相关的日志，请通过工单中心提出申请。
      </p>

      <h2>四、我们不做什么</h2>
      <ul>
        <li>不投放广告，不接入任何广告联盟的 Cookie；</li>
        <li>不使用 Google Analytics 等第三方统计/追踪服务；</li>
        <li>不通过 Cookie 在第三方网站上跟踪你的行为；</li>
        <li>不将存储项中的信息用于身份识别以外的目的，或与第三方共享用于营销。</li>
      </ul>

      <h2>五、第三方页面与接口</h2>
      <p>
        当你点击首页的"加入QQ群"按钮时，你会离开本站并访问腾讯 QQ 加群页面，该页面受
        <a class="text-link" href="https://privacy.qq.com/" target="_blank" rel="noopener noreferrer">腾讯隐私政策</a> 约束，
        其可能设置自己的 Cookie，本站无法控制亦不承担相关责任。
      </p>
      <p>
        航情查询功能由本站服务器向 aviationweather.gov 发起服务端请求，此过程不经过你的浏览器，
        不会向你写入任何 Cookie。
      </p>

      <h2>六、如何管理或删除</h2>
      <ul>
        <li><strong>退出登录</strong>：点击侧边栏底部的退出按钮，登录凭据将立即从你的浏览器移除；</li>
        <li><strong>清除偏好</strong>：在浏览器设置的"站点数据"中删除本站的存储项，主题与时区将恢复默认；</li>
        <li><strong>无痕/隐私模式</strong>：使用浏览器无痕模式访问时，关闭窗口后所有存储项自动删除；</li>
        <li><strong>浏览器设置</strong>：你也可以在浏览器中禁止本站写入存储项，但登录功能将不可用。</li>
      </ul>

      <div class="consent-manage">
        <div>
          <strong>你的当前选择</strong>
          <p style="margin-top: 2px">
            {{ consentText }}
          </p>
        </div>
        <button class="btn btn-ghost" @click="resetChoice">重新选择</button>
      </div>

      <h2>七、政策更新</h2>
      <p>
        若本站的存储项使用方式发生重大变化，我们将在首页公告中告知并更新本政策的"更新日期"。
        继续使用本站即视为接受更新后的政策。
      </p>

      <h2>八、联系我们</h2>
      <p>
        如对本政策有任何疑问，请登录后在
        <router-link class="text-link" to="/tickets">工单中心</router-link>
        提交「账号问题」类工单，或加入首页底部的 QQ 群联系管理团队。
      </p>
    </div>
  </div>
  </div>
</template>

<style scoped>
.legal-page { max-width: 860px; padding-top: 20px; }
.legal-card { padding: 32px 34px; }
.legal-card h2 {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.2px;
  margin: 26px 0 10px;
}
.legal-card h2:first-child { margin-top: 0; }
.legal-card p {
  color: var(--text-2);
  font-size: 14px;
  margin-bottom: 10px;
  line-height: 1.75;
}
.legal-card strong { color: var(--text); }
.legal-card ul {
  padding-left: 20px;
  color: var(--text-2);
  font-size: 14px;
  line-height: 1.9;
  margin-bottom: 10px;
}
.legal-card code {
  font-family: 'SF Mono', 'JetBrains Mono', Consolas, monospace;
  font-size: 12px;
  background: var(--surface);
  padding: 2px 7px;
  border-radius: 6px;
}
.legal-note {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--surface);
  font-size: 13px;
}
.consent-manage {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 16px;
  padding: 14px 16px;
  border-radius: var(--radius-sm);
  background: var(--surface);
}
.consent-manage strong { font-size: 13.5px; }
.consent-manage p { margin: 0 !important; font-size: 13px; }
</style>
