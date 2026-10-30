<script setup>
import { inject } from 'vue';
import { fmtTime } from '../../utils.js';
import DatePicker from '../DatePicker.vue';
import UserAvatar from '../UserAvatar.vue';
const {
  STATUS_MAP,
  canManage,
  canSubmitExam,
  examForm,
  examProgress,
  examSubmitHint,
  exams,
  pendingExams,
  reviewExam,
  submitExam,
  submittingExam,
} = inject('airlinePage');
</script>

<template>
<div class="glass card">
        <div class="card-title">升级考核</div>
        <div class="card-sub">
          副驾驶飞满 <strong>50 小时</strong> 可申请机长考核；机长飞满 <strong>200 小时</strong> 可申请教员考核，CEO 审核通过后晋升
        </div>

        <!-- 我的晋升进度 -->
        <div v-if="examProgress" class="exam-progress">
          <template v-if="examProgress.maxed">
            <div class="exam-progress-title">
              当前等级 {{ examProgress.rank }} · 累计 {{ examProgress.hours }} h
              <span class="tag tag-blue" style="margin-left: 6px">已满级</span>
            </div>
            <div class="list-sub" style="margin-top: 4px">已达到最高可考核等级</div>
          </template>
          <template v-else>
            <div class="exam-progress-title">
              当前等级 {{ examProgress.rank }} · 累计 {{ examProgress.hours }} h
              <span class="tag tag-blue" style="margin-left: 6px">下一级：{{ examProgress.target }}</span>
            </div>
            <div class="exam-progress-bar"><i :style="{ width: examProgress.pct + '%' }"></i></div>
            <div class="list-sub" style="margin-top: 6px">
              <template v-if="examProgress.hasPending">{{ examProgress.target }}考核审核中，通过后晋升</template>
              <template v-else-if="examProgress.eligible">已满足 {{ examProgress.need }} h 要求，可申请{{ examProgress.target }}考核</template>
              <template v-else>距{{ examProgress.target }}考核还差 {{ examProgress.remain.toFixed(1) }} h，需 {{ examProgress.need }} h</template>
            </div>
          </template>
        </div>

        <!-- 成员提交考核 -->
        <div style="margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid var(--border)">
          <div class="grid grid-2" style="gap: 12px">
            <div class="field" style="margin-bottom: 0">
              <label class="label">考核飞行日期</label>
              <DatePicker v-model="examForm.flightDate" mode="date" placeholder="选择日期" />
            </div>
            <div class="field" style="margin-bottom: 0">
              <label class="label">执飞机型</label>
              <input v-model="examForm.aircraft" class="input input-icao" maxlength="16" placeholder="如 A320" />
            </div>
          </div>
          <div class="field" style="margin-top: 12px; margin-bottom: 0">
            <label class="label">考核航段</label>
            <input v-model="examForm.routeFlown" class="input" maxlength="20" placeholder="如 ZBAA-ZSPD" />
          </div>
          <input v-model="examForm.notes" class="input" style="margin-top: 12px" placeholder="考核说明，如航线、进离场程序、特殊情况处置等" />
          <button class="btn btn-primary" style="margin-top: 12px" :disabled="submittingExam || !canSubmitExam" @click="submitExam">
            {{ submittingExam ? '提交中…' : '提交考核申请' }}
          </button>
          <span class="hint" style="display: inline-block; margin-left: 10px">{{ examSubmitHint }}</span>
        </div>

        <!-- 管理成员待审核，CEO / 部长-->
        <template v-if="canManage && pendingExams.length">
          <div class="label" style="margin-bottom: 8px">待审核考核，{{ pendingExams.length }}</div>
          <div v-for="e in pendingExams" :key="e.id" class="list-item">
            <UserAvatar :user="e" :size="34" />
            <div class="list-main">
              <div class="list-title">
                <span class="tag tag-orange" style="margin-right: 8px">{{ e.target_rank }}考核</span>
                {{ e.username }}，CID {{ e.cid }}
              </div>
              <div class="list-sub">
                {{ e.route_flown || '—' }} · {{ e.aircraft || '机型未填' }} · {{ e.flight_date || '-' }}
                <template v-if="e.notes"> · {{ e.notes }}</template>
              </div>
            </div>
            <div style="display: flex; gap: 8px">
              <button class="btn btn-primary btn-sm" @click="reviewExam(e, 'approve')">通过并晋升</button>
              <button class="btn btn-danger btn-sm" @click="reviewExam(e, 'reject')">驳回</button>
            </div>
          </div>
        </template>

        <!-- 考核记录 -->
        <div class="label" style="margin: 10px 0 4px">{{ canManage ? '全部考核记录' : '我的考核记录' }}</div>
        <div v-for="e in exams" :key="e.id" class="list-item">
          <div class="list-main">
            <div class="list-title">
              <span class="tag tag-blue" style="margin-right: 8px">{{ e.target_rank }}考核</span>
              <template v-if="canManage">{{ e.username }} · </template>
              {{ e.route_flown || '未填航段' }}
            </div>
            <div class="list-sub">
              <template v-if="e.aircraft">{{ e.aircraft }} · </template>
              <template v-if="e.flight_date">考核日期 {{ e.flight_date }} · </template>
              <template v-if="e.status === 'rejected'">驳回原因：{{ e.reject_reason }} · </template>
              提交于 {{ fmtTime(e.created_at) }}
            </div>
          </div>
          <span class="tag" :class="STATUS_MAP[e.status]?.cls">{{ STATUS_MAP[e.status]?.text }}</span>
        </div>
        <div v-if="!exams.length" class="empty">暂无考核记录</div>
      </div>

      <!-- 对外主页，CEO 编辑 / 成员预览-->
</template>

<style scoped>
.exam-progress { margin-top: 14px; margin-bottom: 16px; padding: 12px 14px; border-radius: var(--radius-sm); background: var(--surface); }
.exam-progress-title { font-size: 13.5px; font-weight: 500; }
.exam-progress-bar { margin-top: 9px; height: 6px; border-radius: 999px; background: var(--border); overflow: hidden; }
.exam-progress-bar i { display: block; height: 100%; border-radius: 999px; background: var(--blue); transition: width 0.3s ease; }
</style>
