/**
 * 表单校验反馈，登录/注册共用，见交接文档 §26
 *
 * 出错时：输入框水平轻晃 + 边框变红 + 提示文字从下方滑入；
 * 用户一改这个字段就自动收起，修正即消失。
 *
 * 用法：
 *   const fb = useFieldFeedback ['account', 'password'] ;
 *   fb.fail 'account', '请填写账号' ; // 触发红边 + 轻晃 + 提示
 *   fb.input 'account' ; // 输入时调用：有错就收起
 *   fb.errors.account // 模板里绑 "is-error" 与提示文字
 *   fb.shaking.account // 模板里绑 "is-shake"，@animationend 清零
 */
import { reactive } from 'vue';

export function useFieldFeedback(fields) {
  const errors = reactive({});
  const shaking = reactive({});
  for (const f of fields) {
    errors[f] = '';
    shaking[f] = false;
  }

  /** 标记某字段出错：先清掉抖动态，下一帧再打开，保证重复提交也能重新播放动画 */
  function fail(field, message) {
    errors[field] = message;
    shaking[field] = false;
    requestAnimationFrame(() => { shaking[field] = true; });
  }

  function clear(field) {
    errors[field] = '';
    shaking[field] = false;
  }

  function clearAll() {
    for (const f of fields) clear(f);
  }

  /** 用户在改这个字段了：把它的错误收起来，动画由 CSS transition 负责*/
  function input(field) {
    if (errors[field]) clear(field);
  }

  /** 是否有任意字段出错，用于「首个错误」定位等*/
  function hasError() {
    return fields.some((f) => !!errors[f]);
  }

  return { errors, shaking, fail, clear, clearAll, input, hasError };
}
