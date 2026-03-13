# AI 出题失败任务排查报告

生成时间: 2026-03-13

排查范围: 数据库中全部 `question_library_generate` 失败任务，共 2 个。

## 摘要

本次两条 AI 出题失败任务的共同问题，不是前端参数格式错误，也不是题目主题本身无法生成，而是后端运行时实际使用了错误的 LLM 路由配置。

可以确认的结论有两点：

1. 系统运行时被固定到了 `fireworks` Provider，但实际调用的模型却是 `Pro/moonshotai/Kimi-K2.5`，这在当前 Provider 下不可用。
2. 出题链路调用 LLM 时使用了 `raise_on_fail=False`，导致真实上游错误被吞掉，最终统一表现为 `no_questions_generated`。

因此，这两条任务的表面错误虽然相同，但真正原因是：模型请求配置失败，随后又被错误处理逻辑掩盖。

## 失败任务概览

| 任务 ID | 主题 | 题型 | 创建时间 | 运行时长 | 最终错误 |
| --- | --- | --- | --- | --- | --- |
| `ql-gen-axifiz3qb4m` | 导数 | 解答题 | `2026-03-13 09:59:29` | `18.727s` | `no_questions_generated` |
| `ql-gen-vw7f61vkg7b` | 圆锥曲线 | 空 | `2026-03-13 10:00:23` | `33.342s` | `no_questions_generated` |

这两个任务的事件轨迹高度一致:

- 都经过了 `SourcePack -> Spec Search -> Draft Realization -> Judge`
- 都在接近结束时写入 `error: no_questions_generated`
- 都没有出现 `done` 事件
- 都没有产出任何预览草稿

这说明失败点集中发生在出题草稿生成阶段，而不是任务创建、参数校验或结果落库阶段。

## 关键证据

### 1. 数据库存储的失败结果完全一致

在 `tasks` 表中，这两个任务都满足以下条件：

- `task_type = question_library_generate`
- `status = failed`
- `error_json = {"message": "no_questions_generated"}`

在 `task_events` 表中，两条任务合计只有 18 条事件，其中包含 2 条 `error` 事件，没有任何 `done` 事件。

### 2. 学习档案为空，但不是直接根因

当前 `study_archives` 表为空：

- `study_archives_count = 0`
- `高中数学 / 导数` 无匹配档案
- `高中数学 / 圆锥曲线` 无匹配档案

这意味着两个任务虽然传入了 `use_study_archive=true`，但实际上没有拿到额外学习资料。这个因素会让上下文变弱，但不会直接导致任务失败，因为 `build_source_pack()` 在没有档案时仍会继续构建基础素材包。

### 3. 运行时 Provider 与模型配置不匹配

当前运行时配置摘要如下：

- `llm_provider_pinned = True`
- `llm_active_provider = fireworks`
- `lesson_plan_provider = fireworks`
- `lesson_plan_model = Pro/moonshotai/Kimi-K2.5`
- `lesson_plan_base_url = https://api.fireworks.ai/inference/v1`

而 `.env` 中实际写的是：

- `LESSON_PLAN_PROVIDER=openrouter`
- `LESSON_PLAN_MODEL=deepseek/deepseek-v3.2`

但这些值被 `config/model.json` 覆盖，因为该文件显式设置了：

- `active_provider = fireworks`
- `lesson_plan = Pro/moonshotai/Kimi-K2.5`
- `fireworks.api_key = YOUR_FIREWORKS_API_KEY`

所以系统真实执行的不是 `.env` 中的 `OpenRouter + DeepSeek`，而是 `Fireworks + Kimi` 这一组不匹配配置。

### 4. 最小复现实验已经验证真实上游错误

在当前运行时配置下，直接执行最小 LLM 调用并强制 `raise_on_fail=True`，得到的真实错误为：

```text
RuntimeError
llm_request_failed status=404 model=Pro/moonshotai/Kimi-K2.5 provider=fireworks msg=Model not found, inaccessible, and/or not deployed
```

这说明问题不在“题目生成逻辑不会出题”，而在“当前 Provider 下请求了不存在或不可用的模型”。

### 5. 代码吞掉了真实错误，最后统一折叠成 `no_questions_generated`

关键调用链如下：

- `backend/question_library/generation.py:145`
  - `realize_drafts()` 调用 `chat_completion_text(...)`
- `backend/question_library/generation.py:188`
  - 传入 `raise_on_fail=False`
- `backend/core/llm_client.py:802`
  - 上游 HTTP 失败时返回空的 `ChatCompletionResult()`
- `backend/question_library/generation.py:194`
  - `_extract_json_obj(text)` 无法从空文本中提取 `questions`
- `backend/question_library/generation.py:196`
  - `realize_drafts()` 返回空列表
- `backend/api/question_library.py:736`
  - 最终抛出 `RuntimeError("no_questions_generated")`

因此，用户最终看到的是泛化后的业务错误，而不是实际的 LLM 请求错误。

## 根因判定

### 主根因

AI 出题失败的直接主因是 LLM 配置错误：

- Provider 被固定为 `fireworks`
- 模型被配置为 `Pro/moonshotai/Kimi-K2.5`

该组合在当前运行环境下不可用，并且已经被最小复现实验直接验证为 `404 Model not found, inaccessible, and/or not deployed`。

### 放大问题的次根因

错误处理策略隐藏了真实失败原因：

- LLM 调用失败后，没有把真实的 Provider、模型名和 HTTP 错误写入任务错误信息
- 上游错误最终被统一折叠成 `no_questions_generated`

这会让排查方向被误导为“内容生成失败”，而不是“模型配置失败”。

### 非主因但值得记录的背景因素

- `study_archives` 为空，导致 `use_study_archive=true` 实际没有提供附加上下文
- 第二个任务的 `question_type` 为空，会降低题目约束

这两点可能影响题目质量，但都不是本次两条任务同时失败的决定性原因。

## 建议处理

### 立即修复

1. 校正运行时模型路由，让 Provider 和模型保持一致。
2. 如果预期使用 `.env` 中的 `OpenRouter + DeepSeek`，需要取消或修正 `config/model.json` 中的覆盖配置。

### 代码层修复

1. 在出题链路中避免默认吞掉 LLM 错误，至少在任务错误信息中保留真实的上游报错。
2. 对 Provider 与模型组合增加启动期或调用前校验，避免错误配置进入任务执行阶段。
3. 将 `no_questions_generated` 仅用于“模型调用成功但返回空题目”的情况，不要覆盖底层请求失败。

### 体验层改进

1. 当 `use_study_archive=true` 但未匹配到档案时，提示“未找到学习档案，已使用基础素材继续生成”。
2. 当 `question_type` 为空时，在任务详情中明确显示为空值，减少排查歧义。

## 最终结论

这两条 AI 出题任务失败的真实原因可以归纳为：

> 出题链路在 `realize_drafts` 阶段调用了一个当前 Provider 下不可用的模型，导致 LLM 请求直接失败；随后由于错误被吞掉，任务最终只表现为 `no_questions_generated`。
