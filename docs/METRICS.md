# Metrics 与调试调用记录

Study AI 使用两层 metrics：

- `backend/core/metrics.py`：HTTP 请求级 Prometheus instrumentation。
- `backend/core/business_metrics.py`：业务级 Prometheus Counter，包括 LLM tokens/cost/request、工具调用和任务终态。

`backend/llm/metrics.py` 不注册 Prometheus 指标。它是 LLM 调用侧的薄封装：

1. `record_llm_call(...)` 委托 `backend.core.business_metrics.record_llm_usage(...)` 写入业务指标。
2. 同时维护最多 200 条进程内 `_debug_calls`，供 `/api/llm-debug` 和设置页调试面板读取。
3. `recent_llm_calls(...)` 返回聚合后的 `totals`、`by_model` 和最近调用列表。

## LLM 指标

Prometheus 指标由 `business_metrics.py` 单点注册：

- `study_ai_llm_tokens_total{provider,model,tier}`
- `study_ai_llm_cost_usd_total{provider,model,tier}`
- `study_ai_llm_requests_total{provider,model,tier,status}`

LLM debug payload 额外包含：

- `usage.prompt_tokens`
- `usage.completion_tokens`
- `usage.total_tokens`
- `usage.cached_tokens`
- `usage.cost_usd`

`cached_tokens` 来自 provider usage 字段，例如 `cached_tokens`、`cache_read_input_tokens`、`cache_creation_input_tokens`、`prompt_tokens_details.cached_tokens` 或 `input_tokens_details.cache_read`。

## 新增指标规则

- 新增 Prometheus Counter/Histogram/Gauge 时优先放在 `backend/core/business_metrics.py` 或 `backend/core/metrics.py`。
- 领域模块只能调用记录函数，不直接 import `prometheus_client`。
- 如果需要本地调试 timeline，可以在领域 metrics wrapper 中维护进程内 deque，但不能重复注册同名 Prometheus metric。
- 新增 label 必须低基数，不能使用用户输入、trace_id、task_id 或完整 URL 作为 label。
