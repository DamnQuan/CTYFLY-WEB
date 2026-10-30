<script setup>
/**
 * 关于我们 —— 垂天云飞友集团介绍页，公开访问
 * 文案由集团官方提供，页面只做排版，不改动原文表述。
 */
import logoMark from '../assets/logo-mark.png';
import Icon from '../components/Icon.vue';
</script>

<template>
  <div class="page about-page">
    <div class="page-header" style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px">
      <div class="about-head">
        <img class="about-logo" :src="logoMark" alt="" width="44" height="44" />
        <div>
          <div class="page-title">关于我们</div>
          <div class="page-desc">垂天云飞友集团 · CTYFLY 官方网站</div>
        </div>
      </div>
      <router-link class="btn btn-ghost btn-sm" to="/">
        <Icon name="chevron" :size="14" style="transform: rotate(90deg)" /> 返回首页
      </router-link>
    </div>

    <div class="glass card about-card">
      <div class="about-slogan">随云启航，快乐飞翔</div>

      <h2>名称由来与理念</h2>
      <p>
        垂天云飞友集团，名称取自《庄子·逍遥游》<strong>「其翼若垂天之云」</strong>，
        是一个以模拟飞行与虚拟航空为核心的线上社群组织。
        我们秉持<strong>「随云启航，快乐飞翔」</strong>的理念，
        致力于为飞行爱好者提供有序、友好、专业的交流与活动平台。
      </p>

      <h2>发展历程与组织架构</h2>
      <p>
        我们从最初的小规模社群起步，历经多轮调整与发展，逐步建立起完善的组织架构与管理制度，
        现拥有稳定的成员群体与良好的日常活跃度。
      </p>
      <p>
        我们设有行政部，下分多个组别，统筹日常运营、活动组织、内容审核与对外联络，
        并制定发布了《垂天云飞友集团行为准则》，对成员行为、活动参与及违规处理等事项作出明确规定，
        保障社群运行的规范性与连续性。
      </p>

      <h2>社群体系与合作生态</h2>
      <p>
        我们共有 <strong>CTY、CTY-O、CTY-X</strong> 三个社群，形成定位清晰、职能互补的业务体系。
      </p>
      <p>
        在对外合作方面，我们与多家虚拟航空及相关平台保持合作。
        我们的官方网站已完成整体重构，除承担自身信息发布与成员服务功能外，
        亦面向圈内其他虚拟航空提供<strong>免费的航司板块服务</strong>，
        致力于为虚拟航空生态提供稳定、有序的公共交流空间。
      </p>

      <h2>技术与治理</h2>
      <p>
        我们坚持技术自研与规则治理并重，在保持社群活跃与温度的同时，持续完善管理制度与服务体系。
        我们以<strong>真实、温暖、长期运营</strong>为原则，不追求短期扩张，而注重成员体验与社群秩序，
        力求在虚拟航空领域建立可持续、可信赖的社群。
      </p>

      <h2>社群文化</h2>
      <p>
        在社群文化上，我们鼓励成员在遵守规则的前提下自由交流、分享生活。
        我们同样重视成员的参与感与归属感，通过连飞活动、内部互动及日常交流，
        让各位都能找到属于自己的位置。
      </p>

      <h2>面向未来</h2>
      <p>
        面向未来，我们将持续优化平台功能与管理制度，深化与圈内伙伴的合作关系，推动虚拟航空生态的良性发展。
        我们希望垂天云不仅是一个社群的名字，更是一种可以长期信任、值得停留的网络归属。
      </p>
    </div>

    <div class="glass card about-card about-outro">
      <p class="about-wish">祝大家在 CTY 能有一个愉快的飞行体验！</p>
      <p class="about-feedback">
        反馈邮箱：<a class="text-link" href="mailto:support@ccflysim.cn">support@ccflysim.cn</a>
      </p>
      <p class="about-source">
        品牌图来源：<a
          class="text-link"
          href="https://www.bilibili.com/video/BV1BUt26PEno?t=1.7"
          target="_blank" rel="noopener noreferrer"
        >哔哩哔哩视频</a>，版权归原作者所有，仅用于本站品牌展示。
      </p>
    </div>
  </div>
</template>

<style scoped>
.about-page { max-width: 860px; padding-top: 20px; }
.about-head { display: flex; align-items: center; gap: 14px; }
.about-logo {
  border-radius: 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  padding: 4px;
}
.about-card { padding: 32px 34px; }
.about-card h2 {
  font-size: 17px;
  font-weight: 600;
  margin: 26px 0 10px;
  color: var(--text);
}
.about-card h2:first-of-type { margin-top: 4px; }
.about-card p {
  color: var(--text-2);
  font-size: 14px;
  line-height: 1.95;
  margin: 0 0 10px;
}
.about-card strong { color: var(--text); }
.about-slogan {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 4px;
  color: var(--blue);
  margin-bottom: 22px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
.about-outro { margin-top: 16px; text-align: center; }
.about-outro p { margin: 0 0 8px; }
.about-wish { font-size: 15px; font-weight: 600; color: var(--text); }
.about-feedback { font-size: 13.5px; }
/* 图片来源标注：比正文再弱一档，不与反馈邮箱抢注意力 */
.about-source { font-size: 12.5px; color: var(--gray); }
.about-links { font-size: 13.5px; margin-bottom: 0 !important; }
.about-links-sep { color: var(--gray); margin: 0 8px; }
</style>
