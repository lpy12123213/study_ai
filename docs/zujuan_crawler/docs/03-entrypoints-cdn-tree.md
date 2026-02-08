# 3b. 入口：CDN 预生成分类树（`static.zxxk.com/zujuan/tree/*.json`）

更新时间：2026-02-08

组卷网前端在渲染“章节/知识点/解题方法”左侧树时，除了会调用：

- `GET https://zujuan.xkw.com/zujuan-api/category/child_node`

还会（在很多页面/场景下）直接从 CDN 拉取**预生成的整棵树 JSON**，形如：

- `https://static.zxxk.com/zujuan/tree/lk_11.json`（知识点）
- `https://static.zxxk.com/zujuan/tree/j_11.json`（解题方法）
- `https://static.zxxk.com/zujuan/tree/ct_11_135303.json`（章节：某教材版本）

它们的价值在于：
- 响应类型通常为 `application/json`，并常携带 `ETag` / `Last-Modified` / `Cache-Control` 等缓存相关头
- 单次请求返回整棵树，减少对 `child_node` 的递归请求次数
- 在部分网络环境下，CDN 静态资源与主站 HTML 的可用性可能不同步

边界说明：
- 这些 JSON 属于公开可访问静态资源（至少在 2026-02-08 的实测环境中可直接访问）
- URL 命名、文件存在性与权限不构成稳定协议；当 CDN 文件不存在或返回非 JSON 时，可改用 `child_node` 获取树结构

相关文档：
- `docs/api/base.md`：`/zujuan-api/base` 里能拿到 `cdn_domain`
- `docs/api/category-child-node.md`：递归拉树的标准方案（兜底）
- `docs/12-category-alignment.md`：把树 ID 和 `question/list` 参数对齐

---

## 3b.1 如何发现 CDN 域名（`cdn_domain`）

`GET https://zujuan.xkw.com/zujuan-api/base` 的返回体里，除了 `var edu=[...]`，末尾还包含一段站点配置字符串，其中常见：

```text
cdn_domain='https://static.zxxk.com'
```

要点：
- `cdn_domain` 属于站点配置项，出现在 `/zujuan-api/base` 返回体中，可通过字符串解析获得。
- `/zujuan-api/base` 对 `User-Agent` 较敏感；当 UA 异常时可能返回占位内容或非预期文本。相关特征与解析方式见 `docs/api/base.md` 与 `docs/02-session-cookies-headers.md`。

---

## 3b.2 CDN 分类树文件命名规则（已验证可用）

下面 URL 模式在 2026-02-08 实测可用（访客态可直接 GET）：

### 3b.2.1 知识点树（zsd）

```text
GET {cdn_domain}/zujuan/tree/lk_{bankId}.json
```

示例：
- `https://static.zxxk.com/zujuan/tree/lk_11.json`

典型响应头特征：
- `Content-Type: application/json`
- `ETag` / `Last-Modified` / `Cache-Control: max-age=604800`（常见 7 天）

### 3b.2.2 解题方法树（jtff）

```text
GET {cdn_domain}/zujuan/tree/j_{bankId}.json
```

示例：
- `https://static.zxxk.com/zujuan/tree/j_11.json`

存在性提醒（很重要）：
- `j_{bankId}.json` **不是每个学科库都有**。在 2026-02-08 的抽样里：
  - 初中/高中理科（如数学/物理/化学）通常存在（200）
  - 语文/英语/小学学科等可能直接 404（说明该学科没有“方法维度库”或站点未提供）
- 当返回 404 时，可将该维度视为“无静态树文件可用”；是否存在 type=2 的数据需以 `child_node` 或页面实际返回为准。

### 3b.2.3 章节树（zj）：按“教材版本/章节根”区分

```text
GET {cdn_domain}/zujuan/tree/ct_{bankId}_{textbookVersionId}.json
```

示例（高中数学）：
- 章节根（常见来自 URL）：`https://zujuan.xkw.com/gzsx/zj135303/` → `textbookVersionId=135303`
- CDN 树：`https://static.zxxk.com/zujuan/tree/ct_11_135303.json`

`textbookVersionId` 的信息源（按可观察来源枚举）：
1) 分类页 URL：章节路由常形如 `.../zj135303/`，可直接解析数字部分作为 `textbookVersionId`
2) `question/list` 的题块/页面片段：在片段链接中解析 `zj(\\d+)`
3) `GET /zujuan-api/chaptertextbooks?textbookVersionId=...&url=...`（见 `docs/api/chaptertextbooks.md`）
4) `GET /zujuan-api/base` + `GET /zujuan-api/category/child_node` 组合：
   - `/zujuan-api/base` 中每个 bank 的 `CategoryList` 里，常见有“教材版本根”（例如高中数学的人教 A 版 `134949`）
   - 对该根节点调用：
     - `GET /zujuan-api/category/child_node?bankId=11&type=0&categoryId=134949&c2k=false`
   - 返回的子节点就是具体“册/分卷”（例如 `135303` 必修第一册、`135403` 必修第二册...），这些 id 才是 `ct_{bankId}_{textbookVersionId}.json` 里的 `textbookVersionId`

示例（高中数学 `bankId=11`，人教 A 版根 `134949`）：

```text
GET https://zujuan.xkw.com/zujuan-api/category/child_node?bankId=11&type=0&categoryId=134949&c2k=false

-> [
  {"id":135303,"name":"必修第一册",...},
  {"id":135403,"name":"必修第二册",...},
  {"id":135443,"name":"选择性必修第一册",...},
  ...
]
```

然后对应的 CDN 树通常存在：

```text
https://static.zxxk.com/zujuan/tree/ct_11_135303.json
https://static.zxxk.com/zujuan/tree/ct_11_135403.json
...
```

提醒：
- `ct_{bankId}_{textbookVersionId}.json` 的 `textbookVersionId` **不是** “教材版本根”（例如 `134949`），对根直接拼 `ct_11_134949.json` 在实测中会 404。

### 3b.2.4 其它树（观测到但与主流程关系不大）

```text
GET {cdn_domain}/zujuan/tree/l_{bankId}.json
```

示例：
- `https://static.zxxk.com/zujuan/tree/l_11.json`

该文件在前端代码里对应 `good_lesson_bk`（用途随站点调整，和“章节/知识点/解题方法抓题”主链路无强绑定）。

---

## 3b.3 JSON 结构：节点字段与含义

以 `lk_11.json`（知识点树）为例，其根对象与子节点通常都是同一种结构：

```json
{
  "bankId": 11,
  "id": "27925",
  "title": "高中数学知识点",
  "href": "/gzsx/zsd27925",
  "parentId": "0",
  "open": false,
  "children": [
    {
      "id": "27926",
      "title": "集合与常用逻辑用语",
      "href": "/gzsx/zsd27926",
      "parentId": "27925",
      "children": [ "... 省略 ..." ]
    }
  ]
}
```

常用字段解释（以实际返回为准）：
- `id`：节点 ID（字符串/数字都可能出现），**你后续作为 `categoryId` 使用**
- `title`：节点名称
- `href`：前端路由（相对路径）
- `children`：子节点数组；空数组可视为叶子节点
- `parentId`：父节点 ID（字符串居多）
- `bankId`：bankId

注意：
- `j_{bankId}.json`（解题方法树）字段集可能少一些（例如没有 `children` 以外的扩展字段），但核心仍是 `id/title/href/children`
- `ct_{bankId}_{textbookVersionId}.json`（章节树）与知识点树结构很相似

---

## 3b.4 如何把 CDN 树对接到 `question/list`（抓题）

核心映射关系：

| 树类型 | CDN 文件 | `question/list` pageName | categoryId 来源 | Referer 示例（由 href 构造） |
|---|---|---|---|---|
| 章节（zj） | `ct_{bankId}_{textbookVersionId}.json` | `zhangjie`（或 `zj`） | 节点 `id` | `https://zujuan.xkw.com{href}/`（`/gzsx/zj135305`） |
| 知识点（zsd） | `lk_{bankId}.json` | `zsd` | 节点 `id` | `https://zujuan.xkw.com{href}/`（`/gzsx/zsd27926`） |
| 解题方法（jtff） | `j_{bankId}.json` | `jtff` | 节点 `id` | `https://zujuan.xkw.com{href}/`（`/gzsx/jtff149446`） |

补充说明（可观察行为）：
- 前端在调用列表接口时，`Referer` 通常与当前节点的 `href` 路由保持一致。
- 节点 `id` 在 JSON 中常以字符串表示；在 `question/list` 表单参数中可按字符串提交（服务端通常可解析为数值）。
- 章节树与知识点树的节点数量可能较大。

---

## 3b.5 Python：遍历 CDN 树并生成抓取分片

下面示例会：
- 下载一个 tree JSON
- 深度遍历所有节点
- 产出叶子节点列表（`children` 为空）

```python
import json
from collections import deque
from urllib.parse import urljoin
from urllib.request import Request, urlopen


BASE = "https://zujuan.xkw.com"


def fetch_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def iter_nodes(root: dict):
    q = deque([root])
    while q:
        node = q.popleft()
        yield node
        for ch in node.get("children") or []:
            q.append(ch)


def leaf_shards(root: dict):
    shards = []
    for n in iter_nodes(root):
        children = n.get("children") or []
        if not children:
            href = n.get("href") or ""
            shards.append(
                {
                    "categoryId": str(n.get("id")),
                    "title": n.get("title"),
                    "referer": urljoin(BASE, href + "/") if href else None,
                }
            )
    return shards


# Example:
# tree = fetch_json("https://static.zxxk.com/zujuan/tree/lk_11.json")
# shards = leaf_shards(tree)
# print("leaf shards:", len(shards), shards[:3])
```

产出的 `categoryId/referer` 可直接用于调用 `POST /zujuan-api/question/list`（参数见 `docs/api/question-list.md`）。

---

## 3b.6 响应头与条件请求（观测）

这些 CDN JSON 响应通常包含以下缓存相关响应头：
- `ETag`
- `Last-Modified`
- `Cache-Control`（常见为较长的 `max-age`）

当客户端携带 `If-None-Match` / `If-Modified-Since` 发起条件请求时，服务端可能返回 `304 Not Modified`。

---

## 3b.7 一致性抽检结果：CDN tree vs `child_node`（样例）

本仓库在 2026-02-08 对 `bankId=11` 做了结构一致性抽检：对比 CDN tree 的 root `children` 数量与 `child_node` 同 root 的子节点数量。

以高中数学（`bankId=11`）为例，2026-02-08 实测：

| 树类型 | CDN root | CDN children 数 | `child_node` children 数 |
|---|---:|---:|---:|
| 知识点（lk） | `27925` | 18 | 18 |
| 解题方法（j） | `148414` | 14 | 14 |
| 章节（ct，必修一） | `135303` | 6 | 6 |

提醒：
- 上述结果仅覆盖 root 层级的子节点数量对比，不构成对所有层级或未来版本的一致性保证。

---

## 3b.8 不可用情形与替代入口

已观察到的不可用情形包括：
- 文件返回 `404`：该 `bankId` 或该 `textbookVersionId` 对应的静态树文件在该时点不存在（可能为未提供、已下线或命名变更）。
- 响应为非 JSON（例如 HTML）：该请求未获得目标静态资源。

替代公开入口：
- `GET /zujuan-api/category/child_node`（见 `docs/api/category-child-node.md`）
