<script setup>
/**
 * 隐私政策 —— 依据《垂天云飞友集团隐私政策》，CTY 行政部 2026.09 编写，
 * 并如实补充本网站特有的数据条目，账号、飞行报告、钱包、工单、第三方服务。
 *
 * 写作原则：每一条都能在代码里找到对应实现，不写空话：
 *   - 采集字段见 backend/app/database.py 的建表语句
 *   - 官网日志「30 天保留 + 服务器归档」见 backend/app/logretention.py，启动 + 每 24h 一次
 *   - 注销匿名化见 approvals 的 delete_account 分支
 *   - 验证码 10 分钟有效期见 backend/app/mailer.py 的 CODE_TTL_MS
 *   - 小鲸灵对话仅内存 6 轮见 backend/app/routers/pet.py
 */
import Icon from '../components/Icon.vue';

const collected = [
  {
    kind: '成员与账号基础信息',
    detail: 'QQ 群：昵称、QQ 号、呼号、申请理由，昵称与 QQ 号由腾讯 QQ 平台提供并受其规则约束。官网：CID、用户名、邮箱、密码哈希、QQ 号，选填项',
    purpose: '成员识别、账号登录、找回密码、系统通知',
    keep: '成员 / 账号存续期间；退出社群或注销账号后 30 日内删除或匿名化',
    source: '你主动提供',
  },
  {
    kind: '活动与服务数据',
    detail: '连飞活动与技术培训中提交的飞行数据、飞行报告、截图、文字说明、活动报名、航司与钱包流水',
    purpose: '活动组织、数据统计、结果发布、社区与商城功能',
    keep: '集团活动材料自活动结束起不超过 30 日；官网的飞行报告与钱包流水随账号存续，注销时立即匿名化',
    source: '你主动提供',
  },
  {
    kind: '安全与秩序记录',
    detail: '群内发言与互动记录，在 QQ 群侧；官网的登录 / 注册 / 审计 / 接口访问日志：IP 地址、粗略归属地、User-Agent、设备指纹不可逆摘要',
    purpose: '维护社群秩序、异常登录识别、防暴力破解与恶意注册、违规处理与申诉、安全事件溯源与取证',
    keep: '官网管理后台仅保留并可查阅最近 **30 天**；过期前自动压缩归档保存在服务器，不在后台展示，仅用于安全事件溯源；涉及未处理申诉的保存至处理完毕',
    source: '访问与使用时自动记录',
  },
  {
    kind: '公网 IPv6 地址，由浏览器探测',
    detail: '登录后浏览器会在本机发起一次 STUN 查询，通过 Cloudflare 服务，以获知你网络侧的公网 IPv6 地址并回传本站；不含账号、邮箱等任何内容',
    purpose: '本站当前仅提供 IPv4 接入，此项用于为安全事件溯源补充一条网络地址线索',
    keep: '保存为账号的「最近一次探测到的 IPv6」，随账号存续；注销时随账号匿名化',
    source: '浏览器自动探测并回传，仅在你网络本身具备公网 IPv6 时才有结果',
  },
  {
    kind: '邮件验证码',
    detail: '邮箱地址、6 位数字验证码',
    purpose: '注册与找回密码时的身份校验',
    keep: '10 分钟内有效，使用后立即删除',
    source: '你主动触发',
  },
  {
    kind: '机器人交互记录',
    detail: '你向官方机器人或桌面小鲸灵发送的指令、查询请求与对话内容',
    purpose: '功能响应与优化',
    keep: '小鲸灵对话仅保存在服务器内存中，保留最近 6 轮，重启即清空，不写入数据库；QQ 群机器人交互记录不超过 30 日',
    source: '你主动输入',
  },
  {
    kind: '接口访问统计',
    detail: '仅「日期 + 请求方法 + 路径 + 状态码」的聚合计数',
    purpose: '容量规划与稳定性分析',
    keep: '聚合数据，不含任何个人标识',
    source: '自动统计，不关联到人',
  },
];

const thirds = [
  {
    name: 'ip-api.com',
    what: '由本站服务器用你的 IP 查询粗略归属地，用于登录日志与异常识别。只发送 IP 本身，不发送账号、邮箱等任何信息，结果在服务端缓存 24 小时。',
  },
  {
    name: '腾讯 QQ 头像服务，域名 q1.qlogo.cn',
    what: '当你在资料中填写 QQ 号时，浏览器会直接从该地址加载你的 QQ 头像图片，此时腾讯会获得你的 IP 与来源页面。不填 QQ 号则完全不涉及。',
  },
  {
    name: '腾讯企业邮箱，域名 smtp.exmail.qq.com',
    what: '由本站服务器发送验证码邮件，你的邮箱地址会提供给邮件服务商用于投递。',
  },
  {
    name: 'aviationweather.gov / NOAA / VATSIM',
    what: '航情查询，包括 METAR 与 TAF，由本站服务器向这些数据源发起请求，只携带你查询的机场代码，不携带你的任何个人信息。',
  },
  {
    name: '火山方舟，火山引擎 / 豆包大模型',
    what: '仅当你使用桌面小鲸灵的 AI 对话时涉及：你的提问内容、用户名与飞行员等级会发送到火山方舟用于生成回复。我们已在请求中关闭服务商侧的对话存储，请求参数 store=false，对话也不会被我们写入数据库。不使用 AI 对话则完全不涉及。',
  },
  {
    name: 'Cloudflare STUN 服务 stun.cloudflare.com',
    what: '登录后由浏览器发起一次 STUN 查询，用于探测你网络侧的公网 IPv6 地址。查询由浏览器直接发往 Cloudflare，因此 Cloudflare 会看到你的公网 IP；本站只接收探测到的 IPv6 地址，不发送账号、邮箱等任何信息。该探测不影响页面功能，失败时静默跳过。',
  },
  {
    name: '阿里云云解析 DNS',
    what: '仅用于为本站域名自动签发与续期 HTTPS 证书，不涉及任何用户数据。',
  },
];
</script>

<template>
  <div class="policy-shell">
  <div class="page legal-page">
    <div class="page-header" style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px">
      <div>
        <div class="page-title">隐私政策</div>
        <div class="page-desc">垂天云飞友集团 · 生效日期：2026 年 9 月 18 日 · 更新日期：2026 年 10 月 18 日</div>
      </div>
      <router-link class="btn btn-ghost btn-sm" to="/">
        <Icon name="chevron" :size="14" style="transform: rotate(90deg)" /> 返回首页
      </router-link>
    </div>

    <div class="glass card legal-card">
      <h2>引言</h2>
      <p>
        垂天云飞友集团，以下简称为「我们」，深知个人信息对您的重要性，也会尽全力守护您的个人信息安全。
        我们希望通过本政策，把收集、使用、保护您个人信息的方式讲清楚，也便于您了解并行使相关权利。
        为此，我们遵循以下原则：<strong>权责一致、目的明确、选择同意、最少够用、确保安全、主体参与、公开透明</strong>。
      </p>
      <p>
        本政策适用于我们运营的所有平台与服务，包括但不限于
        QQ 群如 CTY、CTY-X、CTY-O 等，官方网站 CTYFLY，以及其他相关线上服务。
        浏览器本地存储也就是 localStorage 的使用规则见
        <router-link class="text-link" to="/cookies">《Cookie 政策》</router-link>。
      </p>
      <p class="legal-note">
        我们在设计上尽量减少对个人信息的采集：<strong>不要求你提供真实姓名</strong>——申请表中的该项已改为「称呼」，
        填呼号或昵称即可；设备指纹只保存<strong>不可逆摘要</strong>；接口访问日志只做聚合计数，不落到个人。
      </p>

      <h2>一、我们如何收集和使用你的个人信息</h2>
      <p>
        个人信息，是指以电子或者其他方式记录的、能够单独或者与其他信息结合识别特定自然人身份，
        或者反映特定自然人活动情况的各种信息。我们仅会出于本政策所述目的，收集和使用你的个人信息：
      </p>

      <h3>1.1 帮助你成为我们的成员</h3>
      <p>
        加入 QQ 社群需要提供昵称、QQ 号、呼号、申请理由等信息——其中昵称、QQ 号由腾讯 QQ 平台提供并受其规则约束；
        官网注册需要提供 CID、用户名、邮箱并设置密码。如果你仅浏览公开页面，则无需提供上述信息。
      </p>

      <h3>1.2 为你提供活动与服务</h3>
      <p>
        参与连飞活动、技术培训等集体活动时，我们可能收集你提交的飞行数据、截图、文字说明，
        以及你在官网提交的飞行报告、活动报名、航司信息与钱包流水，用于活动组织、数据统计、结果发布与功能运转。
      </p>

      <h3>1.3 保障服务安全与秩序</h3>
      <p>
        为维护社群秩序，并依据《垂天云飞友集团行为准则》处理违规行为，我们可能收集并保存群内发言记录、互动内容、
        文件分享记录，以及官网的登录 / 注册 / 审计日志，包括 IP 地址、粗略归属地、User-Agent、设备指纹摘要。
      </p>

      <h3>1.4 改进我们的服务</h3>
      <p>
        我们可能收集官网访问时的日志数据，以及你向机器人发送的指令与交互记录，用于分析使用情况、优化功能设计。
      </p>

      <h3>1.5 信息保存期限</h3>
      <p>
        我们仅在实现本政策所述目的所必需的期限内保存你的个人信息：除成员 / 账号基础信息外，
        官网各类日志，包括登录 / 注册 / 审计 / 接口访问，在管理后台<strong>仅保留并可查阅最近 30 天</strong>；
        更早的记录会在删除前自动压缩归档保存在服务器上，用于安全事件溯源，不再在后台展示：
      </p>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr><th>类别</th><th>具体内容</th><th>保存期限</th></tr>
          </thead>
          <tbody>
            <tr v-for="c in collected" :key="c.kind">
              <td><strong>{{ c.kind }}</strong><div class="legal-src">{{ c.source }}</div></td>
              <td>{{ c.detail }}</td>
              <td>{{ c.keep }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="legal-note">
        保存期限届满后，我们会对相关个人信息进行删除或匿名化处理；
        法律法规另有规定或你另行授权的除外。官网的到期日志由系统<strong>每日自动清理</strong>，无需人工介入。
      </p>

      <h2>二、我们如何使用 Cookie 和同类技术</h2>
      <p>
        为确保网站正常运转，并为你提供更轻松的访问体验，我们会在你的计算机或移动设备上存储名为 Cookie 的小数据文件。
        我们不会将 Cookie 用于本政策所述目的之外的任何用途，你可以根据自己的偏好管理或删除 Cookie。
      </p>

      <h2>三、我们如何共享、转让、公开披露你的个人信息</h2>
      <h3>3.1 共享</h3>
      <p>
        我们不会与任何第三方公司、组织和个人共享你的个人信息，但以下情况除外：
        获得你的明确同意；根据法律法规规定或政府主管部门的强制性要求；
        与合作方开展联合活动时提前告知并征得你的同意。
        此外，下列<strong>实现功能所必需</strong>的服务提供方会在有限范围内处理你的信息：
      </p>
      <ul>
        <li v-for="t in thirds" :key="t.name"><strong>{{ t.name }}</strong>：{{ t.what }}</li>
      </ul>
      <h3>3.2 转让</h3>
      <p>
        我们不会将你的个人信息转让给任何公司、组织和个人，但以下情况除外：
        获得你的明确同意；如本集团发生合并、分立或运营主体变更，且涉及个人信息转让时，
        我们会要求新的持有方继续受本政策约束，否则将重新向你征求授权同意。
      </p>
      <h3>3.3 公开披露</h3>
      <p>
        仅在获得你的明确同意，或依据法律、法律程序、诉讼或政府主管部门强制性要求的情况下，
        我们才会公开披露你的个人信息。
      </p>

      <h2>四、我们如何保护你的个人信息</h2>
      <ul>
        <li><strong>存储位置</strong>：数据保存在中华人民共和国境内的自有服务器与数据库中，不托管给第三方云数据库；</li>
        <li><strong>密码</strong>：使用 bcrypt 加盐哈希，每条独立随机盐与迭代式密钥扩展，任何人包括管理员都无法还原你的明文密码；</li>
        <li><strong>传输</strong>：全站强制 HTTPS 加密传输；</li>
        <li><strong>会话</strong>：登录凭据使用带版本号的令牌，修改密码或注销会立即让此前所有会话失效；</li>
        <li><strong>防护</strong>：接口限流、请求体大小限制、越权访问拦截与审计日志；</li>
        <li><strong>备份</strong>：数据库、上传文件与日志归档每日自动备份，服务器本机保留最近 14 天，并每日同步至站长本地设备留存；</li>
        <li><strong>事件响应</strong>：发生个人信息安全事件后，我们将按法律法规要求及时告知基本情况、影响、处置措施与你的防范建议。</li>
      </ul>
      <p>互联网并非绝对安全的环境，我们建议你不要通过群聊、私信等未加密方式发送敏感个人信息。</p>

      <h2>五、你的权利</h2>
      <ul>
        <li>
          <strong>查询与更正</strong>：登录后可在
          <router-link class="text-link" to="/profile">个人中心</router-link>
          查看并修改你的用户名、邮箱、QQ 号与头像；申请记录、工单、飞行报告等也可在对应页面查看。
        </li>
        <li>
          <strong>删除与注销账号</strong>：可通过工单提出注销申请。为防止误操作与恶意注销，
          需经 <strong>2 名管理员复核</strong>后执行。执行后：
          <ul>
            <li>用户名、邮箱、QQ 号、头像、密码哈希会被立即清除并替换为不可识别的值，账号无法再登录；</li>
            <li>此前所有登录会话立即失效；</li>
            <li>为保证历史记录中工单、飞行报告、活动报名等的引用完整性，这些记录本身会保留，
                但已不再关联任何可识别你个人身份的信息。</li>
          </ul>
        </li>
        <li><strong>改变授权范围</strong>：每个业务功能需要一些基本的个人信息才能完成；
            对于额外收集的部分，你可以随时给予或收回授权，例如在 Cookie 提示中选择「仅必需」，
            或在个人中心收起桌面小鲸灵。</li>
        <li><strong>响应承诺</strong>：为保障安全，我们可能先要求你验证身份，再处理你的请求，
            并将在合理期限内作出答复。</li>
      </ul>

      <h2>六、我们如何处理未成年人的个人信息</h2>
      <p>
        我们非常重视对未成年人个人信息的保护。若你是未成年人，建议请你的监护人阅读本政策，
        并在征得监护人同意的前提下使用我们的服务或向我们提供信息。
        本站面向航空爱好者社区，内容不含不适宜未成年人的信息。
      </p>

      <h2>七、你的个人信息如何存储</h2>
      <p>
        我们在中华人民共和国境内运营中收集和产生的个人信息，存储在中国境内。
        以下情形除外：法律法规有明确规定；获得你的明确授权；你通过互联网进行跨境交流等个人主动行为。
        针对以上情形，我们会确保依据本政策对你的个人信息提供足够的保护。
      </p>

      <h2>八、本政策如何更新</h2>
      <p>
        我们的隐私政策可能变更。未经你明确同意，我们不会削减你按照本政策所应享有的权利。
        我们会在本页面发布对本政策所做的任何变更；对于重大变更，包括服务模式重大变化、
        共享 / 转让 / 公开披露的主要对象变化、你的权利及行使方式重大变化、
        责任部门与联络渠道变化等，我们还会提供更为显著的通知。继续使用本站即视为接受更新后的政策。
      </p>

      <h2>九、如何联系我们</h2>
      <p>
        如你对本隐私政策有任何疑问、意见或建议，或需要行使上述权利：
      </p>
      <ul>
        <li>通过集团行政部邮箱 <strong>support@ccflysim.cn</strong> 与我们联系；</li>
        <li>登录后在 <router-link class="text-link" to="/tickets">工单中心</router-link> 提交「账号问题」类工单；</li>
        <li>加入首页的 QQ 群联系管理团队。</li>
      </ul>
      <p>我们将在收到后尽快处理并回复。</p>

      <p style="margin-top: 26px; color: var(--gray); font-size: 13px">
        垂天云飞友集团 · CTY 行政部<br />2026.09
      </p>
    </div>
  </div>
  </div>
</template>

<style scoped>
.legal-page { max-width: 860px; padding-top: 20px; }
.legal-card { padding: 32px 34px; }
.legal-card h2 {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.2px;
  margin: 26px 0 10px;
}
.legal-card h2:first-child { margin-top: 0; }
.legal-card h3 {
  font-size: 14.5px;
  font-weight: 600;
  margin: 18px 0 8px;
  color: var(--text);
}
.legal-card p {
  color: var(--text-2);
  font-size: 14px;
  margin-bottom: 10px;
  line-height: 1.75;
}
.legal-card strong { color: var(--text); }
.legal-card ul {
  padding-left: 20px;
  color: var(--text-2);
  font-size: 14px;
  line-height: 1.9;
  margin-bottom: 10px;
}
.legal-card ul ul { margin-top: 6px; margin-bottom: 6px; }
.legal-card li strong { color: var(--text); }
.legal-card td { vertical-align: top; font-size: 13.5px; }
.legal-src {
  margin-top: 3px;
  font-size: 12px;
  color: var(--gray);
}
.legal-note {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--surface);
  font-size: 13px;
}
</style>
