# 3. 入口：sitemap（XML）

本章记录 sitemap 入口的 URL 形式、返回结构与已观察到的大小写差异。

## 3.1 sitemap index（索引）

- URL：`https://zujuan.xkw.com/sitemap.xml`
- 响应类型：XML（正常情况下）
- 结构：`<sitemapindex>`，包含多个 `<sitemap><loc>...</loc></sitemap>`

风控相关说明：
- 在部分时段/访问模式下，`/sitemap.xml` 可能返回 `text/html` 的挑战页而非 XML。
- 该场景属于响应类型变化，并非 XML 解析错误。
- 本文档范围不包含挑战页绕过/对抗实现。

替代信息源（同为公开入口）：
- `POST /zujuan-api/paper/list`（见 `docs/api/paper-list.md`）
- 通过浏览器直接下载 sitemap 文件（人工操作）

返回示例（截断，仅示意结构）：

```xml
<sitemapindex>
  <sitemap>
    <loc>https://zujuan.xkw.com/Sitemap/p1.xml</loc>
    <lastmod>2022/12/29</lastmod>
  </sitemap>
  ...
</sitemapindex>
```

已观察到的大小写差异：
- index 中返回的 `<loc>` 常见形如：`https://zujuan.xkw.com/Sitemap/p1.xml`
- 实际可用路径常见为小写：`https://zujuan.xkw.com/sitemap/p1.xml`

当 `Sitemap` 大写路径返回非预期响应时，可在抓取侧将路径统一转换为 `/sitemap/` 再请求。

## 3.2 paper sitemap（可用）

- `https://zujuan.xkw.com/sitemap/p1.xml`（p2、p3... 类似）
- 内容是 `<urlset>`，每个 `<url><loc>https://zujuan.xkw.com/11p2296523.html</loc>...</url>`

用途：
- 批量获取 paper URL（通常覆盖面大，且不依赖复杂参数）

注意：
- 单个 `p*.xml` 文件可能较大（例如 MB 级）；示例采用流式解析（iterparse）。
- `<loc>` 中可能包含不同的 `{bankId}`（例如 `18p...`、`11p...`、`2p...`），`bankId` 可直接从 URL 模式中解析。

Python（lxml）流式解析示例：

```python
from lxml import etree
import requests

def iter_sitemap_locs(url: str):
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        # 防止拿到 JS 挑战页：先检查 Content-Type / 片段特征
        ct = (r.headers.get("Content-Type") or "").lower()
        if "xml" not in ct and "text/xml" not in ct:
            raise ValueError(f"unexpected content-type for sitemap: {ct}")
        # 直接对响应体做 iterparse
        context = etree.iterparse(r.raw, events=("end",), tag="{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
        for _, elem in context:
            if elem.text:
                yield elem.text.strip()
            elem.clear()
```

## 3.3 question sitemap（可能不可用）

index 中常见也会列出 `q1.xml`、`q2.xml` 等，但实际访问可能 404（以实时为准）。

当 question sitemap 返回 `404` 时，该入口在该时点不可用；paper sitemap 与 `paper/list` 可用于提供试卷入口集合。
