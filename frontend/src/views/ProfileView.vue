<script setup>
import { ref } from 'vue';
import { api, setToken } from '../api.js';
import { useAuthStore } from '../stores/auth.js';
import { showToast } from '../utils.js';
import UserAvatar from '../components/UserAvatar.vue';
import UserTag from '../components/UserTag.vue';
import Icon from '../components/Icon.vue';
import { petEnabled, petHover, setPetEnabled, setPetHover } from '../pet.js';
import { navLayout, setNavLayout } from '../navlayout.js';
import { restartTour } from '../tour.js';

const auth = useAuthStore();

// 导航布局：左侧边栏 / 顶部栏，顶部栏为横排 + 悬停通栏面板
function chooseLayout(v) {
  setNavLayout(v);
  showToast(v === 'top' ? '已切到顶部栏导航，窄屏会自动回退侧边抽屉' : '已切回左侧边栏');
}

// 重新播放新手引导，跳过的人也能找回来
function replayTour() {
  restartTour();
  showToast('新手引导已重新开始');
}

// 桌面小鲸灵开关，关掉后写入 localStorage，这里可以再打开
function togglePet(on) {
  setPetEnabled(on);
  showToast(on ? '鲸宝已回来啦' : '已收起鲸宝，可在本页重新打开');
}

// 停放方式：落地，默认，按重力落回底部/ 悬停，停在你拖到的位置
function toggleHover(on) {
  setPetHover(on);
  showToast(on ? '已切到悬停：松手后停在原地' : '已切到落地：松手后落回页面底部');
}

const username = ref(auth.user?.username || '');
const qq = ref(auth.user?.qq || '');

const pwd = ref({ oldPassword: '', password: '', confirmPassword: '' });
const savingProfile = ref(false);
const savingPwd = ref(false);

async function saveProfile() {
  savingProfile.value = true;
  try {
    const data = await api.patch('/api/auth/profile', { username: username.value, qq: qq.value });
    auth.user = data.user;
    showToast('资料已更新');
  } catch (err) {
    showToast(err.message);
  } finally {
    savingProfile.value = false;
  }
}

async function changePwd() {
  savingPwd.value = true;
  try {
    const data = await api.post('/api/auth/change-password', pwd.value);
    // 后端令牌版本化：换发新 token，当前会话无缝续期，其他旧会话全部失效
    if (data.token) setToken(data.token);
    showToast('密码修改成功');
    pwd.value = { oldPassword: '', password: '', confirmPassword: '' };
  } catch (err) {
    showToast(err.message);
  } finally {
    savingPwd.value = false;
  }
}
</script>

<template>
  <!-- 横向布局，2026-10-17 站长要求：两列 Grid 平铺，一屏尽量多看；
       单卡内容过长时在卡片内部滚动，.profile-card 的 max-height + overflow-y，
       不再把整页撑高；窄屏回退单列、取消限高，见底部 scoped 样式。-->
  <div class="page profile-page">
    <div class="page-header">
      <div class="page-title">个人中心</div>
      <div class="page-desc">管理您的账号资料与安全设置</div>
    </div>

    <div class="profile-grid">
      <!-- 身份横幅：整行 -->
      <div class="glass card profile-banner" style="display: flex; align-items: center; gap: 20px">
        <UserAvatar :user="auth.user" :size="76" ring />
        <div style="flex: 1">
          <div style="font-size: 19px; font-weight: 700">
            <UserTag
              :badge="auth.user?.equipped_badge"
              :title="auth.user?.equipped_title"
              size="lg"
            >{{ auth.user?.username }}</UserTag>
          </div>
          <div style="font-size: 13px; color: var(--text-2); margin-top: 2px">CID {{ auth.user?.cid }} · {{ auth.user?.email }}</div>
          <div style="margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap">
            <span class="tag tag-blue">管制等级 {{ auth.user?.rating }}</span>
            <span class="tag tag-purple">飞行员 {{ auth.user?.pilot_rank }}</span>
            <span v-if="auth.user?.is_controller" class="tag tag-green">在职管制员</span>
            <span v-if="auth.isAdmin" class="tag tag-red">管理员</span>
          </div>
          <router-link
            v-if="!auth.user?.equipped_badge && !auth.user?.equipped_title"
            to="/shop"
            class="btn btn-ghost btn-sm"
            style="margin-top: 10px"
          ><Icon name="shop" :size="14" /> 去商城挑选称号与徽章</router-link>
        </div>
        <div style="text-align: right; font-size: 12.5px; color: var(--gray)">
          注册于 {{ auth.user?.created_at?.slice(0, 10) }}
        </div>
      </div>

      <div class="glass card profile-card">
        <div class="card-title">基础资料</div>
        <div class="card-sub">修改 QQ 号后将自动重新绑定 QQ 头像</div>
        <div class="grid grid-2">
          <div class="field"><label class="label">用户名</label><input v-model="username" class="input" /></div>
          <div class="field"><label class="label">QQ 号 <span class="optional">选填</span></label><input v-model="qq" class="input" inputmode="numeric" maxlength="20" placeholder="填写后自动同步 QQ 头像" /></div>
        </div>
        <div class="field">
          <label class="label">邮箱</label>
          <input class="input" :value="auth.user?.email" disabled />
          <div class="hint">注册邮箱不可修改</div>
        </div>
        <button class="btn btn-primary" :disabled="savingProfile" @click="saveProfile">
          {{ savingProfile ? '保存中…' : '保存资料' }}
        </button>
      </div>

      <div class="glass card profile-card">
        <div class="card-title">修改密码</div>
        <div class="card-sub">为了账号安全，建议定期更换密码</div>
        <div class="grid grid-3">
          <div class="field"><label class="label">当前密码</label><input v-model="pwd.oldPassword" class="input" type="password" autocomplete="current-password" /></div>
          <div class="field"><label class="label">新密码</label><input v-model="pwd.password" class="input" type="password" autocomplete="new-password" /></div>
          <div class="field"><label class="label">确认新密码</label><input v-model="pwd.confirmPassword" class="input" type="password" autocomplete="new-password" /></div>
        </div>
        <button class="btn btn-dark" :disabled="savingPwd" @click="changePwd">
          {{ savingPwd ? '提交中…' : '修改密码' }}
        </button>
      </div>

      <div class="glass card profile-card">
        <div class="card-title">桌面小鲸灵</div>
        <div class="card-sub">
          页面右下角的鲸宝，开源桌宠 dsh-pet 的网页版：三十多段手绘动画自己连播，
          会打瞌睡、玩魔方、写代码、涮火锅；点它有 Q 弹回应，拖着玩可以甩出去撞墙反弹。
          <strong>右键，手机长按</strong>它还能点播动作、聊两句。
          关掉后不会再出现，随时可以在这里召唤回来。
        </div>
        <button
          class="btn"
          :class="petEnabled ? 'btn-ghost' : 'btn-primary'"
          @click="togglePet(!petEnabled)"
        >
          {{ petEnabled ? '收起鲸宝' : '召唤鲸宝' }}
        </button>

        <div style="display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border)">
          <div>
            <strong style="font-size: 13.5px">停放方式</strong>
            <div class="card-sub" style="margin: 2px 0 0">
              {{ petHover
                ? '悬停：拖到哪里就停在哪里，可以停在半空或页面顶部'
                : '落地：松手后按重力落回页面底部，像现实里的小宠物一样' }}
            </div>
          </div>
          <button class="btn btn-ghost btn-sm" @click="toggleHover(!petHover)">
            {{ petHover ? '改为落地' : '改为悬停' }}
          </button>
        </div>
      </div>

      <!-- 右列：两张小卡纵排，填满与左列桌宠卡同行的高度 -->
      <div class="profile-col">
        <div class="glass card profile-card">
          <div class="card-title">导航布局</div>
          <div class="card-sub">
            左侧边栏：竖向菜单，二级项就地展开；顶部栏：导航横排，鼠标悬停展开通栏面板，
            子页面分列展示并带说明。窄屏，≤860px 会自动使用侧边抽屉。
          </div>
          <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap">
            <button
              class="btn"
              :class="navLayout === 'side' ? 'btn-primary' : 'btn-ghost'"
              @click="chooseLayout('side')"
            >左侧边栏</button>
            <button
              class="btn"
              :class="navLayout === 'top' ? 'btn-primary' : 'btn-ghost'"
              @click="chooseLayout('top')"
            >顶部栏</button>
            <span class="card-sub" style="margin: 0">
              当前：{{ navLayout === 'top' ? '顶部栏' : '左侧边栏' }}
            </span>
          </div>
        </div>

        <div class="glass card profile-card">
          <div class="card-title">新手引导</div>
          <div class="card-sub">
            带你过一遍侧边栏里的每个功能是干什么的，随时可以跳过。想再看一遍就点下面这个按钮。
          </div>
          <button class="btn btn-ghost" @click="replayTour">重新播放新手引导</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 两列横向平铺：minmax 0,1fr 防止长内容把列撑破*/
.profile-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  align-items: stretch;
}

/* 全局 `.card + .card { margin-top: 16px }`，给纵向卡片列表留的间距会渗进网格：
   只有紧邻上一张 .card 的那张被顶下 16px，与格子里的非 .card 容器，.profile-col 错位。
   网格内间距由 gap 负责，这里清零。*/
.profile-grid > .card,
.profile-grid .profile-col > .card {
  margin-top: 0;
}

/* 身份横幅占整行 */
.profile-banner {
  grid-column: 1 / -1;
}

/* 单卡限高 = 一屏内放得下；内容超出时卡片内部滚动，不再把整页撑高 */
.profile-card {
  min-width: 0;
  max-height: calc(100vh - 200px);
  overflow-y: auto;
}

/* 右列小卡纵排 */
.profile-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

/* 窄屏回退单列，取消限高：手机上保持自然的页面滚动 */
@media (max-width: 960px) {
  .profile-grid {
    grid-template-columns: 1fr;
  }
  .profile-card {
    max-height: none;
    overflow: visible;
  }
  .profile-col {
    display: contents;
  }
}

/* 手机端：修改密码的三个输入框在单列里挤成 3 列太窄，改为逐个堆叠 */
@media (max-width: 720px) {
  .profile-card .grid-3 {
    grid-template-columns: 1fr;
  }
}
</style>
