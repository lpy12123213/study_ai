# 自学资料生成质量 Benchmark

对 `POST /api/study-materials/generate` 生成的自学资料做**困难但便于评分**的离线评测：
用例驱动、确定性评分为主、百分制报告。benchmark 只观察、不修改生成链路。

## 快速开始

```bash
# 1. 校验用例（不跑生成，离线）
python -m backend.evals.study_materials.runner --case all --dry-run

# 2. 启动后端后跑单个用例（真实生成，SSE 采集）
python -m uvicorn backend.app:app --port 8000
python -m backend.evals.study_materials.runner --case lebesgue_integral

# 3. 全量 + LLM 复核 + 参考文献链接抽查
python -m backend.evals.study_materials.runner --case all --llm-judge --check-links
```

每个用例在 `artifacts/evals/study_materials/<case_id>/<timestamp>/` 产出：
`events.jsonl`（SSE 事件流）、`final.md`（成稿）、`meta.json`、`task_info.json`、
`score.json`、`report.md`（逐项得分与扣分原因）。

## 评分体系（100 分）

| 维度 | 分值 | 评分方式 |
|---|---|---|
| R 多步检索过程 | 15 | 事件流：来源类别数 ≥3、每 kp 深读 `browse_web_pages`、唯一来源 URL 数、检索轮次 ≥2×kp、权威域名命中（用例 `expected_domains`） |
| K 知识理解 | 35 | K1 用例锚定事实点（正则匹配，可选 LLM 复核）×**可溯源门控**；K2 常见误解陷阱（写错或未驳正均判 0）；K3 概念辨析（对比对须在小窗口内共现） |
| S 子代理使用 | 15 | 事件流：subagent_start/end、per-kp 覆盖率 ≥80%、子代理摘要 |
| F 结构与格式 | 12 | 必备骨架、目录锚点可跳转 + 标题层级、数学 lint + 关键公式（复用 `backend.core.text_lint` 与 `coverage.split_sections_by_kp`）、篇幅 |
| A 美观与可读性 | 10 | 图/表/图注计数；排版质量（确定性代理：`--llm-judge` 可换 LLM rubric） |
| C 引用与学术规范 | 13 | 参考文献小节 + URL、内联引用标记与文末一一对应、链接可访问性抽查（`--check-links`） |

### 可溯源门控（K1）

`K1得分 = 命中比例 × (0.15 + 0.85 × 内联引用比例)`。立场：自学资料的关键论断必须
可溯源；没有内联引用的"裸论断"最多只值 15%。门控系数见
`backend/evals/study_materials/graders/knowledge.py` 的 `_TRACE_FLOOR`。

## 难度设计（为什么当前系统得分 <20 是预期）

每个低分机制都对应代码中的真实缺口，而非刻意刁难：

- **S ≈ 0**：默认 ReAct 路径不派发子代理；subagent 事件仅 plan 模式
  `foreach_knowledge_point` 步骤块触发（`backend/agent/execution_strategy.py`）。
- **C ≈ 0**：汇编收集了 `refs_by_kp` 但从不渲染（`backend/agent/tools/knowledge/study_archive.py:71-86`），
  成稿无参考文献小节；小节写手 prompt 明确禁止输出引用标记。
- **K1 被门控到 15%**：上面两条叠加，事实点即使有内容正确也只能拿零头。
- **F2 锚点 0 分**：现行目录是纯文本 bullet，无 `[文本](#锚点)` 链接。
- **A1 图 0 分**：TikZ/SVG 工具链缺失时只写降级说明。
- **用例本身难**：研究级主题 + 陷阱题（如"勒贝格积分是黎曼积分特例"）
  + 权威域名要求（RFC/nobelprize/nature）+ 时效性要求（base/prime editing 年份）。

难度旋钮集中在两处：`graders/common.py` 的 `DIMENSION_MAX`（维度权重）与
各用例 JSON 的阈值字段（`min_unique_sources` / `expected_domains` / `required_facts`）。
模拟现行默认链路产物的离线锚点测试见
`backend/tests/test_study_materials_evals.py::ScorecardTests::test_current_style_run_scores_below_20`。

## 首批用例（`backend/evals/study_materials/cases/`）

| 用例 | 学科 | preset | 考察点 |
|---|---|---|---|
| `lebesgue_integral` | 数学分析 | deep | 三大收敛定理、Dirichlet 函数、黎曼 vs 勒贝格辨析、换序条件陷阱 |
| `quantum_harmonic_oscillator` | 量子力学 | deep | 能级公式、零点能、升降算符、经典/量子概率分布陷阱 |
| `tcp_congestion_control` | 计算机网络 | standard | 慢启动/拥塞避免/快恢复、RFC 权威来源、rwnd/cwnd 混淆陷阱 |
| `crispr_cas9` | 分子生物学 | deep | PAM/gRNA/DSB 修复、2020 诺贝尔化学奖陷阱、base vs prime editing 时效性 |
| `french_revolution_causes` | 世界历史 | standard | 多因素归因（反单一归因陷阱）、1788 歉收、中英文多源交叉 |
| `gradient_descent_variants` | 机器学习 | deep | 更新公式、偏差修正、学习率调度、"Adam 总是更优"陷阱 |

## 第二批用例

| 用例 | 学科 | preset | 考察点 |
|---|---|---|---|
| `eigen_decomposition` | 线性代数 | deep | 对角化判定、代数/几何重数辨析、"所有矩阵可对角化"陷阱、谱定理 |
| `photosynthesis` | 生物学 | standard | O₂ 来自水光解（非 CO₂）、暗反应间接需光、C3/C4/CAM 与光呼吸 |
| `bayes_medical_screening` | 概率论 | standard | 基础概率谬误、灵敏度 ≠ 阳性预测值、低患病率下假阳性占多数 |

用例事实点均锚定学术来源（`source_urls`：Wikipedia/RFC/Nobel Prize/Nature 等），
编写时已逐条核实（RFC 5681/6582/8312、Komor 2016、Anzalone 2019、1788 歉收等）。

## 新增用例

复制任一 JSON 修改即可；schema 校验规则（`case_schema.py`）：
`required_facts` 至少 1 条且 id 唯一、正则必须可编译、`preset ∈ quick|standard|deep|research`、
`expected_knowledge_points` 非空。建议每个用例配 8-12 条事实点、2-3 条陷阱、2 组辨析对。

注意：`options.prefer_local_archive` 必须保持 `false`，否则命中历史归档会跳过真实生成。

## 校准记录

- 2026-08-01：benchmark 初版落地。离线锚点测试（模拟现行默认链路产物形态）总分 <20 通过。
- 2026-08-01：真实链路首次校准（deepseek 生产配置、默认 legacy ReAct 路径）：

  | 用例 | 总分 | R | K | S | F | A | C | 运行目录 |
  |---|---|---|---|---|---|---|---|---|
  | lebesgue_integral（deep） | **10.0** | 10.0 | 0 | 0 | 0 | 0 | 0 | `artifacts/evals/study_materials/lebesgue_integral/20260801_103739/` |
  | tcp_congestion_control（standard） | **15.2** | 8.8 | 0 | 0 | 4.9 | 1.5 | 0 | `artifacts/evals/study_materials/tcp_congestion_control/20260801_105148/` |

  基线均 <20，无需调整权重。校准暴露的两个真实生成缺陷（比分数更有价值）：

  1. **写作步骤硬超时（lebesgue）**：`generate_study_material` 连续 14 次
     `Tool timeout after 240s`，成稿为空，orchestrator 诚实判 `empty_material`。
  2. **知识点拆分塌缩（tcp）**：`split_knowledge_points` 未生效，整条 query 被当作
     唯一知识点，21 次写作调用产出 354 字符空壳骨架（仅标题/目录/使用建议）。

  校准同时修正了评分器三处公平性问题（均已回归测试覆盖）：空稿在 A2 误得分；
  SSE 裁剪大 tool_result 导致来源统计漏计（改由 `task_info.search_summary_by_kp` 补全）；
  空壳骨架靠标题/目录的 query 回显在 K 维度蹭分（知识判定改为剥离标题与目录后的正文）。
  复评已落盘运行用 `--regrade <run_dir>`（不重新生成），成稿缺失时自动回退 `md_url` 下载。

- 2026-08-01：基线暴露的生成缺陷修复后复跑（分支 `feat/study-materials-benchmark`）：

  | 模型 | 用例 | 总分 | 成稿 | R | K | S | F | A | C |
  |---|---|---|---|---|---|---|---|---|---|
  | deepseek-v4-pro | tcp_congestion_control | **44.9** | 10768 字符 | 8.8 | 19.2 | 0 | 9.9 | 7.0 | 0 |
  | deepseek-v4-pro | lebesgue_integral | **36.8** | 9358 字符 | 8.5 | 13.1 | 0 | 8.7 | 6.5 | 0 |
  | deepseek-v4-flash | tcp_congestion_control | **41.6** | 14920 字符 | 10.0 | 16.8 | 0 | 8.3 | 6.5 | 0 |
  | deepseek-v4-flash | lebesgue_integral | **40.4** | 22468 字符 | 10.0 | 17.2 | 0 | 8.8 | 4.5 | 0 |

  失分地图（修复后）：S（无子代理事件）与 C（无参考文献/内联引用）为结构性 0 分；
  K1 受 0.15 溯源门控压制；R 缺深读与权威域名命中。下一步提升主攻：引用体系
  （渲染 refs_by_kp + 内联标记）、plan 模式子代理、每 kp 深读。

  修复的缺陷（详见 `backend/tests/test_study_materials_write_path_fixes.py` 回归）：
  写作 240s 超时预算、直写路径 0 素材静默成功、审阅 JSON flake 判死整跑、
  done 不携成稿误判 empty_material、revise_markdown 截断（输出预算按原稿放大 + 70% 长度护栏）。

  运维注意：多进程共享同一 sqlite 库时，任一进程启动（含 `--reload` 重载、
  `TestClient(create_app())` 测试）都会触发 `restart_recovery` 把 running 任务标记为
  `server_restarted` 杀掉——benchmark 运行期间不要并行跑测试套件或重启同库服务。

## 已知边界（后续扩展）

- 仅 HTTP/SSE 模式；in-process 模式（直接驱动 `StudyMaterialsTaskManager`）留待后续。
- A2 默认是确定性代理；渲染版式（HTML/PDF）视觉评审未实现。
- LLM judge 是可选增强（`--llm-judge`），默认关闭以保证完全可复现。
