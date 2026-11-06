<script setup>
import { inject } from 'vue';
import { fmtTime } from '../../utils.js';
import DatePicker from '../DatePicker.vue';
import SelectMenu from '../SelectMenu.vue';
import UserAvatar from '../UserAvatar.vue';
const {
  STATUS_MAP,
  canManage,
  data,
  distanceRate,
  hourlyRate,
  isMember,
  pendingReports,
  reportForm,
  reports,
  reportsLoading,
  reviewReport,
  submitReport,
  submitting,
} = inject('airlinePage');
</script>

<template>
<div class="glass card" style="margin-bottom: 16px">
        <div class="card-title">飞行报告</div>

        <!-- 成员提交表单 -->
        <div v-if="isMember" style="margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid var(--border)">
          <div class="card-sub">飞完航司航线后提交报告，CEO 审核通过后自动发放工资，航线基础工资 + 时长 × 时薪 {{ hourlyRate }}/h</div>
          <div class="grid grid-2" style="gap: 12px">
            <div class="field" style="margin-bottom: 0">
              <label class="label">航线 <span style="color: var(--red)">*</span></label>
              <SelectMenu
                v-model="reportForm.routeId"
                placeholder="选择航线"
                :options="data.routes.map((r) => ({ value: r.id, label: `${r.dep}-${r.arr}${r.flight_no ? `（${r.flight_no}）` : ''}` }))"
              />
            </div>
            <div class="field" style="margin-bottom: 0">
              <label class="label">机型</label>
              <input v-model="reportForm.aircraft" class="input input-icao" maxlength="16" placeholder="如 A320（选填）" />
            </div>
            <div class="field" style="margin-bottom: 0">
              <label class="label">飞行时长（小时）<span style="color: var(--red)">*</span></label>
              <input v-model.number="reportForm.hours" class="input" type="number" step="0.1" min="0.1" max="24" />
            </div>
            <div class="field" style="margin-bottom: 0">
              <label class="label">飞行日期</label>
              <DatePicker v-model="reportForm.flightDate" mode="date" placeholder="选择飞行日期" />
            </div>
          </div>
          <input v-model="reportForm.notes" class="input" style="margin-top: 12px" placeholder="备注（选填）" />
          <div style="margin-top: 12px">
            <button class="btn btn-primary" :disabled="submitting" @click="submitReport">
              {{ submitting ? '提交中…' : '提交飞行报告' }}
            </button>
            <span class="hint" style="display: inline-block; margin-left: 10px">
              预计工资 = 航线基础 + 时长 × {{ hourlyRate }} + 距离 × {{ distanceRate }}
            </span>
          </div>
        </div>

        <!-- 管理成员待审核，CEO / 部长-->
        <template v-if="canManage && pendingReports.length">
          <div class="label" style="margin-bottom: 8px">待审核（{{ pendingReports.length }}）</div>
          <div v-for="r in pendingReports" :key="r.id" class="list-item">
            <UserAvatar :user="r" :size="34" />
            <div class="list-main">
              <div class="list-title">
                <span class="tag tag-blue" style="margin-right: 8px">{{ r.dep }}-{{ r.arr }}</span>
                {{ r.username }} · {{ r.hours }} h · {{ r.aircraft || '机型未填' }}
              </div>
              <div class="list-sub">飞行日期 {{ r.flight_date || '-' }} · 提交于 {{ fmtTime(r.created_at) }}<template v-if="r.notes"> · {{ r.notes }}</template></div>
              <div v-if="r.verify_score >= 0" class="list-sub">
                ACARS 核验：<b>{{ r.verify_score }} 分</b><template v-if="r.verify_detail"> · {{ r.verify_detail }}</template>
              </div>
            </div>
            <div style="display: flex; gap: 8px">
              <button class="btn btn-primary btn-sm" @click="reviewReport(r, 'approve')">通过并发薪</button>
              <button class="btn btn-danger btn-sm" @click="reviewReport(r, 'reject')">驳回</button>
            </div>
          </div>
        </template>

        <!-- 报告列表 -->
        <div class="label" style="margin: 10px 0 4px">{{ canManage ? '全部报告' : '我的报告' }}</div>
        <div v-if="reportsLoading" class="loading">加载中…</div>
        <template v-else>
          <div v-for="r in reports" :key="r.id" class="list-item">
            <div class="list-main">
              <div class="list-title">
                <span class="tag tag-blue" style="margin-right: 8px">{{ r.dep }}-{{ r.arr }}</span>
                <template v-if="canManage">{{ r.username }} · </template>
                {{ r.hours }} h
                <span v-if="r.status === 'approved' && r.amount" class="tag tag-green" style="margin-left: 6px">+{{ r.amount }}</span>
              </div>
              <div class="list-sub">
                <template v-if="r.status === 'rejected'">驳回原因：{{ r.reject_reason }} · </template>
                <template v-if="r.verify_score >= 0">ACARS {{ r.verify_score }} 分 · </template>
                {{ fmtTime(r.created_at) }}
              </div>
            </div>
            <span class="tag" :class="STATUS_MAP[r.status]?.cls">{{ STATUS_MAP[r.status]?.text }}</span>
          </div>
          <div v-if="!reports.length" class="empty">暂无飞行报告</div>
        </template>
      </div>

      <!-- 成员名单 -->
</template>
