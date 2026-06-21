/**
 * useLinkify — URL 自动识别为可点击链接
 *
 * 文本中 http/https URL → <a target="_blank"> 可点击链接。
 * 先 HTML 转义防 XSS，再正则替换。
 */

/** 匹配 http/https 链接 */
const URL_RE = /https?:\/\/[^\s<>"'`（）()「」【】[\]]+/g;

/**
 * 将文本中的 URL 转为可点击的 <a> 标签
 *
 * @param text - 原始文本
 * @returns 带 <a> 标签的 HTML 字符串，通过 v-html 渲染
 */
function linkify(text: string | undefined): string {
  if (!text) return '';
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  return escaped.replace(URL_RE, (url) => {
    const clean = url.replace(/[.,;:!?)]+$/, '');
    return `<a href="${clean}" target="_blank" rel="noopener noreferrer" class="text-accent underline decoration-dotted hover:decoration-solid">${clean}</a>`;
  });
}

/** URL 链接化 composable */
export function useLinkify() {
  return { linkify };
}
