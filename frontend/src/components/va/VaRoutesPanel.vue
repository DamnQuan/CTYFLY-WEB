<script setup>
import { inject } from 'vue';
import AirportInput from '../AirportInput.vue';
import CheckBox from '../CheckBox.vue';
const {
  addRoute,
  canManage,
  csvInput,
  data,
  deleteRoute,
  importRoutesCsv,
  importingCsv,
  nm,
  pickCsv,
  routeForm,
} = inject('airlinePage');
</script>

<template>
<div class="glass card">
        <div class="card-title">航线网络，{{ data.routes.length }}</div>
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
              <div class="field" style="margin-bottom: 10px"><AirportInput v-model="routeForm.dep" placeholder="起飞 ICAO，如 ZBAA" /></div>
              <div class="field" style="margin-bottom: 10px"><AirportInput v-model="routeForm.arr" placeholder="落地 ICAO，如 ZSPD" /></div>
              <div class="field" style="margin-bottom: 10px">
            <CheckBox v-model="routeForm.intl" label="国际航线（国际备用油规章）" />
          </div>
          <div class="field" style="margin-bottom: 10px"><input v-model="routeForm.flightNo" class="input input-icao" maxlength="8" placeholder="航班号，选填" /></div>
              <div class="field" style="margin-bottom: 10px"><input v-model="routeForm.aircraft" class="input input-icao" maxlength="16" placeholder="机型，选填 A320" /></div>
              <div class="field" style="margin-bottom: 10px"><input v-model.number="routeForm.baseSalary" class="input" type="number" min="0" placeholder="基础工资，默认 200" /></div>
            </div>
            <input v-model="routeForm.notes" class="input" style="margin-bottom: 10px" placeholder="备注，选填" />
                          <button class="btn btn-primary btn-sm" @click="addRoute">添加航线</button>
              <button class="btn btn-ghost btn-sm" :disabled="importingCsv" @click="pickCsv">导入 CSV</button>
              <input ref="csvInput" type="file" accept=".csv" style="display: none" @change="importRoutesCsv" />
          </div>
        </template>
      </div>

      <!-- 升级考核 -->
</template>
