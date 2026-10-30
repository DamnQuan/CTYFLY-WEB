/**
 * 图片上传前的客户端压缩，Canvas 重编码
 *
 * 为什么需要：手机拍的图动辄 3~8MB，原样上传会依次撞上「后端中间件上限 / nginx 上限」，
 * 用户只看到一句「请求体过大」，既不知道多大、也不知道怎么办。
 * 在 FormData 之前用 Canvas 把图压到 ≤2MB，既省流量也避免这些 413。
 *
 * 策略，先保清晰度，再保体积：
 *   1. 长边超过 maxDim，默认 2560 先等比缩图；
 *   2. 用 JPEG 质量 0.86 起编，超限就逐档降到 0.55；
 *   3. 仍超限再逐次缩尺寸，每次 ×0.8，直到 ≤ maxBytes 或到 1280 下限；
 *   4. 压完反而更大，小图重编码常见→ 返回原文件，不做负优化。
 *
 * 注意：
 * - GIF 直接原样返回，重编码会丢动画；
 * - JPEG 无透明通道，绘制前先铺白底，避免 PNG 透明区压完变黑块；
 * - 解码走 `createImageBitmap`，现代浏览器带 EXIF 方向，失败回退 `<img>`。
 */
const DEFAULT_MAX_BYTES = 2 * 1024 * 1024;
const DEFAULT_MAX_DIM = 2560;

function loadViaImg(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('图片解析失败，请换一张图片'));
    };
    img.src = url;
  });
}

function loadSource(file) {
  if (typeof createImageBitmap === 'function') {
    return createImageBitmap(file).catch(() => loadViaImg(file));
  }
  return loadViaImg(file);
}

function encode(source, width, height, type, quality) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) return Promise.resolve(null);
  // 先铺白底：JPEG 不支持透明，透明 PNG 直接编会变成黑块
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, width, height);
  ctx.drawImage(source, 0, 0, width, height);
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

export const MAX_UPLOAD_IMAGE_BYTES = DEFAULT_MAX_BYTES;

/**
 * @param {File} file 用户选择的原始文件
 * @param {{maxBytes?: number, maxDim?: number, quality?: number}} options
 * @returns {Promise<{file: File, compressed: boolean, originalSize: number, size: number}>}
 */
export async function compressImage(file, options = {}) {
  const {
    maxBytes = DEFAULT_MAX_BYTES,
    maxDim = DEFAULT_MAX_DIM,
    quality = 0.86,
  } = options;

  const originalSize = file?.size || 0;
  if (!(file instanceof File) || !file.type.startsWith('image/') || file.type === 'image/gif') {
    return { file, compressed: false, originalSize, size: originalSize };
  }

  let source;
  try {
    source = await loadSource(file);
  } catch {
    return { file, compressed: false, originalSize, size: originalSize };
  }

  const sw = source.width || source.naturalWidth || 0;
  const sh = source.height || source.naturalHeight || 0;
  if (!sw || !sh) {
    if (typeof source.close === 'function') source.close();
    return { file, compressed: false, originalSize, size: originalSize };
  }

  const scale = Math.min(1, maxDim / Math.max(sw, sh));
  let width = Math.max(1, Math.round(sw * scale));
  let height = Math.max(1, Math.round(sh * scale));
  const type = 'image/jpeg';

  let q = quality;
  let blob = await encode(source, width, height, type, q);
  while (blob && blob.size > maxBytes && q > 0.55) {
    q = Math.max(0.5, Number((q - 0.08).toFixed(2)));
    blob = await encode(source, width, height, type, q);
  }
  while (blob && blob.size > maxBytes && Math.max(width, height) > 1280) {
    width = Math.max(1, Math.round(width * 0.8));
    height = Math.max(1, Math.round(height * 0.8));
    q = 0.8;
    blob = await encode(source, width, height, type, q);
  }
  if (typeof source.close === 'function') source.close();

  // 压不出来或反而更大 → 原图交回，不制造负优化
  if (!blob || blob.size >= originalSize) {
    return { file, compressed: false, originalSize, size: originalSize };
  }
  const baseName = (file.name || 'image').replace(/\.[^.]+$/, '') || 'image';
  const out = new File([blob], `${baseName}.jpg`, { type, lastModified: Date.now() });
  return { file: out, compressed: true, originalSize, size: out.size };
}
