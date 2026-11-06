<script setup>
import { inject } from 'vue';
import { fmtTime } from '../../utils.js';
import SelectMenu from '../SelectMenu.vue';
import UserAvatar from '../UserAvatar.vue';
import UserTag from '../UserTag.vue';
const {
  canManage,
  data,
  isCeo,
  positionOptions,
  removeMember,
  setMinister,
  setPosition,
} = inject('airlinePage');
</script>

<template>
<div class="glass card">
        <div class="card-title">成员名单（{{ data.members.length }}）</div>
        <div class="card-sub" v-if="canManage">职位按现实飞行部门阶梯设置：飞行教员 / 机长 / 副驾驶 / 二副 / 见习学员，留空即普通飞行员</div>
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

      <!-- 航线网络 -->
</template>
