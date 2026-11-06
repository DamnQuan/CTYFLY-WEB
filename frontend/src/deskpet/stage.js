/**
 * 桌宠播放器：双视频槽交叉淡入
 *
 * 素材是 10 秒一段的 VP9-alpha WebM。切换动画时不能直接改同一个 <video> 的 src
 * 会闪一下黑/空，所以用两块视频轮换：旧的在前面继续显示，新的在背面加载完
 * 再淡入、旧的淡出，视觉上是无缝的。这是上游 dsh-pet 的做法，这里按网页场景简化：
 *   - 加载走 **fetch + blob**：上游实测 <video> 流式加载在部分网络/服务器组合下会
 *     stall，请求挂起、不报错、永不 loadeddata → 宠物凭空隐形，整文件拿下来再喂
 *     给 video 才可靠。
 *   - 只保留「切换代次 token」防止旧加载覆盖新动画 / 预热被连点取代误判失败。
 *
 * 用法：
 *   const stage = createStage { slots: [a, b], onEnded, onError } ;
 *   stage.play 'idle-breathe' ; // 切到某段，自动加载
 *   stage.preload 'act-hum' ; // 背面预热，播完切过去不卡
 *   stage.pause ; / stage.resume ; // 标签页隐藏时省电
 */
import { webmUrl } from './catalog.js';

const LOAD_TIMEOUT_MS = 8000;

export function createStage({ slots, onEnded, onError, onFront }) {
  let front = 0;
  let current = '';
  let token = 0;
  let disposed = false;
  let paused = false;
  /** 每槽已加载的 slug，避免重复 src 赋值导致重播*/
  const loaded = ['', ''];
  /** 每槽当前的 blob URL，换新前 revoke，防内存泄漏*/
  const blobUrls = ['', ''];
  /** 背面预热记录：{ slug, slot } */
  let warm = null;
  /** 每槽的加载代次：同槽后发的 src 会掐断先前加载的 loadeddata，
   *  旧 promise 必须以「被取代」结束，而不是当成失败，否则一次快速连点就会误降级静态图*/
  const loadGen = [0, 0];

  const applyFacing = (el, facing) => {
    if (el) el.style.transform = facing === 'right' ? 'scaleX(-1)' : '';
  };

  const superseded = () => Object.assign(new Error('动画加载被新的切换取代'), { superseded: true });

  const load = (slotIndex, slug) => {
    const el = slots[slotIndex];
    if (!el) return Promise.reject(new Error('slot missing'));
    if (loaded[slotIndex] === slug && el.readyState >= 2) return Promise.resolve(el);
    const my = ++loadGen[slotIndex];
    return new Promise((resolve, reject) => {
      let done = false;
      const ac = new AbortController();
      const finish = (fn, arg) => {
        if (done) return;
        done = true;
        el.removeEventListener('loadeddata', onReady);
        el.removeEventListener('error', onErr);
        clearTimeout(timer);
        try { ac.abort(); } catch { /* 已完成的 fetch abort 是无害 no-op */ }
        fn(arg);
      };
      const onReady = () => {
        if (loadGen[slotIndex] !== my) {
          finish(reject, superseded());
          return;
        }
        loaded[slotIndex] = slug;
        finish(resolve, el);
      };
      const onErr = () => finish(reject, loadGen[slotIndex] !== my ? superseded() : new Error(`动画加载失败 ${slug}`));
      const timer = setTimeout(() => finish(reject, loadGen[slotIndex] !== my ? superseded() : new Error(`动画加载超时 ${slug}`)), LOAD_TIMEOUT_MS);
      el.addEventListener('loadeddata', onReady);
      el.addEventListener('error', onErr);
      // 整文件 fetch，HTTP 缓存照常生效→ blob → 再交给 video；超时由上面的 timer 兜底
      fetch(webmUrl(slug), { cache: 'default', signal: ac.signal })
        .then((r) => {
          if (!r.ok) throw new Error(`动画 HTTP ${r.status} ${slug}`);
          return r.blob();
        })
        .then((blob) => {
          if (loadGen[slotIndex] !== my) {
            finish(reject, superseded());
            return;
          }
          if (blobUrls[slotIndex]) URL.revokeObjectURL(blobUrls[slotIndex]);
          const obj = URL.createObjectURL(blob);
          blobUrls[slotIndex] = obj;
          el.src = obj;
          el.load();
        })
        .catch((err) => {
          if (loadGen[slotIndex] !== my) finish(reject, superseded());
          else finish(reject, err instanceof Error ? err : new Error(`动画请求失败 ${slug}`));
        });
    });
  };

  /**
   * 切到某段动画。
   * @param {string} slug
   * @param {{ facing?: 'left'|'right', restart?: boolean }} opts
   * @returns {Promise<HTMLVideoElement|null>}
   */
  async function play(slug, opts = {}) {
    if (!slug || disposed) return null;
    const facing = opts.facing || 'left';
    let el = slots[front];
    if (current === slug && !opts.restart) {
      applyFacing(el, facing);
      if (paused) return el;
      el.play().catch(() => {});
      return el;
    }
    const my = ++token;
    const targetIndex = 1 - front;
    const target = slots[targetIndex];
    if (!target) return null;
    // 复用预热好的槽：同一段已经加载在背面，直接切，几乎零延迟
    if (!(warm && warm.slot === targetIndex && warm.slug === slug)) warm = null;
    try {
      await load(targetIndex, slug);
    } catch (err) {
      // 被更新的切换取代 = 正常竞态，静默让位；真失败才上报，组件据此降级静态图
      if (my === token && !disposed && !(err && err.superseded)) onError && onError(err, slug);
      return null;
    }
    if (my !== token || disposed) return null;
    el = target;
    target.onended = () => {
      if (my === token && !disposed) onEnded && onEnded(slug);
    };
    // 旧的前台视频立刻降级：掐掉它的 ended，避免残留事件把动画链带跑
    const old = slots[front];
    if (old && old !== target) {
      old.onended = null;
      // 只暂停不换 src：下次切回同一段还命中 readyState，省一次解码
      old.pause();
    }
    applyFacing(target, facing);
    front = targetIndex;
    current = slug;
    warm = null;
    // 前台切换交给调用方渲染层，is-front 类由 Vue 响应式绑定，避免和补丁打架
    if (onFront && !disposed) onFront(front);
    if (!paused) target.play().catch(() => {});
    // 解码看门狗：blob 已就绪但 12s 后 still 无帧，decode stall→ 当失败上报，
    // 组件降级静态立绘。宁可降级也绝不留一只「隐形宠物」。
    setTimeout(() => {
      if (my !== token || disposed) return;
      if (target.readyState < 2) onError && onError(new Error(`动画解码停滞 ${slug}`), slug);
    }, 12000);
    return target;
  }

  /** 背面预热下一段，不切换。同一段正在前台时不重复加载*/
  function preload(slug) {
    if (!slug || disposed || slug === current) return;
    if (warm && warm.slug === slug) return;
    const targetIndex = 1 - front;
    if (loaded[targetIndex] === slug) {
      warm = { slug, slot: targetIndex };
      return;
    }
    load(targetIndex, slug)
      .then(() => {
        if (!disposed) warm = { slug, slot: targetIndex };
      })
      .catch(() => { /* 预热失败无所谓，真正要播的时候还会再试一次 */ });
  }

  function pause() {
    paused = true;
    slots.forEach((el) => el && el.pause());
  }

  function resume() {
    paused = false;
    const el = slots[front];
    if (el && current) el.play().catch(() => {});
  }

  function dispose() {
    disposed = true;
    token++;
    warm = null;
    slots.forEach((el, i) => {
      if (!el) return;
      el.onended = null;
      el.pause();
      el.removeAttribute('src');
      el.load();
    });
    blobUrls.forEach((u) => u && URL.revokeObjectURL(u));
    blobUrls[0] = '';
    blobUrls[1] = '';
  }

  return {
    play,
    preload,
    pause,
    resume,
    dispose,
    applyFacing: (facing) => applyFacing(slots[front], facing),
    front: () => slots[front],
    current: () => current,
    duration: () => {
      const el = slots[front];
      const d = el && el.duration;
      return Number.isFinite(d) && d > 0 ? d : 10;
    },
    time: () => (slots[front] ? slots[front].currentTime || 0 : 0),
  };
}
