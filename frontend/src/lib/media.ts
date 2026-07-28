/**
 * 媒体 URL 工具。
 * - 第三方题目图片一律经 /api/media/proxy?url= 加载（SSRF 白名单 + 缓存）。
 * - 生成文件走 /api/media/generated/{filename}。
 */
export function proxyImageUrl(url?: string | null): string {
  if (!url) return "";
  let u = url.trim();
  if (!u) return "";
  if (u.startsWith("/api/")) return u;
  if (u.startsWith("//")) u = `https:${u}`;
  if (/^https?:\/\//i.test(u)) {
    return `/api/media/proxy?url=${encodeURIComponent(u)}`;
  }
  return u;
}

/** 题干 HTML（后端已消毒）中的 <img> src 改写为媒体代理地址。 */
export function rewriteStemHtml(html?: string | null): string {
  if (!html) return "";
  try {
    const doc = new DOMParser().parseFromString(html, "text/html");
    doc.querySelectorAll("img").forEach((img) => {
      const src = img.getAttribute("src");
      if (src) img.setAttribute("src", proxyImageUrl(src));
      img.setAttribute("loading", "lazy");
      img.setAttribute("referrerpolicy", "no-referrer");
    });
    return doc.body.innerHTML;
  } catch {
    return html;
  }
}

export function generatedFileUrl(filename?: string | null): string {
  if (!filename) return "";
  if (filename.startsWith("/api/")) return filename;
  return `/api/media/generated/${filename}`;
}
