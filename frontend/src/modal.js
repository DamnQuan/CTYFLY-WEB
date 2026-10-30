/** 全局弹窗系统：promise 风格的 confirm / prompt / alert */
import { reactive } from 'vue';

export const modalState = reactive({
  visible: false,
  title: '',
  message: '',
  danger: false,
  confirmText: '确定',
  cancelText: '取消',
  inputMode: false,      // prompt 模式：显示输入框
  inputPlaceholder: '',
  inputValue: '',
  alertValue: '',        // alert 模式：展示的值
  copyable: false,       // alert 值是否带复制按钮
  hideCancel: false,
  resolver: null,
});

export function showModal(options = {}) {
  return new Promise((resolve) => {
    // 旧弹窗还有 await 挂着时先按类型给默认值落地，confirm 类 false、prompt 类 null，
    // 避免被新弹窗覆盖后旧调用方永久 pending
    if (modalState.visible && modalState.resolver) {
      const oldResolver = modalState.resolver;
      modalState.resolver = null;
      oldResolver(modalState.inputMode ? null : false);
    }
    Object.assign(
      modalState,
      {
        title: '', message: '', danger: false, confirmText: '确定', cancelText: '取消',
        inputMode: false, inputPlaceholder: '', inputValue: '', alertValue: '',
        copyable: false, hideCancel: false,
      },
      options,
      { visible: true, resolver: resolve },
    );
  });
}

/** 返回 true，确定/ false，取消*/
export const confirmModal = (options = {}) => showModal(options).then((v) => v === true);

/** 返回输入字符串，确定/ null，取消*/
export const promptModal = (options = {}) => showModal({ inputMode: true, ...options });

/** 展示信息的 alert 弹窗 */
export const alertModal = (options = {}) => showModal({ hideCancel: true, ...options });

export function resolveModal(value) {
  if (!modalState.visible) return;
  const resolver = modalState.resolver;
  modalState.resolver = null;
  modalState.visible = false;
  resolver?.(value);
}

export function cancelModal() {
  resolveModal(modalState.inputMode ? null : false);
}

export function confirmModalValue() {
  resolveModal(modalState.inputMode ? modalState.inputValue : true);
}

export async function copyAlertValue() {
  try {
    await navigator.clipboard.writeText(modalState.alertValue);
    return true;
  } catch {
    return false;
  }
}
