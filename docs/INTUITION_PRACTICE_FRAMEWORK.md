# 直觉练习出题框架

## 1. 目标与定义

本框架直接作用于原 `question_library_generate` 线路，不增加平行的 practice runner。

这里的“直觉”不是答得快、蒙得准或熟记题型，而是学生能够在脑中形成并操作一个内部表征：先对对象、关系或变化作出方向性判断，再用最短的逻辑、计算、图示、实验或文本证据校准它，最后把同一结构迁移到不同表面。

因此，一道合格的直觉练习必须形成以下闭环：

1. **感知**：完整计算前先作判断，并记录信心。
2. **模型显化**：说清脑中看见的对象、关系和决定性线索。
3. **最小验证**：只使用足以检验第一感觉的证据，不强迫长推导。
4. **迁移**：保留决定性结构，同时改变至少两个表面特征。
5. **品鉴（可选）**：比较正确解法的简洁、对称、统一、推广或条件必要性。

训练价值主要出现在“第一感觉”和验证结论不一致之处。反馈应帮助学生指出偏差来自哪个内部模型，而不是只判对错或羞辱错误直觉。

## 2. 与考纲、教材和题库的关系

直觉训练不能越过课程边界。生成请求中的学科、年级、教材版本、知识点和学习资料仍由原线路的 `curriculum_context` 处理，并作为硬约束进入生成和快速校验。

每个练习包应保存：

- 对齐的知识点；
- 范围说明；
- 是否在当前课程范围内；
- 题干条件是否充分；
- 答案是否正确且与解析一致；
- 是否存在致命歧义。

参考题只用于提取课程边界、典型表征、结构线索和常见错误直觉。不得把长推导、参数分类数量、运算量或“压轴感”本身当作质量，也不得复刻参考题的数值、情境、结论或解法表述。

## 3. 练习配置

原生成请求新增 `intuition_practice`：

```json
{
  "practice_goal": "structural_intuition",
  "intuition_kinds": ["prediction", "representation", "invariant"],
  "packet_size": 3,
  "feedback_mode": "guided"
}
```

### 练习目标

| 目标 | 生成重点 |
| --- | --- |
| `fluency` | 把基础对象练到可以直接操作，但不把套路背诵冒充理解 |
| `structural_intuition` | 关系、表征、不变量、对称与决定性线索 |
| `intuition_correction` | 可解释的认知冲突、边界或反例，用于修正错误模型 |
| `transfer` | 同结构异表面，至少改变两个表面特征 |
| `solution_appreciation` | 比较正确解法为何更自然，至少生成四个环节 |

### 直觉切面

`prediction`、`representation`、`invariant`、`boundary`、`counterexample`、`solution_comparison` 分别对应先猜后证、换表征、不变量、边界、反例和解法比较。

### 反馈方式

- `guided`：渐进提示，第一条提示不能直接泄露答案；
- `concise`：只给决定性线索和短校准；
- `reflective`：用追问促使学生重述内部模型，再提供参考判断。

## 4. 结构化输出

旧客户端继续读取 `stem`、`answer`、`analysis`。新线路同时生成 `intuition_packet`：

```json
{
  "version": "1.0",
  "practice_goal": "structural_intuition",
  "atom": {
    "concept": "需要在脑中操作的知识对象",
    "internal_model": "希望形成的内部模型",
    "mental_action": "比较、移动、缩放、估计、取极端或换表征",
    "decisive_cue": "真正决定结论的线索",
    "expected_first_feel": "合理但尚未形式化的第一感觉",
    "common_false_intuition": "最值得校准的错误直觉",
    "formal_anchor": "最短充分证据",
    "transfer_mutation": "同结构异表面的变化方式",
    "boundary_flip": "使原结论翻转的关键条件",
    "feedback": "模型校准策略"
  },
  "stages": [
    {
      "stage": "perception",
      "kind": "prediction",
      "prompt": "学生任务",
      "hint": "提交后才显示的提示",
      "expected_answer": "参考判断",
      "feedback": "针对内部模型的校准"
    }
  ],
  "curriculum_alignment": {
    "knowledge_points": [],
    "scope_note": "",
    "in_scope": true
  },
  "validation": {
    "status": "passed",
    "scope_ok": true,
    "answer_correct": true,
    "answer_analysis_consistent": true,
    "conditions_sufficient": true,
    "unambiguous": true,
    "transfer_valid": true,
    "issues": [],
    "repaired": false
  }
}
```

三个环节时固定为“感知 → 模型显化 → 迁移”；四、五个环节按目标加入“最小验证”和“品鉴”。阶段在正规化时按教学顺序排列，每个阶段名最多出现一次。

## 5. 轻量正确性校验

学生自主练习不需要多模型共识、三次求解、复杂 beam 验证、IRT/DIF 或专家级心理测量。默认只进行一次快速检查，失败时最多修复一次。

但“轻量”不等于容忍错误。以下任一项失败都不能进入可练习结果：

- 超出指定课程范围；
- 独立核验无法得到给定答案；
- 答案与解析矛盾；
- 条件不足；
- 存在影响结论的歧义；
- 缺少感知、模型显化或迁移环节；
- 迁移仅替换数字，没有保留可辨认的决定性结构。

难度、创新性、区分度和“优美程度”不作为这道安全门的主观评分项。数学审美通过让学生依据明确标准比较解法来考察，而不是让模型替学生打一个美感分。

## 6. 学生作答与反馈数据

作答状态保存在原 session 的 `practice_attempts[question_id]`，不混入可入库的题目内容：

```json
{
  "first_guess": "",
  "confidence": 60,
  "phase": "perception",
  "hint_level": 1,
  "reflection": "",
  "stage_responses": {
    "perception": {
      "initial_response": "",
      "final_response": "",
      "confidence": 60,
      "hint_level": 1
    }
  },
  "completed": false
}
```

前端遵循“先作答、后提示、再修正”：没有初答不能展开该阶段反馈，全部阶段作答后才展示原答案与解析。刷新后恢复各阶段进度；局部重生成导致内容变化时，必须清除旧练习包、旧校验和旧作答状态。

## 7. 学科适配

| 学科 | 第一感觉的对象 | 最小验证 | 审美或品鉴标准 |
| --- | --- | --- | --- |
| 数学 | 数量级、图形走势、对称、不变量、边界 | 短推导、特例、反例、图形或计算 | 简洁、对称、统一、推广性、条件必要性 |
| 物理 | 过程方向、极限、量纲、图像趋势 | 守恒、量纲、极端情况或局部计算 | 模型解释力、变量选择和表征经济性 |
| 化学 | 粒子图景、守恒、平衡移动 | 方程、守恒、实验现象或条件变化 | 微观与宏观解释的一致性 |
| 生物 | 系统、反馈、因果链和稳态 | 对照证据、机制链或边界条件 | 解释范围、证据简约与系统一致性 |
| 语文/语言 | 语篇预期、结构转折、语义关系 | 文本证据、语法约束或反例语境 | 表达精确、结构呼应与证据充分 |
| 历史/社会学科 | 因果方向、时序、利益结构 | 史料证据、时间线和反事实边界 | 解释的统一性、证据覆盖与假设节制 |

不同学科共享同一个学习循环，但不得把数学术语机械套到其他学科。生成器应替换“形式证明”为该学科最小、可复核的证据形式。

## 8. 原线路阶段映射

为兼容任务事件和历史会话，阶段 ID 不变，只更新职责：

| 原 stage ID | 新职责 |
| --- | --- |
| `source_pack` | 汇总课内材料与知识边界 |
| `curriculum_context` | 建立年级、教材和知识点约束 |
| `reference_crawl` / `reference_analysis` | 可选地提取参考题结构，不模仿难度和表面 |
| `brainstorm` | 设计直觉原子 |
| `spec_search` | 编排练习包结构 |
| `draft_realization` | 生成结构化练习包及兼容三字段 |
| `diagram_generation` | 按需生成辅助表征 |
| `judge` | 一次快速正确性校验，最多修复一次 |
| `final_selection` | 按直觉结构去重并截取目标数量 |
| `pending_review` | 进入可练习、可确认和可入库状态 |

题库列表不携带完整练习包，避免大字段拖慢分页；`GET /items/{question_id}` 的题目详情按需返回结构化 `intuition_packet`。
