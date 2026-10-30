<script setup>
import { inject } from 'vue';
import { fmtTime } from '../../utils.js';
import Icon from '../Icon.vue';
import LogoUploader from '../LogoUploader.vue';
import SegmentedTabs from '../SegmentedTabs.vue';
import UserAvatar from '../UserAvatar.vue';
import UserTag from '../UserTag.vue';
const {
  airline,
  canManage,
  cancelTransfer,
  copyPublicLink,
  data,
  disband,
  inOtherAirline,
  isCeo,
  isMember,
  join,
  joinLoading,
  leave,
  logoUrl,
  myMembership,
  myTransfer,
  openPublicPreview,
  pendingJoin,
  pendingTransfers,
  rankFor,
  reviewMember,
  reviewTransfer,
  saveLogo,
  savingLogo,
  stats,
  tab,
  tabOptions,
  transfer,
  transferLoading,
} = inject('airlinePage');
</script>

<template>
<!-- 航司信息 -->
      <div class="glass card" style="margin-bottom: 16px">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 14px">
          <div style="display: flex; gap: 16px; align-items: center">
            <div class="va-badge" :style="airline.logo_url ? `background-image:url(${airline.logo_url});background-size:cover` : ''">
              <template v-if="!airline.logo_url">{{ airline.icao }}</template>
            </div>
            <div>
              <div class="card-title" style="margin-bottom: 2px">
                {{ airline.name }}
                <span class="tag tag-green" style="margin-left: 8px">运营中</span>
              </div>
              <div class="card-sub" style="margin-bottom: 0">
                CEO：{{ airline.ceo }} ·
                <Icon name="users" :size="12" /> {{ airline.member_count }} 名成员 ·
                {{ airline.route_count }} 条航线
              </div>
              <div class="list-sub" style="margin-top: 6px">{{ airline.description || '暂无简介' }}</div>
            </div>
          </div>
          <div style="display: flex; gap: 8px; flex-wrap: wrap">
            <!-- 不跳转、不开新标签：成员就地切到「对外主页」选项卡并展开预览 -->
            <button v-if="isMember" class="btn btn-ghost btn-sm" @click="openPublicPreview">
              <Icon name="globe" :size="14" /> 对外主页
            </button>
            <button v-else class="btn btn-ghost btn-sm" @click="copyPublicLink">
              <Icon name="link" :size="14" /> 复制主页链接
            </button>
            <button
              v-if="!myMembership && !isMember"
              class="btn btn-primary"
              :disabled="joinLoading"
              @click="join"
            >{{ joinLoading ? '提交中…' : '申请加入' }}</button>
            <span v-if="pendingJoin" class="tag tag-orange" style="align-self: center">加入申请审核中</span>

            <!-- 已在别家航司：跳槽 -->
            <template v-if="inOtherAirline && !myTransfer">
              <button class="btn btn-dark" :disabled="transferLoading" @click="transfer">
                <Icon name="trending" :size="15" /> {{ transferLoading ? '提交中…' : '我要跳槽' }}
              </button>
            </template>
            <template v-if="inOtherAirline && myTransfer">
              <span class="tag tag-orange" style="align-self: center">
                跳槽申请审核中 · 现属 {{ myMembership.icao }}
              </span>
              <button class="btn btn-ghost btn-sm" @click="cancelTransfer">撤销申请</button>
            </template>
            <span
              v-if="myMembership && myMembership.role === 'ceo' && !isMember"
              class="tag tag-red"
              style="align-self: center"
            >CEO 无法跳槽</span>
            <span
              v-if="myMembership && !isMember && !myTransfer && myMembership.status === 'pending'"
              class="tag tag-orange"
              style="align-self: center"
            >你在 {{ myMembership.icao }} 的加入申请审核中</span>

            <button
              v-if="isMember && myMembership.role !== 'ceo'"
              class="btn btn-danger btn-sm"
              @click="leave"
            >退出航司</button>
            <button v-if="isCeo" class="btn btn-danger btn-sm" @click="disband">解散航司</button>
          </div>
        </div>
      </div>

      <!-- CEO：运营统计，时薪/距离补贴/主基地/工资单导出已归入上方「资金管理」卡-->
      <div v-if="isCeo && stats" class="glass card" style="margin-bottom: 16px">
        <div class="card-title" style="margin: 0">运营统计</div>
        <div class="grid grid-3" style="margin-top: 14px">
          <div class="stat"><div class="stat-num">{{ stats.reports }}</div><div class="stat-label">已通过报告</div></div>
          <div class="stat"><div class="stat-num">{{ stats.totalHours }}</div><div class="stat-label">总飞行时长，小时</div></div>
          <div class="stat"><div class="stat-num">{{ stats.totalPayout }}</div><div class="stat-label">累计发放工资</div></div>
        </div>
        <div style="margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border)">
          <label class="label">航司 Logo</label>
          <LogoUploader v-model="logoUrl" :fallback="airline.icao" />
          <button class="btn btn-ghost btn-sm" style="margin-top: 10px" :disabled="savingLogo" @click="saveLogo">
            {{ savingLogo ? '保存中…' : '保存 Logo' }}
          </button>
        </div>
        <div class="table-wrap" style="margin-top: 14px">
          <table class="table">
            <thead><tr><th>成员</th><th>飞行时长</th><th>累计收入</th><th>等级</th></tr></thead>
            <tbody>
              <tr v-for="p in stats.perMember" :key="p.cid">
                <td>{{ p.username }}，CID {{ p.cid }}</td>
                <td>{{ p.hours }} h</td>
                <td>{{ p.earned }}</td>
                <td><span class="tag tag-blue">{{ rankFor(p.hours) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 加入申请审批，CEO / 部长-->
      <div v-if="canManage" class="glass card" style="margin-bottom: 16px">
        <div class="card-title">加入申请，{{ data.applications.length }}</div>
        <div v-for="m in data.applications" :key="m.id" class="list-item">
          <UserAvatar :user="m" :size="36" />
          <div class="list-main">
            <div class="list-title">
              <UserTag :badge="m.equipped_badge" :title="m.equipped_title">{{ m.username }}</UserTag>
              CID {{ m.cid }}
            </div>
            <div class="list-sub">申请于 {{ fmtTime(m.created_at) }} · 管制等级 {{ m.rating }}</div>
          </div>
          <div style="display: flex; gap: 8px">
            <button class="btn btn-primary btn-sm" @click="reviewMember(m, 'approve')">通过</button>
            <button class="btn btn-danger btn-sm" @click="reviewMember(m, 'reject')">拒绝</button>
          </div>
        </div>
        <div v-if="!data.applications.length" class="empty">暂无待审批的加入申请</div>
      </div>

      <!-- CEO：跳槽，转司审批-->
      <div v-if="isCeo" class="glass card" style="margin-bottom: 16px">
        <div class="card-title">跳槽申请，{{ pendingTransfers.length }}</div>
        <div class="card-sub">批准后该飞行员将解除与原航司的成员关系，直接加入本航司</div>
        <div v-for="t in pendingTransfers" :key="t.id" class="list-item">
          <UserAvatar :user="t" :size="36" />
          <div class="list-main">
            <div class="list-title">
              <UserTag :badge="t.equipped_badge" :title="t.equipped_title">{{ t.username }}</UserTag>
              CID {{ t.cid }}
            </div>
            <div class="list-sub">
              来自 <strong>{{ t.from_icao }} {{ t.from_name }}</strong> · 申请于 {{ fmtTime(t.created_at) }}
            </div>
            <div v-if="t.reason" class="list-sub">理由：{{ t.reason }}</div>
          </div>
          <div style="display: flex; gap: 8px">
            <button class="btn btn-primary btn-sm" @click="reviewTransfer(t, 'approve')">接收</button>
            <button class="btn btn-danger btn-sm" @click="reviewTransfer(t, 'reject')">驳回</button>
          </div>
        </div>
        <div v-if="!pendingTransfers.length" class="empty">暂无待审批的跳槽申请</div>
      </div>

      <!-- 选项卡 -->
      <SegmentedTabs class="lg" style="margin-bottom: 16px" :options="tabOptions" v-model="tab" />

      <!-- ============ 管理中心，CEO / 部长：聚合日常管理卡片 ============-->
</template>

<style scoped>
.va-badge {
  width: 56px;
  height: 56px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: linear-gradient(135deg, #0a84ff, #0071e3);
  background-size: cover;
  color: #fff;
  font-weight: 700;
  font-size: 14px;
  letter-spacing: 0.5px;
}
</style>
