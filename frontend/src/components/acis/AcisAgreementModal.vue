<script setup>
/**
 * ACIS 首次使用须知：全屏液态玻璃模态框，禁止原生 alert/confirm。
 * 必须点击同意后关闭，状态写入 localStorage。
 */
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import acisLogo from '../../assets/acis-mark.png';

const OPEN_KEY = 'acis_agreed';
const ANON_KEY = 'acis_anon_id';
const open = ref(false);
const bodyEl = ref(null);
let previousOverflow = '';

const paragraphs = [
  'ACIS是由CTY主持开发的一款飞圈事件智能检索系统。在ACIS中，用户可便捷查询近年来飞友圈内发生的部分事件，并可对事件内容进行纠错或投稿新事件，以协助完善ACIS资料库。CTY将对资料库进行长期自主更新，以确保事件检索的准确性与时效性。',
  'ACIS的初期资料由CTY人工收集，可能存在内容偏差或重要事件未收录的情况。用户在使用时应注意甄别，并及时纠错或补充，共同参与ACIS的建设。',
  'ACIS收集事件遵循四大原则：真实可信、传播广泛、合法合规、中立客观。CTY行政部对事件筛选拥有最终决定权，并将严格遵守上述原则对事件进行审核，确保ACIS的权威性与可信度。ACIS坚持以真实为本，不受任何外部势力干扰而致使事件记录失真。',
  '原则上，ACIS在事件收集过程中将严格保密投稿人及事件当事人的个人信息。记录中确需提及事件当事人的，将使用其CID或网名代替，通常情况下不予展示个人QQ号。',
  '在收集社群成立、解散及纠纷等相关事件时，ACIS优先收录具有较高知名度的社群内容，对大量微型社群的成立与解散事件不予收录。同时，ACIS亦收录部分在圈内作出突出贡献的个人资料，展示时不会涉及个人敏感信息。',
  'ACIS亦收录部分圈内负面事件，旨在引导用户汲取教训、避免同类事件再次发生，绝非出于引战或挑起负面情绪之目的。',
  '针对部分具有重大影响力的著名事件，ACIS将发布中立客观的评论。该评论仅代表CTY官方视角的客观梳理，不构成对任何一方的最终定性，亦不代表对相关事件的法律裁决，且不会误导用户判断。',
  '因资料库存储空间有限，如遇容量满载，ACIS将视情况删除部分次要事件，删除后将无法检索该事件。用户提交的纠错与新事件投稿，需经CTY行政部审核通过后方可录入资料库。CTY有权对投稿内容进行修改、删减或不予收录，且无需对未采纳的投稿进行逐一解释。',
  '如当事人认为收录内容侵犯其合法权益或存在严重失实，可通过官方渠道联系CTY行政部申请复核或下架。一经核实，CTY将依法依规予以修正或删除。因不可抗力、网络攻击或服务器故障导致资料库数据丢失、损坏或服务中断的，CTY将在合理范围内尽力恢复，但不承担由此产生的连带法律责任。',
  'CTY持有ACIS的一切所有权与编辑权。',
];

function ensureAnonId() {
  try {
    if (!localStorage.getItem(ANON_KEY)) {
      const id = typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `acis-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      localStorage.setItem(ANON_KEY, id);
    }
  } catch { /* 存储不可用时由后端按 IP 派生匿名标识 */ }
}

function lockScroll() {
  previousOverflow = document.body.style.overflow;
  document.body.style.overflow = 'hidden';
}

function unlockScroll() {
  document.body.style.overflow = previousOverflow;
}

function accept() {
  try {
    localStorage.setItem(OPEN_KEY, 'true');
  } catch { /* 忽略存储异常 */ }
  ensureAnonId();
  open.value = false;
  unlockScroll();
}

onMounted(async () => {
  lockScroll();
  await nextTick();
  try {
    open.value = localStorage.getItem(OPEN_KEY) !== 'true';
  } catch {
    open.value = true;
  }
  if (!open.value) unlockScroll();
});

onBeforeUnmount(unlockScroll);
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="acis-modal-mask" role="dialog" aria-modal="true" aria-labelledby="acis-modal-title">
      <div class="acis-modal">
        <div class="acis-modal-head">
          <img :src="acisLogo" alt="ACIS" class="acis-modal-logo" />
          <div>
            <div id="acis-modal-title" class="acis-modal-title">ACIS使用须知</div>
            <div class="acis-modal-sub">首次使用前请阅读并确认</div>
          </div>
        </div>
        <div ref="bodyEl" class="acis-modal-body">
          <p v-for="(text, index) in paragraphs" :key="index" class="acis-modal-p">{{ text }}</p>
          <p class="acis-modal-p">
            反馈与申诉渠道：请通过CTY行政部邮箱
            <a href="mailto:support@ccflysim.cn" class="acis-mail">support@ccflysim.cn</a>
            或联系下方负责人员。
          </p>
          <div class="acis-modal-contact">
            <div>ACIS 技术主管：Changyang Gui (5966)</div>
            <div>ACIS 内容主管：Xiong Shu (6738)</div>
          </div>
        </div>
        <div class="acis-modal-foot">
          <button class="btn btn-primary acis-agree" type="button" @click="accept">确定并同意</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.acis-modal-mask {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(6, 18, 38, 0.52);
  backdrop-filter: blur(22px) saturate(1.2);
  -webkit-backdrop-filter: blur(22px) saturate(1.2);
}
.acis-modal {
  width: min(900px, 100%);
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.5);
  background: linear-gradient(150deg, rgba(255, 255, 255, 0.86), rgba(224, 242, 255, 0.72));
  box-shadow: 0 30px 90px rgba(0, 30, 70, 0.3);
  overflow: hidden;
}
.acis-modal-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 20px 24px 16px;
  border-bottom: 1px solid rgba(10, 132, 255, 0.14);
}
.acis-modal-logo { width: 54px; height: 50px; object-fit: contain; border-radius: 12px; }
.acis-modal-title { font-size: 21px; font-weight: 700; letter-spacing: 0.2px; }
.acis-modal-sub { margin-top: 3px; color: var(--text-2); font-size: 12.5px; }
.acis-modal-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 26px;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.acis-modal-body::-webkit-scrollbar { display: none; width: 0; height: 0; }
.acis-modal-p { margin: 0 0 13px; color: var(--text); font-size: 13.5px; line-height: 1.9; text-align: justify; }
.acis-mail { color: #0a84ff; font-weight: 600; text-decoration: none; }
.acis-mail:hover { text-decoration: underline; }
.acis-modal-contact { margin-top: 16px; padding-top: 12px; border-top: 1px dashed rgba(10, 132, 255, 0.2); color: var(--text-2); font-size: 13px; line-height: 1.9; }
.acis-modal-foot { padding: 14px 24px 18px; border-top: 1px solid rgba(10, 132, 255, 0.14); display: flex; justify-content: flex-end; }
.acis-agree { min-width: 160px; }
@media (max-width: 620px) {
  .acis-modal-mask { padding: 12px; }
  .acis-modal { max-height: calc(100vh - 24px); border-radius: 18px; }
  .acis-modal-head { padding: 16px; }
  .acis-modal-body { padding: 14px 16px; }
  .acis-modal-p { font-size: 13px; }
  .acis-modal-foot { padding: 12px 16px 14px; }
  .acis-agree { width: 100%; }
}
</style>
