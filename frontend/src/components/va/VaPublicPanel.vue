<script setup>
import { inject } from 'vue';
import CheckBox from '../CheckBox.vue';
import Icon from '../Icon.vue';
import UserAvatar from '../UserAvatar.vue';
import UserTag from '../UserTag.vue';
const {
  airline,
  canManage,
  copyPublicLink,
  data,
  isCeo,
  previewDescription,
  previewFlags,
  previewFleet,
  previewLogo,
  previewName,
  previewSlogan,
  previewWelcome,
  pubForm,
  savePublicPage,
  savingPub,
  showPreview,
} = inject('airlinePage');
</script>

<template>
<div class="glass card">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px">
          <div>
            <div class="card-title" style="margin-bottom: 2px">对外主页</div>
            <div class="card-sub" style="margin-bottom: 0">
              {{ canManage ? '这里的内容会展示在公开主页上，任何人都可以访问' : '由 CEO / 部长维护，以下为对外主页的当前设置' }}
            </div>
          </div>
          <div style="display: flex; gap: 8px; flex-wrap: wrap">
            <button class="btn btn-ghost btn-sm" @click="showPreview = !showPreview">
              <Icon name="globe" :size="14" /> {{ showPreview ? '收起预览' : '预览对外主页' }}
            </button>
            <button v-if="isCeo" class="btn btn-ghost btn-sm" @click="copyPublicLink">
              <Icon name="link" :size="14" /> 复制主页链接
            </button>
          </div>
        </div>

        <template v-if="canManage">
          <div class="grid grid-2" style="margin-top: 18px">
            <div class="field">
              <label class="label">航司名称 <span style="color: var(--red)">*</span></label>
              <input v-model="pubForm.name" class="input" maxlength="20" />
            </div>
            <div class="field">
              <label class="label">标语 <span class="optional">选填，显示在名称下方</span></label>
              <input v-model="pubForm.slogan" class="input" maxlength="20" placeholder="如 安全第一，准点至上" />
            </div>
          </div>
          <div class="field">
            <label class="label">航司简介</label>
            <textarea v-model="pubForm.description" class="textarea" rows="3" maxlength="300"
                      placeholder="介绍航司定位、主基地与运营风格…"></textarea>
          </div>
          <div class="field">
            <label class="label">欢迎语 / 公告 <span class="optional">选填，主页上的醒目区块</span></label>
            <textarea v-model="pubForm.welcome" class="textarea" rows="3" maxlength="500"
                      placeholder="如 我们长期招募热爱飞行的伙伴，欢迎加入…"></textarea>
          </div>

          <div class="field">
            <label class="label">展示板块</label>
            <div style="display: flex; gap: 20px; flex-wrap: wrap">
              <CheckBox v-model="pubForm.showStats" variant="switch" label="数据统计" />
              <CheckBox v-model="pubForm.showFleet" variant="switch" label="机队" />
              <CheckBox v-model="pubForm.showRoutes" variant="switch" label="航线网络" />
              <CheckBox v-model="pubForm.showMembers" variant="switch" label="成员名单" />
            </div>
            <div class="list-sub" style="margin-top: 6px">关闭的板块在对外主页上完全不显示，访客也取不到对应数据</div>
          </div>

          <button class="btn btn-primary" :disabled="savingPub" @click="savePublicPage">
            {{ savingPub ? '保存中…' : '保存对外主页' }}
          </button>
        </template>

        <template v-else>
          <div class="list-item">
            <div class="list-main">
              <div class="list-title">{{ airline.name }}</div>
              <div class="list-sub">{{ airline.slogan || '未设置标语' }}</div>
            </div>
          </div>
          <div class="list-sub" style="margin-top: 10px">
            展示板块：
            {{ [
              airline.show_stats ? '数据统计' : '', airline.show_fleet ? '机队' : '',
              airline.show_routes ? '航线网络' : '', airline.show_members ? '成员名单' : '',
            ].filter(Boolean).join(' · ') || '全部隐藏' }}
          </div>
        </template>

        <!-- 页内实时预览：不跳转、不开新标签，按对外主页样式渲染未保存的内容 -->
        <div v-if="showPreview" class="pub-preview">
          <div class="pub-preview-bar">
            <Icon name="globe" :size="14" />
            <span>对外主页预览</span>
            <code>/va/{{ airline.icao }}</code>
            <span class="pub-preview-hint">{{ canManage ? '实时反映上方编辑内容，含未保存的改动' : '访客看到的样子' }}</span>
          </div>

          <div class="pub-preview-card" style="padding: 24px">
            <div style="display: flex; gap: 18px; align-items: center; flex-wrap: wrap">
              <div class="va-badge" :style="previewLogo ? `background-image:url(${previewLogo});background-size:cover` : ''">
                <template v-if="!previewLogo">{{ airline.icao }}</template>
              </div>
              <div style="flex: 1; min-width: 200px">
                <div style="font-size: 22px; font-weight: 700; letter-spacing: -0.5px">
                  {{ previewName || airline.name }}
                </div>
                <div v-if="previewSlogan" class="pub-preview-slogan">{{ previewSlogan }}</div>
                <div class="list-sub" style="margin-top: 4px">
                  {{ airline.icao }} · CEO {{ airline.ceo }} · 成立于 {{ airline.createdAt?.slice(0, 10) }}
                </div>
                <p class="pub-preview-desc">{{ previewDescription || '这家航司还没有填写简介。' }}</p>
              </div>
            </div>

            <div v-if="previewFlags.showStats" class="grid grid-4" style="margin-top: 20px">
              <div class="stat"><div class="stat-num">{{ data.members.length }}</div><div class="stat-label">在册成员</div></div>
              <div class="stat"><div class="stat-num">{{ data.routes.length }}</div><div class="stat-label">运营航线</div></div>
              <div class="stat"><div class="stat-num">—</div><div class="stat-label">累计飞行小时</div></div>
              <div class="stat"><div class="stat-num">—</div><div class="stat-label">已完成航班</div></div>
            </div>
          </div>

          <div v-if="previewWelcome" class="pub-preview-card pub-preview-welcome" style="margin-top: 12px">
            <div class="card-title"><Icon name="megaphone" :size="16" /> 欢迎语</div>
            <p class="pub-preview-welcome-text">{{ previewWelcome }}</p>
          </div>

          <div v-if="previewFlags.showFleet && previewFleet.length" class="pub-preview-card" style="margin-top: 12px">
            <div class="card-title">机队</div>
            <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px">
              <span v-for="f in previewFleet" :key="f" class="tag tag-blue">{{ f }}</span>
            </div>
          </div>

          <div v-if="previewFlags.showRoutes || previewFlags.showMembers" class="grid grid-2" style="margin-top: 12px">
            <div v-if="previewFlags.showRoutes" class="pub-preview-card">
              <div class="card-title">航线网络，{{ data.routes.length }}</div>
              <div v-for="r in data.routes.slice(0, 6)" :key="r.id" class="list-item">
                <div class="list-main">
                  <div class="list-title">
                    <span class="tag tag-blue" style="margin-right: 8px">{{ r.dep }}-{{ r.arr }}</span>
                    <span v-if="r.flight_no" class="tag">{{ r.flight_no }}</span>
                  </div>
                  <div v-if="r.aircraft" class="list-sub">机型 {{ r.aircraft }}</div>
                </div>
              </div>
              <div v-if="!data.routes.length" class="empty">暂未公布航线</div>
            </div>
            <div v-if="previewFlags.showMembers" class="pub-preview-card">
              <div class="card-title">成员名单，{{ data.members.length }}</div>
              <div v-for="m in data.members.slice(0, 6)" :key="m.id" class="list-item">
                <UserAvatar :user="m" :size="30" />
                <div class="list-main">
                  <div class="list-title">
                    <UserTag :badge="m.equipped_badge" :title="m.equipped_title">{{ m.username }}</UserTag>
                    <span :class="m.role === 'ceo' ? 'tag tag-red' : 'tag tag-blue'" style="margin-left: 6px">
                      {{ m.role === 'ceo' ? 'CEO' : (m.pilot_rank || '学员') }}
                    </span>
                  </div>
                  <div class="list-sub">CID {{ m.cid }}</div>
                </div>
              </div>
              <div v-if="!data.members.length" class="empty">暂无成员</div>
            </div>
          </div>
          <div
            v-if="!previewFlags.showStats && !previewFlags.showFleet && !previewFlags.showRoutes && !previewFlags.showMembers"
            class="pub-preview-card pub-preview-welcome"
            style="margin-top: 12px"
          >
            <div class="list-sub" style="margin: 0">四个展示板块都已关闭，访客只会看到上面的航司名片。</div>
          </div>
        </div>
      </div>

      <!-- 航司内部动态 -->
</template>

<style scoped>
.pub-preview { margin-top: 22px; padding-top: 18px; border-top: 1px dashed var(--border); }
.pub-preview-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }
.pub-preview-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; font-size: 13px; font-weight: 500; color: var(--text-2); }
.pub-preview-bar code { padding: 2px 8px; border-radius: 6px; font-size: 12px; color: var(--blue); background: rgba(0, 113, 227, 0.1); }
.pub-preview-hint { font-size: 12px; font-weight: 400; color: var(--gray); }
.pub-preview-slogan { margin-top: 4px; font-size: 13.5px; font-weight: 500; color: var(--blue); }
.pub-preview-desc { margin-top: 10px; font-size: 13.5px; line-height: 1.7; color: var(--text-2); white-space: pre-wrap; word-break: break-word; }
.pub-preview-welcome { border-left: 3px solid var(--blue); }
.pub-preview-welcome-text { font-size: 13.5px; line-height: 1.75; white-space: pre-wrap; word-break: break-word; margin-top: 6px; }
</style>
