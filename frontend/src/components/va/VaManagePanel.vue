<script setup>
import { inject } from 'vue';
import { fmtTime } from '../../utils.js';
import AirportInput from '../AirportInput.vue';
import CheckBox from '../CheckBox.vue';
import DatePicker from '../DatePicker.vue';
import Icon from '../Icon.vue';
import SegmentedTabs from '../SegmentedTabs.vue';
import SelectMenu from '../SelectMenu.vue';
import UserAvatar from '../UserAvatar.vue';
import UserTag from '../UserTag.vue';

const {
  data, canManage, pendingMembers, pendingReports, pendingExams,
  payrollMonth, exporting, exportPayroll,
  ledger, ledgerLoading, ledgerLoadingMore, ledgerType, setLedgerType, loadLedger,
  money, signedMoney, nm, isCeo, hourlyRate, distanceRate, hub, savingRate, saveRate,
  positionOptions, setPosition, setMinister, removeMember, reviewMember,
  reviewReport, reviewExam,
  routeForm, addRoute, deleteRoute, pickCsv, csvInput, importRoutesCsv, importingCsv,
  pubForm, savingPub, showPreview, previewName, previewSlogan, previewDescription,
  previewWelcome, previewLogo, previewFlags, previewFleet, copyPublicLink,
  savePublicPage, airline,
} = inject('airlinePage');
</script>

<template>
<!-- 概览 -->
        <div class="glass card" style="margin-bottom: 16px">
          <div class="card-title">管理中心</div>
          <div class="card-sub">
            待审批成员 {{ pendingMembers }} 人 · 待审核报告 {{ pendingReports.length }} 份 · 待审核考核 {{ pendingExams.length }} 人
          </div>
        </div>

        <!-- 资金管理：公司余额 / 账本流水 / 经济参数 / 工资单导出，CEO + 部长，只读为主-->
        <div class="glass card" style="margin-bottom: 16px">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px">
            <div>
              <div class="card-title" style="margin-bottom: 2px">资金管理</div>
              <div class="card-sub" style="margin-bottom: 0">
                公司余额与账本流水，收入为正、支出为负。发薪仅通过飞行报告审核结算，此处不提供直接变动资金的入口
              </div>
            </div>
            <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap">
              <label class="label" style="margin: 0">工资单月份</label>
              <div style="width: 168px">
                <DatePicker v-model="payrollMonth" mode="month" :clearable="false" placeholder="选择月份" />
              </div>
              <button class="btn btn-dark btn-sm" :disabled="exporting" @click="exportPayroll">
                {{ exporting ? '导出中…' : '导出工资单 CSV' }}
              </button>
            </div>
          </div>

          <div v-if="ledgerLoading" class="loading">加载中…</div>
          <template v-else-if="ledger">
            <div class="grid grid-3" style="margin-top: 14px">
              <div class="stat"><div class="stat-num">{{ money(ledger.balance) }}</div><div class="stat-label">公司余额</div></div>
              <div class="stat"><div class="stat-num">{{ money(ledger.income) }}</div><div class="stat-label">累计收入</div></div>
              <div class="stat"><div class="stat-num">{{ money(ledger.expense) }}</div><div class="stat-label">累计支出（负数）</div></div>
            </div>
            <div class="card-sub" style="margin-top: 10px">
              账本净额 {{ money(ledger.net) }} · 近 30 天收入 {{ money(ledger.recent30.income) }} / 支出 {{ money(ledger.recent30.expense) }}
            </div>
            <div v-if="!ledger.reconciled" style="margin-top: 8px">
              <span class="tag tag-red">账实不符</span>
              <span class="list-sub" style="margin-left: 8px">
                公司余额 {{ money(ledger.balance) }} 与账本净额 {{ money(ledger.net) }} 不一致，请联系管理员核对
              </span>
            </div>

            <!-- 经济参数：直接决定全公司工资支出，仅 CEO 可改，后端同步收窄为 _require_ceo-->
            <div style="margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border)">
              <div class="label" style="margin-bottom: 8px">经济参数（决定全公司工资支出）</div>
              <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap">
                <label class="label" style="margin: 0">时薪</label>
                <input
                  v-if="isCeo" v-model.number="hourlyRate" class="input input-icao"
                  style="width: 84px; padding: 6px 10px" type="number" min="1" max="2000"
                />
                <span v-else class="tag tag-blue">{{ hourlyRate }}</span>
                <span style="font-size: 12.5px; color: var(--text-2)">/h</span>
                <label class="label" style="margin: 0">距离补贴</label>
                <input
                  v-if="isCeo" v-model.number="distanceRate" class="input input-icao"
                  style="width: 70px; padding: 6px 10px" type="number" min="0" max="100"
                />
                <span v-else class="tag tag-blue">{{ distanceRate }}</span>
                <span style="font-size: 12.5px; color: var(--text-2)">/NM</span>
                <label class="label" style="margin: 0">主基地</label>
                <input
                  v-if="isCeo" v-model="hub" class="input input-icao"
                  style="width: 76px; padding: 6px 10px; text-transform: uppercase"
                  maxlength="4" placeholder="ZBAA" @input="hub = hub.toUpperCase()"
                />
                <span v-else class="tag tag-blue">{{ hub || '未设' }}</span>
                <button v-if="isCeo" class="btn btn-ghost btn-sm" :disabled="savingRate" @click="saveRate">保存</button>
              </div>
              <div class="hourly-hint" style="margin-top: 8px">
                官方建议时薪（游戏币/h，按机型）：支线 80–95 · 窄体 100–125 · 宽体 150–200 · 旗舰 200+
                <template v-if="!isCeo"> · 经济参数仅 CEO 可修改</template>
              </div>
            </div>

            <!-- 账本流水：分页 + 类型筛选 -->
            <div style="margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border)">
              <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px">
                <div class="label" style="margin: 0">账本流水（{{ ledger.total }} 条）</div>
                <SegmentedTabs
                  :options="[{ value: '', label: '全部' }, { value: 'revenue', label: '收入' }, { value: 'expense', label: '支出' }]"
                  :model-value="ledgerType"
                  @update:model-value="setLedgerType"
                />
              </div>
              <div v-for="r in ledger.records" :key="r.id" class="list-item">
                <div class="list-main">
                  <div class="list-title">
                    <span :class="r.type === 'revenue' ? 'tag tag-blue' : 'tag tag-red'" style="margin-right: 8px">
                      {{ r.type === 'revenue' ? '收入' : '支出' }}
                    </span>
                    <span style="font-variant-numeric: tabular-nums">{{ signedMoney(r.amount) }}</span>
                  </div>
                  <div class="list-sub">
                    {{ r.note || '—' }}<template v-if="r.report_id"> · 关联报告 #{{ r.report_id }}</template>
                  </div>
                </div>
                <div class="list-sub">{{ fmtTime(r.created_at) }}</div>
              </div>
              <div v-if="!ledger.records.length" class="empty">暂无账本记录</div>
              <button
                v-if="ledger.records.length < ledger.total"
                class="btn btn-ghost btn-sm" style="margin-top: 10px"
                :disabled="ledgerLoadingMore" @click="loadLedger(true)"
              >
                {{ ledgerLoadingMore ? '加载中…' : `加载更多（还有 ${ledger.total - ledger.records.length} 条）` }}
              </button>
            </div>
          </template>
          <div v-else class="empty">资金数据加载失败</div>
        </div>

        <!-- 成员管理：加入申请审批 + 成员职位 / 部长任命 -->
        <div class="glass card" style="margin-bottom: 16px">
          <div class="card-title">成员管理</div>
          <div class="card-sub">职位按现实飞行部门阶梯设置：飞行教员 / 机长 / 副驾驶 / 二副 / 见习学员，留空即普通飞行员；移除成员与部长任命仅 CEO 可操作</div>

          <div v-if="data.applications.length" class="label" style="margin: 12px 0 4px">待审批加入申请（{{ data.applications.length }}）</div>
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

          <div class="label" style="margin: 14px 0 4px">正式成员（{{ data.members.length }}）</div>
          <div v-for="m in data.members" :key="m.id" class="list-item">
            <UserAvatar :user="m" :size="34" />
            <div class="list-main">
              <div class="list-title">
                <UserTag :badge="m.equipped_badge" :title="m.equipped_title">{{ m.username }}</UserTag>
                <span :class="m.role === 'ceo' ? 'tag tag-red' : 'tag'" style="margin-left: 6px">
                  {{ m.role === 'ceo' ? 'CEO' : (m.position || '飞行员') }}
                </span>
                <span v-if="m.minister && m.role !== 'ceo'" class="tag tag-purple" style="margin-left: 6px">部长</span>
                <span class="tag tag-blue" style="margin-left: 6px">飞行员等级 {{ m.pilot_rank || '学员' }}</span>
              </div>
              <div class="list-sub">CID {{ m.cid }} · 管制等级 {{ m.rating }} · 加入于 {{ fmtTime(m.joined_at) }}</div>
            </div>
            <div v-if="canManage && m.role !== 'ceo'" class="list-actions">
              <SelectMenu
                style="width: 140px"
                :model-value="m.position || ''"
                :options="[{ value: '', label: '未设置' }, ...positionOptions.map((x) => ({ value: x, label: x }))]"
                placeholder="设置职位"
                @update:model-value="(v) => setPosition(m, v)"
              />
              <button v-if="isCeo" class="btn btn-ghost btn-sm" @click="setMinister(m)">
                {{ m.minister ? '取消部长' : '任命部长' }}
              </button>
              <button v-if="isCeo" class="btn btn-danger btn-sm" @click="removeMember(m)">移除</button>
            </div>
          </div>
          <div v-if="!data.members.length" class="empty">暂无成员</div>
        </div>

        <!-- 航线管理：添加 / 删除航线 -->
        <div class="glass card" style="margin-bottom: 16px">
          <div class="card-title">航线管理（{{ data.routes.length }}）</div>
          <div v-for="r in data.routes" :key="r.id" class="list-item">
            <div class="list-main">
              <div class="list-title">
                <span class="tag tag-blue" style="margin-right: 8px">{{ r.dep }}-{{ r.arr }}</span>
                <span v-if="r.flight_no" class="tag" style="margin-right: 6px">{{ r.flight_no }}</span>
                <span v-if="r.aircraft" class="tag" style="margin-left: 6px">{{ r.aircraft }}</span>
              </div>
              <div class="list-sub">
                <template v-if="r.distance_nm != null">距离 {{ nm(r.distance_nm) }} NM · 基础工资 {{ r.base_salary }}<template v-if="r.notes"> · {{ r.notes }}</template></template>
                <template v-else-if="r.notes">{{ r.notes }}</template>
                <template v-else>未收录距离，导航数据无此机场时工资不计距离补贴</template>
              </div>
            </div>
            <button v-if="canManage" class="btn btn-danger btn-sm" @click="deleteRoute(r)">删除</button>
          </div>
          <div v-if="!data.routes.length" class="empty">暂无航线</div>

          <template v-if="canManage">
            <div style="margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--border)">
              <div class="label" style="margin-bottom: 8px">新增航线</div>
              <div class="grid grid-2" style="gap: 10px">
                <div class="field" style="margin-bottom: 10px"><AirportInput v-model="routeForm.dep" placeholder="起飞 ICAO（如 ZBAA）" /></div>
                <div class="field" style="margin-bottom: 10px"><AirportInput v-model="routeForm.arr" placeholder="落地 ICAO（如 ZSPD）" /></div>
                <div class="field" style="margin-bottom: 10px">
                  <CheckBox v-model="routeForm.intl" label="国际航线（国际备用油规章）" />
                </div>
                <div class="field" style="margin-bottom: 10px"><input v-model="routeForm.flightNo" class="input input-icao" maxlength="8" placeholder="航班号（选填）" /></div>
                <div class="field" style="margin-bottom: 10px"><input v-model="routeForm.aircraft" class="input input-icao" maxlength="16" placeholder="机型（选填，如 A320）" /></div>
                <div class="field" style="margin-bottom: 10px"><input v-model.number="routeForm.baseSalary" class="input" type="number" min="0" placeholder="基础工资（默认 200）" /></div>
              </div>
              <input v-model="routeForm.notes" class="input" style="margin-bottom: 10px" placeholder="备注（选填）" />
                            <button class="btn btn-primary btn-sm" @click="addRoute">添加航线</button>
              <button class="btn btn-ghost btn-sm" :disabled="importingCsv" @click="pickCsv">导入 CSV</button>
              <input ref="csvInput" type="file" accept=".csv" style="display: none" @change="importRoutesCsv" />
            </div>
          </template>
        </div>

        <!-- 飞行报告审核：待审核列表 + 通过 / 驳回，提交表单不在此处-->
        <div class="glass card" style="margin-bottom: 16px">
          <div class="card-title">飞行报告审核（{{ pendingReports.length }}）</div>
          <template v-if="pendingReports.length">
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
          <div v-else class="empty">暂无待审核的飞行报告</div>
        </div>

        <!-- 考核审核：待审核列表 + 通过 / 驳回 -->
        <div class="glass card" style="margin-bottom: 16px">
          <div class="card-title">考核审核（{{ pendingExams.length }}）</div>
          <template v-if="pendingExams.length">
            <div v-for="e in pendingExams" :key="e.id" class="list-item">
              <UserAvatar :user="e" :size="34" />
              <div class="list-main">
                <div class="list-title">
                  <span class="tag tag-orange" style="margin-right: 8px">{{ e.target_rank }}考核</span>
                  {{ e.username }}（CID {{ e.cid }}）
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
          <div v-else class="empty">暂无待审核的考核申请</div>
        </div>

        <!-- 对外主页设置：编辑 + 保存 + 页内预览 -->
        <div class="glass card" style="margin-bottom: 16px">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px">
            <div>
              <div class="card-title" style="margin-bottom: 2px">对外主页设置</div>
              <div class="card-sub" style="margin-bottom: 0">这里的内容会展示在公开主页上，任何人都可以访问</div>
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

          <div class="grid grid-2" style="margin-top: 18px">
            <div class="field">
              <label class="label">航司名称 <span style="color: var(--red)">*</span></label>
              <input v-model="pubForm.name" class="input" maxlength="20" />
            </div>
            <div class="field">
              <label class="label">标语 <span class="optional">选填（显示在名称下方）</span></label>
              <input v-model="pubForm.slogan" class="input" maxlength="20" placeholder="如 安全第一，准点至上" />
            </div>
          </div>
          <div class="field">
            <label class="label">航司简介</label>
            <textarea v-model="pubForm.description" class="textarea" rows="3" maxlength="300"
                      placeholder="介绍航司定位、主基地与运营风格…"></textarea>
          </div>
          <div class="field">
            <label class="label">欢迎语 / 公告 <span class="optional">选填（主页上的醒目区块）</span></label>
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

          <!-- 页内实时预览：不跳转、不开新标签，按对外主页样式渲染未保存的内容 -->
          <div v-if="showPreview" class="pub-preview">
            <div class="pub-preview-bar">
              <Icon name="globe" :size="14" />
              <span>对外主页预览</span>
              <code>/va/{{ airline.icao }}</code>
              <span class="pub-preview-hint">实时反映上方编辑内容，含未保存的改动</span>
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
                <div class="card-title">航线网络（{{ data.routes.length }}）</div>
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
                <div class="card-title">成员名单（{{ data.members.length }}）</div>
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
</template>

<style scoped>
.hourly-hint { font-size: 12px; color: var(--gray); }
.pub-preview {
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px dashed var(--border);
}
.pub-preview-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}
.pub-preview-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-2);
}
.pub-preview-bar code {
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--blue);
  background: rgba(0, 113, 227, 0.1);
}
.pub-preview-hint { font-size: 12px; font-weight: 400; color: var(--gray); }
.pub-preview-slogan {
  margin-top: 4px;
  font-size: 13.5px;
  font-weight: 500;
  color: var(--blue);
}
.pub-preview-desc {
  margin-top: 10px;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
}
.pub-preview-welcome { border-left: 3px solid var(--blue); }
.pub-preview-welcome-text {
  font-size: 13.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  margin-top: 6px;
}
</style>
