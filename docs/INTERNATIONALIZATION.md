# 国际化约定

Study AI 目前采用轻量 i18n：应用外壳、路由、Header、命令面板、历史侧栏和标签弹窗优先走 locale key；深层业务页面仍以中文产品文案为主。

## 当前状态

截至 2026-05-24 的审计结果：

- `frontend/src/i18n/locales/zh-CN.json`：93 个 key。
- `frontend/src/i18n/locales/en-US.json`：93 个 key。
- 中英文 key 集合一致，当前无缺失 key。
- `frontend/src` 内 `t(...)` 调用约 69 处。
- `frontend/src` 内中文硬编码命中约 2355 行，主要集中在业务页面、表单、结果面板和错误提示。

这表示国际化覆盖重点是应用外壳，而不是全量业务页面。新增功能不要假设所有文案都已国际化。

## Namespace

Locale key 使用点分 namespace：

- `header.*`：顶栏按钮、菜单和无障碍标签。
- `layout.*`：布局级文案，例如 skip link、面包屑。
- `command.*`：命令面板。
- `history.*`：历史侧栏、任务入口、历史项操作。
- `tagDialog.*`：统一标签编辑弹窗。
- `route.*`：路由标题、导航标签、命令面板中的页面名。

新增 namespace 应与功能边界一致，例如 `settings.*`、`taskCenter.*`、`essayEvaluation.*`。不要把业务页面文案塞进 `common.*`，除非它确实跨多个领域复用。

## 新增文案流程

1. 判断文案位置。
   - 应用外壳、导航、路由、全局弹窗和跨页面组件必须走 i18n。
   - 单一业务页内部文案可先保留中文，但如果同一组件被两个以上页面复用，应走 i18n。
2. 在 `zh-CN.json` 和 `en-US.json` 同时添加 key。
3. 在组件中通过 `useI18n().t(key)`、`routeLabel(...)` 或对应 feature hook 读取。
4. key 名保持稳定，不把完整中文句子当 key。
5. PR 中说明新增 namespace 和是否存在暂未国际化的业务文案。

## 审计命令

统计 i18n 调用：

```powershell
rg -n "\bt\(" frontend\src -g "*.tsx" -g "*.ts"
```

统计中文硬编码：

```powershell
rg -n "[\u4e00-\u9fff]" frontend\src -g "*.tsx" -g "*.ts"
```

比较中英文 locale key：

```powershell
python - <<'PY'
import json
from pathlib import Path
zh = json.loads(Path('frontend/src/i18n/locales/zh-CN.json').read_text(encoding='utf-8'))
en = json.loads(Path('frontend/src/i18n/locales/en-US.json').read_text(encoding='utf-8'))
print('missing_en', sorted(set(zh) - set(en)))
print('missing_zh', sorted(set(en) - set(zh)))
PY
```

## 待迁移重点

优先迁移：

- 设置页和全局通知。
- 任务中心状态、操作和错误提示。
- Dashboard、搜索页、导出中心等跨入口页面。
- 复用组件内的按钮、空状态、校验提示。

暂缓迁移：

- 学科内容、作文反馈、题目解析、模型生成结果等用户/模型内容。
- 短期实验页和开发演示页。
