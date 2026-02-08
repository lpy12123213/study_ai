"""
AI 对话服务 - 使用 OpenAI-compatible API（OpenRouter / Fireworks）实现工具调用
"""
import json
import re
import asyncio
import httpx
from typing import List, Dict, Any, AsyncGenerator, Optional
from backend.core.settings import settings
from backend.config import (
    CHAT_PROVIDER,
    MAIN_MODEL,
    MAIN_MODEL_TEMPERATURE,
    MAIN_MODEL_MAX_TOKENS,
    MAX_TOOL_ITERATIONS,
    API_TIMEOUT
)
from backend.subjects import DEFAULT_DIFFICULTY, normalize_difficulty, resolve_subject
from backend.crawler.zujuan_crawler import ZujuanCrawler

# 系统提示词（带学科占位符）
SYSTEM_PROMPT_TEMPLATE_LEGACY = """你是一个智能组卷助手，具备完全自主的多轮工具调用能力。你可以连续执行多个工具调用，无需用户中间确认，直到完成整个组卷任务。

## 当前学科：{subject}

你当前正在为【{subject}】学科组卷，所有搜索和选题都应该针对这个学科。

## 核心能力
1. **search_questions** - 搜索题目（关键词、难度、题型）
   - 难度参数：'简单'、'中等'、'困难'
   - 重要：难度系数越小越难（困难 < 中等 < 简单）
   - 用户要求"简单题目"时使用难度='简单'，"困难题目"时使用难度='困难'
2. **batch_get_question_details** - 批量获取题目详情（最多10个）
3. **select_best_question** - 【子AI选题】从候选题目中智能选择最符合要求的一道
4. **create_paper** - 创建试卷
5. **get_papers** - 查看已有试卷

## 子AI选题功能（重要）

当你需要从多道候选题目中选择最合适的一道时，**必须调用 select_best_question 工具**：

```
调用 select_best_question(
    question_ids=["id1", "id2", "id3"],  # 2-5个候选题目
    requirement="选题要求描述"
)
```

子AI会分析每道题目的内容、难度、知识点，返回最佳选择和理由。

### 每次调用工具后必须说明情况：
- 搜索后：说明找到了多少道题目
- 获取详情后：简述题目内容概况
- **子AI选题后：必须详细说明子AI的选择结果和理由**
- 创建试卷后：汇报成功信息

## 自主多轮执行模式

你可以在一次对话中**连续调用多个工具**，系统支持最多10轮工具调用。**每轮最多调用3个工具**，超过的会被截断。推荐执行流程：

```
搜索题目 → 获取详情 → 子AI选择最佳题目 → (重复多轮) → 创建试卷 → 汇报结果
```

### 执行策略

**第1轮**：搜索题目
- 调用 search_questions 搜索相关题目

**第2轮**：获取详情
- 调用 batch_get_question_details 获取候选题目详情

**第3轮**：子AI智能选题
- 调用 select_best_question，让子AI从候选中选择最符合要求的题目
- **说明子AI的选择结果：选了哪道题、选择理由是什么**

**第4轮+**：继续搜索其他题型/知识点，重复选题过程

**收集完所有题目后**：
- 整理并展示试卷细目表（题号、ID、知识点、题型、难度）
- 询问用户是否确认创建
- 等待用户回复

**用户同意后**：调用 create_paper 创建试卷并汇报结果

## 决策规则

1. **完整规划再执行**：收到组卷需求后，先完成所有题目的搜索和选题工作
2. **必用子AI选题**：每个题型/知识点都应该调用子AI来选择最佳题目
3. **每次说明情况**：工具调用后要告诉用户发生了什么
4. **智能补充**：如果搜索结果不足，自动尝试相关关键词
5. **先展示细目表，征求同意后再创建**：
   - 完成所有题目选择后，整理成表格形式的细目表
   - 细目表必须包含：题号、难度、知识点（可多个）、题目ID
   - 格式示例：
     ```
     【试卷细目表】
     题号 | 难度 | 知识点 | 题目ID
     1    | 容易 | 磁现象和磁场 | 12345678
     2    | 适中 | 机械振动、机械波 | 23456789
     ...
     ```
   - 展示后询问："以上是试卷细目表，是否确认创建？"
   - **只有在用户明确同意（如"确认"、"可以"、"好的"等）后才调用 create_paper 工具**
   - 如果用户不同意或要求修改，询问具体调整需求

## 典型场景示例

用户："帮我出一份关于{subject_topic}的测试，3道选择题"

执行过程：
1. 搜索{subject_topic}相关选择题（第1题） → "找到15道候选题目"
2. 获取前5道题目详情
3. 调用子AI选题 → "子AI选择了题目ID:xxx，理由：..."
4. 搜索{subject_topic}相关选择题（第2题） → "找到12道候选题目"
5. 获取详情并调用子AI选题 → "子AI选择了题目ID:yyy，理由：..."
6. 搜索{subject_topic}相关选择题（第3题） → "找到10道候选题目"
7. 获取详情并调用子AI选题 → "子AI选择了题目ID:zzz，理由：..."
8. **展示试卷细目表**：
   ```
   【试卷细目表】
   题号 | 难度 | 知识点 | 题目ID
   1    | 容易 | {subject_topic}的基本概念 | xxx
   2    | 适中 | {subject_topic}的应用 | yyy
   3    | 较难 | {subject_topic}的综合运用 | zzz
   ```
9. **询问用户确认** → "以上是试卷细目表，是否确认创建？"
10. **等待用户回复**
11. 如果用户同意（"确认"/"可以"/"好的"）→ 创建试卷 → "已创建试卷《{subject_topic}测试》"
12. 如果用户不同意 → 询问需要调整哪些题目

注意：题干中的[公式:<svg...>]是数学公式，子AI能够识别这些SVG矢量图中的数学符号。"""

# v3 system prompt: tool-first, compliance-aware, more one-shot friendly.
SYSTEM_PROMPT_TEMPLATE = """你是一个【智能组卷助手】。你的目标是：根据用户要求，从组卷网题库中筛选题目编号（ID），并在需要时创建并保存试卷。

【当前学科】{subject}
- 所有检索/筛选必须严格针对该学科。
- 版权/合规：默认不向用户完整复述题目原文（题干/选项/答案/解析），避免版权风险；对用户只展示“题目ID + 必要元数据（题型/难度/知识点/来源）”。
- 若用户坚持索要题目原文：说明无法直接提供，建议使用组卷网官方页面或本系统的下载链接跳转查看。

【工具参数规范（很重要）】
- 你输出的工具参数必须是严格 JSON：
  - integer/number 字段必须使用数值类型，不要把数字写成字符串（例如用 10 而不是 "10"）。
  - boolean 字段必须使用 true/false，不要用 "true"/"false" 字符串。
  - array 字段必须使用数组，不要用字符串冒充 JSON。
- 当需要年级/教材版本/地区/试卷类型等可选项或 ID 时，优先调用 get_available_filters 获取可用值后再继续，避免猜错导致无结果。

【重要约定：难度】
- 难度系数越小越难：困难 < 中等 < 简单。
- 用户说“简单/基础/入门”→ difficulty='简单'；“中等/适中”→ difficulty='中等'；“困难/拔高/压轴”→ difficulty='困难'。
- 若用户给出 difficulty_value_min/max，也要按“越小越难”的含义应用。

【两阶段工作流（必须遵守）】
你要把“规划”和“执行”拆开：

阶段 A：信息搜集 → 生成【组卷规划表】（必须先做）
1) 先调用 get_available_filters 获取当前学科可用：年级/题型/教材版本/地区等（避免猜 ID）。
2) 再调用 1-3 次 search_questions 做“题库探测”（用较小 limit，例如 5-8），验证关键词/题型/难度是否有足够题目。
3) 基于筛选项与探测结果，生成【组卷规划表】（见下方输出格式）。
4) 生成规划后：必须等待用户确认；不要开始正式组卷（不要调用 compose_paper_blueprint / create_paper）。

阶段 B：确认后执行组卷
1) 只有当用户回复明确确认（例如：确认开始组卷 / 确认 / 开始组卷）后，才进入执行阶段。
2) 执行阶段必须优先使用 compose_paper_blueprint 按规划批量组装题目ID；必要时再用子AI精挑。
3) 执行完成后再创建试卷 create_paper，并输出【试卷细目表】与 paper_id。

【可用工具】
- search_questions：按关键词/题型/难度/年级/教材/地区/年份等搜索题目ID
- get_available_filters：获取该学科可用筛选项（年级/教材/题型等），避免写死 ID
- compose_paper_blueprint：根据“蓝图槽位”批量搜索并组装题目ID列表（优先使用）
- batch_get_question_details：批量获取候选题目详情（最多 10 个，用于内部判断/二次筛选）
- select_best_question：子AI选题（在 2-5 道候选中选最符合要求的 1 道，并给出理由）
- create_paper：创建试卷（只提交题目ID列表）
- get_papers：查看已保存试卷

【阶段 A 输出格式要求：组卷规划表】
当你完成信息搜集后，必须输出一个可机器解析的规划 JSON，用以下标签包裹：
- 标签内只能输出“裸 JSON”（不要使用 Markdown 代码块，不要输出 ```json）。
- JSON 必须能被严格解析（JSON.parse / json.loads 直接通过），不要有注释/尾逗号/多余文字。

<EXAM_PAPER_PLAN>
{{
  "version": 1,
  "subject": "{subject}",
  "paper_name": "（建议的试卷名称）",
  "edu_level": "",
  "learn_grade": "",
  "learn_grade_id": 0,
  "textbook_version": "",
  "province": "",
  "province_id": -1,
  "year": 0,
  "term": 0,
  "paper_type_id": 0,
  "elective_mode": "include",
  "exclude_elective": false,
  "max_pages": 2,
  "per_slot_expand": 3,
  "min_quality_score": 0,
  "dedup_by_stem": true,
  "blueprint": [
    {{
      "section": "选择题",
      "keyword": "{subject_topic}",
      "knowledge_point": "",
      "count": 10,
      "difficulty": "中等",
      "question_type": "选择题",
      "source_contains": "",
      "stem_contains": "",
      "knowledge_contains": "",
      "max_pages": 0
    }}
  ]
}}
</EXAM_PAPER_PLAN>

在标签之外，你只需要用 1-3 句话告知：已生成规划表，并提示用户“确认开始组卷”。（务必至少留一句可读文本，避免出现空回复。）
注意：阶段 A 绝对不要调用 compose_paper_blueprint / create_paper。

【阶段 B 输出格式要求：试卷细目表】
当用户确认后，执行组卷并创建试卷，然后输出【试卷细目表】（纯文本表格即可）并附上 paper_id：
【试卷细目表】
题号 | 题型 | 难度 | 知识点/专题 | 题目ID | 来源(可选)
1 | 选择题 | 中等 | {subject_topic} | 12345678
2 | 填空题 | 中等 | {subject_topic} | 23456789
...

注意：题干中的 [公式:<svg...>] 是数学公式 SVG 片段；必要时可用于内部判断，但不要把题目原文完整复述给用户。"""

def get_system_prompt(subject: str) -> str:
    """根据学科生成系统提示词"""
    # 获取学科相关的示例话题
    topic_map = {
        "高中数学": "函数",
        "高中语文": "古诗词鉴赏",
        "高中英语": "阅读理解",
        "高中物理": "力学",
        "高中化学": "化学反应",
        "高中生物": "细胞",
        "高中政治": "哲学",
        "高中历史": "近代史",
        "高中地理": "自然地理",
        "初中数学": "方程",
        "初中语文": "现代文阅读",
        "初中英语": "语法",
        "初中物理": "电学",
        "初中化学": "元素化合物",
        "初中生物": "生态系统",
        "初中道德与法治": "法律常识",
        "初中历史": "中国古代史",
        "初中地理": "中国地理",
        "小学数学": "四则运算",
        "小学语文": "阅读理解",
        "小学英语": "单词",
    }
    topic = topic_map.get(subject, "相关知识点")
    return SYSTEM_PROMPT_TEMPLATE.format(subject=subject, subject_topic=topic)

# 工具定义
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_questions",
            "description": "搜索题目。根据关键词、难度、题型等条件搜索组卷网上的题目。返回题目ID列表和基本信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，如'函数'、'导数'、'三角函数'等"
                    },
                    "edu_level": {
                        "type": "string",
                        "enum": ["小学", "初中", "高中", ""],
                        "description": "学段筛选，可选：小学/初中/高中（指定后将严格校验）",
                        "default": ""
                    },
                    "difficulty": {
                        "type": "string",
                        "enum": ["简单", "中等", "困难", ""],
                        "description": "难度等级筛选，可选。重要：难度系数越小越难（困难 < 中等 < 简单）。如果用户要求简单题目，使用'简单'；困难题目使用'困难'"
                    },
                    "question_type": {
                        "type": "string",
                        "description": "题型，如'选择题'、'填空题'、'解答题'等，可选"
                    },
                    "learn_grade": {
                        "type": "string",
                        "description": "年级筛选（可选，如：高一/高二/高三/七年级等；建议先通过 get_available_filters 获取可用项）",
                        "default": ""
                    },
                    "learn_grade_id": {
                        "type": "integer",
                        "description": "年级ID（高级；优先级高于 learn_grade）",
                        "default": 0
                    },
                    "textbook_version": {
                        "type": "string",
                        "description": "教材版本/题库分类（可选，如：人教版/外研版/北师大版；建议先通过 get_available_filters 获取可用项）",
                        "default": ""
                    },
                    "elective_mode": {
                        "type": "string",
                        "description": "选修过滤模式（include=不限；exclude=排除选修；only=仅选修）。默认 include",
                        "default": ""
                    },
                    "elective_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "自定义选修识别关键词（可选；默认使用：选修/选择性必修/选必）"
                    },
                    "exclude_elective": {
                        "type": "boolean",
                        "description": "兼容旧参数：true 等价于 elective_mode=exclude（当 elective_mode 为空时）",
                        "default": False
                    },
                    "dedup_by_stem": {
                        "type": "boolean",
                        "description": "按题干去重（避免同质题）",
                        "default": False
                    },
                    "min_quality_score": {
                        "type": "integer",
                        "description": "最小质量分（0-100；0 表示不过滤）",
                        "default": 0
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回题目数量，默认10",
                        "default": 10
                    },
                    "max_pages": {
                        "type": "integer",
                        "description": "最多翻页数（默认 2 页）",
                        "default": 2
                    },
                    "year": {
                        "type": "integer",
                        "description": "年份过滤（如 2024；0 表示不限）",
                        "default": 0
                    },
                    "source_contains": {
                        "type": "string",
                        "description": "来源包含关键字（如：高考、期末、北京等）",
                        "default": ""
                    },
                    "stem_contains": {
                        "type": "string",
                        "description": "题干包含关键字（可选）",
                        "default": ""
                    },
                    "knowledge_contains": {
                        "type": "string",
                        "description": "知识点包含关键字（可选）",
                        "default": ""
                    },
                    "difficulty_value_min": {
                        "type": "number",
                        "description": "难度系数下限（可选）。注意：系数越小越难；题目没有难度系数时不会被剔除"
                    },
                    "difficulty_value_max": {
                        "type": "number",
                        "description": "难度系数上限（可选）。注意：系数越小越难；题目没有难度系数时不会被剔除"
                    },
                    "province": {
                        "type": "string",
                        "description": "地区（可选，如：北京/北京市/全国；建议先通过 get_available_filters 获取 provinces；同时传 province_id 时以 province_id 为准）",
                        "default": ""
                    },
                    "province_id": {
                        "type": "integer",
                        "description": "地区ID（高级；-1 表示不限）",
                        "default": -1
                    },
                    "paper_type_id": {
                        "type": "integer",
                        "description": "试卷类型ID（高级；0 表示不限）",
                        "default": 0
                    },
                    "term": {
                        "type": "integer",
                        "description": "学期（高级；0 表示不限）",
                        "default": 0
                    },
                    "order_by": {
                        "type": "integer",
                        "description": "排序方式（高级；默认 2）",
                        "default": 2
                    }
                },
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_available_filters",
            "description": "获取当前学科下可用的筛选项（年级/试卷类型/教材版本/题型等），用于下拉选择，避免写死ID。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "学科全名（可选，不填则使用当前学科；填写会自动切换）",
                        "default": ""
                    },
                    "edu_level": {
                        "type": "string",
                        "enum": ["小学", "初中", "高中", ""],
                        "description": "学段校验（可选：小学/初中/高中；填写后会严格校验学段与学科匹配）",
                        "default": ""
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compose_paper_blueprint",
            "description": "根据“组卷蓝图”批量搜索并组装题目ID列表（支持年级/教材版本/选修过滤/去重/质量阈值/严学科约束）。返回分段选题结果与精简预览。",
            "parameters": {
                "type": "object",
                "properties": {
                    "blueprint": {
                        "type": "array",
                        "description": "组卷蓝图（多个检索槽位）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "keyword": {"type": "string", "description": "关键词（与 knowledge_point 二选一）", "default": ""},
                                "knowledge_point": {"type": "string", "description": "知识点（与 keyword 二选一）", "default": ""},
                                "count": {"type": "integer", "description": "本槽位需要的题目数量", "default": 1},
                                "difficulty": {"type": "string", "description": "难度（简单/中等/困难；可选）", "default": ""},
                                "question_type": {"type": "string", "description": "题型（可选）", "default": ""},
                                "source_contains": {"type": "string", "description": "来源包含（可选）", "default": ""},
                                "stem_contains": {"type": "string", "description": "题干包含（可选）", "default": ""},
                                "knowledge_contains": {"type": "string", "description": "知识点包含（可选）", "default": ""},
                                "max_pages": {"type": "integer", "description": "本槽位最多翻页数（可选，覆盖全局 max_pages）", "default": 0}
                            }
                        }
                    },
                    "subject": {"type": "string", "description": "学科全名（可选，不填则使用当前学科；填写会自动切换）", "default": ""},
                    "edu_level": {"type": "string", "enum": ["小学", "初中", "高中", ""], "description": "学段筛选（可选）", "default": ""},
                    "learn_grade": {"type": "string", "description": "年级名称（可选）", "default": ""},
                    "learn_grade_id": {"type": "integer", "description": "年级ID（可选，优先级高于 learn_grade）", "default": 0},
                    "textbook_version": {"type": "string", "description": "教材版本/题库分类（可选）", "default": ""},
                    "elective_mode": {"type": "string", "description": "选修过滤模式（include/exclude/only）", "default": ""},
                    "elective_keywords": {"type": "array", "items": {"type": "string"}, "description": "自定义选修识别关键词（可选）"},
                    "exclude_elective": {"type": "boolean", "description": "兼容旧参数：true 等价于 elective_mode=exclude（当 elective_mode 为空时）", "default": False},
                    "year": {"type": "integer", "description": "年份过滤（可选，0 表示不限）", "default": 0},
                    "province": {"type": "string", "description": "地区（可选，如：北京/北京市/全国；建议先通过 get_available_filters 获取 provinces；同时传 province_id 时以 province_id 为准）", "default": ""},
                    "province_id": {"type": "integer", "description": "地区ID（可选，-1 表示不限）", "default": -1},
                    "paper_type_id": {"type": "integer", "description": "试卷类型ID（可选，0 表示不限）", "default": 0},
                    "term": {"type": "integer", "description": "学期（可选，0 表示不限）", "default": 0},
                    "order_by": {"type": "integer", "description": "排序方式（可选，默认 2）", "default": 2},
                    "max_pages": {"type": "integer", "description": "全局最多翻页数（默认 2）", "default": 2},
                    "per_slot_expand": {"type": "integer", "description": "每个槽位扩展倍数（先多抓再筛选；默认 3）", "default": 3},
                    "min_quality_score": {"type": "integer", "description": "最小质量分（0-100；0 表示不过滤）", "default": 0},
                    "dedup_by_stem": {"type": "boolean", "description": "按题干去重（避免同质题）", "default": True},
                    "strict_subject": {"type": "boolean", "description": "严学科约束（防止跨学段混入）", "default": True}
                },
                "required": ["blueprint"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_paper",
            "description": "创建试卷。将选定的题目保存为一份试卷。",
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_name": {
                        "type": "string",
                        "description": "试卷名称"
                    },
                    "question_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "题目ID列表"
                    }
                },
                "required": ["paper_name", "question_ids"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_papers",
            "description": "获取已创建的试卷列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制，默认10",
                        "default": 10
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_question_detail",
            "description": "根据题目ID获取题目详情。用于逐一判断题目是否符合组卷需求。返回题目的完整信息包括题干、选项、答案、解析等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_id": {
                        "type": "string",
                        "description": "题目ID，如 '12345678'"
                    }
                },
                "required": ["question_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "batch_get_question_details",
            "description": "批量获取多个题目的详情。用于一次性获取多道题目进行筛选判断。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "题目ID列表，最多10个"
                    }
                },
                "required": ["question_ids"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "select_best_question",
            "description": "【子AI选题】从多个候选题目中智能选择最符合要求的一道。会调用子AI分析题目内容、难度、知识点，返回最佳选择和选择理由。每次选题都应该使用这个工具让子AI来决策。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "候选题目ID列表（2-5个）"
                    },
                    "requirement": {
                        "type": "string",
                        "description": "选题要求描述，如'需要一道考查函数单调性的中等难度选择题'"
                    }
                },
                "required": ["question_ids", "requirement"]
            }
        }
    }
]

PLAN_TAG_OPEN = "<EXAM_PAPER_PLAN>"
PLAN_TAG_CLOSE = "</EXAM_PAPER_PLAN>"


class ChatService:
    def __init__(self):
        self.crawler = None
        self.current_subject = "高中数学"
        self.question_cache = {}  # 缓存题目详情 {question_id: question_data}

    def _infer_provider_for_model(self, model: str) -> str:
        """
        Infer which OpenAI-compatible provider to call based on the model name.

        Heuristics:
        - Fireworks model IDs are published as `accounts/...` (e.g. `accounts/fireworks/models/...`).
          Fireworks `/models` may also include non-`accounts/fireworks/...` owners (e.g. `accounts/cogito/...`),
          but they are still resolved by the Fireworks API base URL.
        - OpenRouter model IDs are typically `<provider>/<model>` (e.g. `openai/gpt-4o-mini`, `anthropic/...`).
        - Otherwise, fall back to the backend default provider (CHAT_PROVIDER).

        Notes:
        - This enables switching to Fireworks models from the frontend even when the backend default is OpenRouter.
        """
        m = (model or "").strip()
        if m.startswith("accounts/"):
            return "fireworks"
        if "/" in m:
            return "openrouter"
        return CHAT_PROVIDER

    def _resolve_chat_endpoint(self, model: str) -> Dict[str, str]:
        """
        Resolve base URL + API key by provider (derived from model).

        Returns:
            dict: {provider, base_url, api_key}
        """
        provider = self._infer_provider_for_model(model)
        if provider == "fireworks":
            return {
                "provider": "fireworks",
                "base_url": (settings.fireworks_base_url or "").rstrip("/"),
                "api_key": (settings.fireworks_api_key or "").strip(),
            }
        return {
            "provider": "openrouter",
            "base_url": (settings.openrouter_base_url or "").rstrip("/"),
            "api_key": (settings.openrouter_api_key or "").strip(),
        }

    def _chat_headers(self, provider: str, api_key: str) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        # OpenRouter uses these headers for ranking / attribution (optional but recommended).
        if provider == "openrouter":
            headers["HTTP-Referer"] = "http://localhost:8000"
            headers["X-Title"] = "Exam Paper Assistant"
        return headers

    def _extract_plan_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        content = (text or "").strip()
        if not content:
            return None
        start = content.find(PLAN_TAG_OPEN)
        if start < 0:
            return None
        end = content.find(PLAN_TAG_CLOSE, start + len(PLAN_TAG_OPEN))
        if end < 0:
            return None
        payload = content[start + len(PLAN_TAG_OPEN) : end].strip()
        if not payload:
            return None

        # Be tolerant to models wrapping JSON in Markdown code fences:
        # <EXAM_PAPER_PLAN>```json {...}```</EXAM_PAPER_PLAN>
        payload_clean = payload.strip()
        if payload_clean.startswith("```"):
            payload_clean = re.sub(r"^```[a-zA-Z0-9_-]*", "", payload_clean).lstrip()
            payload_clean = re.sub(r"```$", "", payload_clean).rstrip()

        try:
            data = json.loads(payload_clean)
            return data if isinstance(data, dict) else None
        except Exception:
            # Last-resort: extract the first {...} JSON object from the payload.
            try:
                l = payload_clean.find("{")
                r = payload_clean.rfind("}")
                if l >= 0 and r > l:
                    data = json.loads(payload_clean[l : r + 1])
                    return data if isinstance(data, dict) else None
            except Exception:
                pass
            return None

    def _extract_last_plan_from_history(self, history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        for msg in reversed(history or []):
            if msg.get("role") != "assistant":
                continue
            plan = self._extract_plan_from_text(msg.get("content") or "")
            if plan is not None:
                return plan
        return None

    def _is_confirmation_message(self, user_message: str) -> bool:
        raw = user_message or ""
        normalized = re.sub(r"\s+", "", raw).strip().lower()
        if not normalized:
            return False
        return normalized in {
            "确认",
            "确认开始组卷",
            "开始组卷",
            "开始",
            "执行",
            "就按这个",
            "ok",
            "okay",
            "yes",
            "y",
            "好的",
            "可以",
        }

    def _tools_by_names(self, allowed_names: List[str]) -> List[Dict[str, Any]]:
        allowed = {n.strip() for n in (allowed_names or []) if (n or "").strip()}
        if not allowed:
            return []
        out: List[Dict[str, Any]] = []
        for tool in TOOLS:
            try:
                func = tool.get("function") or {}
                name = func.get("name")
                if name in allowed:
                    out.append(tool)
            except Exception:
                continue
        return out

    def _determine_tools_for_request(self, history: List[Dict[str, Any]], user_message: str) -> List[Dict[str, Any]]:
        """
        Two-phase gating:
        - Planning stage (default): only allow filter + search tools.
        - Execution stage (requires explicit confirmation AND a previously proposed plan): allow all tools.
        """
        plan = self._extract_last_plan_from_history(history)
        if plan is not None and self._is_confirmation_message(user_message):
            return TOOLS
        return self._tools_by_names(["get_available_filters", "search_questions"])

    async def _get_crawler(self, subject: str = None):
        """获取爬虫实例，支持学科切换"""
        subject = resolve_subject(subject or self.current_subject, strict=True)
        self.current_subject = subject
        if self.crawler is None:
            self.crawler = ZujuanCrawler(subject=subject)
            await self.crawler.initialize()
        elif self.crawler.subject != subject:
            # 切换学科
            self.crawler.set_subject(subject)
        return self.crawler

    def _lookup_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Find the JSON schema (parameters) for a given tool name."""
        name = (tool_name or "").strip()
        if not name:
            return None
        for tool in TOOLS:
            try:
                func = tool.get("function") or {}
                if func.get("name") == name:
                    params = func.get("parameters")
                    return params if isinstance(params, dict) else None
            except Exception:
                continue
        return None

    def _coerce_tool_args(self, tool_name: str, arguments: Any) -> Dict[str, Any]:
        """
        Coerce tool-call arguments to match the tool JSON schema.

        Some providers/models occasionally emit numeric/boolean fields as strings
        (e.g. "limit": "10", "exclude_elective": "false"), which can crash tool code.
        """
        if not isinstance(arguments, dict):
            return {}
        schema = self._lookup_tool_schema(tool_name)
        if not schema:
            return arguments
        coerced = self._coerce_with_schema(schema, arguments)
        return coerced if isinstance(coerced, dict) else arguments

    def _coerce_with_schema(self, schema: Any, value: Any) -> Any:
        if not isinstance(schema, dict):
            return value

        schema_type = schema.get("type")

        if schema_type == "object":
            if isinstance(value, str):
                s = value.strip()
                if s.startswith("{") or s.startswith("["):
                    try:
                        value = json.loads(s)
                    except Exception:
                        pass
            if not isinstance(value, dict):
                return value
            props = schema.get("properties") or {}
            if not isinstance(props, dict):
                return value
            out = dict(value)
            for key, prop_schema in props.items():
                if key in value:
                    out[key] = self._coerce_with_schema(prop_schema, value.get(key))
            return out

        if schema_type == "array":
            if isinstance(value, str):
                s = value.strip()
                if s.startswith("[") or s.startswith("{"):
                    try:
                        value = json.loads(s)
                    except Exception:
                        pass
            if not isinstance(value, list):
                return value
            item_schema = schema.get("items") or {}
            return [self._coerce_with_schema(item_schema, v) for v in value]

        if schema_type == "integer":
            return self._coerce_int(value)

        if schema_type == "number":
            return self._coerce_number(value)

        if schema_type == "boolean":
            return self._coerce_bool(value)

        return value

    def _coerce_int(self, value: Any) -> Any:
        try:
            if value is None:
                return value
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value) if value.is_integer() else value
            if isinstance(value, str):
                s = value.strip()
                if not s:
                    return value
                try:
                    return int(s)
                except Exception:
                    try:
                        f = float(s)
                        return int(f) if f.is_integer() else value
                    except Exception:
                        return value
            return value
        except Exception:
            return value

    def _coerce_number(self, value: Any) -> Any:
        try:
            if value is None:
                return value
            if isinstance(value, bool):
                return float(int(value))
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                s = value.strip()
                if not s:
                    return value
                try:
                    return float(s)
                except Exception:
                    return value
            return value
        except Exception:
            return value

    def _coerce_bool(self, value: Any) -> Any:
        try:
            if value is None:
                return value
            if isinstance(value, bool):
                return value
            if isinstance(value, int):
                return bool(value)
            if isinstance(value, float):
                return bool(int(value))
            if isinstance(value, str):
                s = value.strip().lower()
                if s in {"true", "1", "yes", "y", "on"}:
                    return True
                if s in {"false", "0", "no", "n", "off", ""}:
                    return False
                return value
            return value
        except Exception:
            return value

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], *, sub_model: Optional[str] = None
    ) -> Dict[str, Any]:
        """执行工具调用"""
        try:
            arguments = self._coerce_tool_args(tool_name, arguments)

            def _as_int(value: Any, default: int) -> int:
                try:
                    if value is None:
                        return default
                    if isinstance(value, bool):
                        return default
                    if isinstance(value, int):
                        return value
                    s = str(value).strip()
                    if not s:
                        return default
                    return int(s)
                except Exception:
                    return default

            def _as_float(value: Any) -> Optional[float]:
                try:
                    if value is None:
                        return None
                    if isinstance(value, bool):
                        return None
                    if isinstance(value, (int, float)):
                        return float(value)
                    s = str(value).strip()
                    if not s:
                        return None
                    return float(s)
                except Exception:
                    return None

            if tool_name == "search_questions":
                crawler = await self._get_crawler()
                edu_level = (arguments.get("edu_level") or "").strip()
                difficulty = normalize_difficulty(
                    arguments.get("difficulty") or DEFAULT_DIFFICULTY,
                    strict=True,
                )
                learn_grade_id = _as_int(arguments.get("learn_grade_id", 0), 0)
                limit = _as_int(arguments.get("limit", 10), 10)
                max_pages = _as_int(arguments.get("max_pages", 2), 2)
                year = _as_int(arguments.get("year", 0), 0)
                province_id = _as_int(arguments.get("province_id", -1), -1)
                paper_type_id = _as_int(arguments.get("paper_type_id", 0), 0)
                term = _as_int(arguments.get("term", 0), 0)
                order_by = _as_int(arguments.get("order_by", 2), 2)
                min_quality_score = _as_int(arguments.get("min_quality_score", 0), 0)
                difficulty_value_min = _as_float(arguments.get("difficulty_value_min"))
                difficulty_value_max = _as_float(arguments.get("difficulty_value_max"))
                result = await crawler.search_by_keyword(
                    keyword=arguments.get("keyword", ""),
                    edu_level=edu_level,
                    difficulty=difficulty,
                    question_type=arguments.get("question_type", ""),
                    learn_grade=arguments.get("learn_grade", ""),
                    learn_grade_id=learn_grade_id,
                    textbook_version=arguments.get("textbook_version", ""),
                    limit=limit,
                    max_pages=max_pages,
                    year=year,
                    province=arguments.get("province", ""),
                    province_id=province_id,
                    paper_type_id=paper_type_id,
                    term=term,
                    order_by=order_by,
                    source_contains=arguments.get("source_contains", ""),
                    stem_contains=arguments.get("stem_contains", ""),
                    knowledge_contains=arguments.get("knowledge_contains", ""),
                    elective_mode=arguments.get("elective_mode", ""),
                    elective_keywords=arguments.get("elective_keywords"),
                    exclude_elective=arguments.get("exclude_elective", False),
                    dedup_by_stem=arguments.get("dedup_by_stem", False),
                    min_quality_score=min_quality_score,
                    difficulty_value_min=difficulty_value_min,
                    difficulty_value_max=difficulty_value_max,
                    require_difficulty=True,
                    strict_subject=True,
                )
                if edu_level:
                    result["applied_edu_level"] = edu_level
                return result

            elif tool_name == "get_available_filters":
                edu_level = (arguments.get("edu_level") or "").strip()
                subject_input = (arguments.get("subject") or self.current_subject).strip()
                try:
                    subject = resolve_subject(subject_input, edu_level=edu_level, strict=True)
                except ValueError as exc:
                    return {
                        "success": False,
                        "error": str(exc),
                        "current_subject": self.current_subject,
                        "allowed_edu_levels": ["小学", "初中", "高中"],
                    }

                crawler = await self._get_crawler(subject)
                result = await crawler.get_available_filters()
                result["current_subject"] = subject
                if edu_level:
                    result["applied_edu_level"] = edu_level
                return result

            elif tool_name == "compose_paper_blueprint":
                edu_level = (arguments.get("edu_level") or "").strip()
                subject_input = (arguments.get("subject") or self.current_subject).strip()
                try:
                    subject = resolve_subject(subject_input, edu_level=edu_level, strict=True)
                except ValueError as exc:
                    return {
                        "success": False,
                        "error": str(exc),
                        "current_subject": self.current_subject,
                        "allowed_edu_levels": ["小学", "初中", "高中"],
                    }

                learn_grade_id = _as_int(arguments.get("learn_grade_id", 0), 0)
                year = _as_int(arguments.get("year", 0), 0)
                province_id = _as_int(arguments.get("province_id", -1), -1)
                paper_type_id = _as_int(arguments.get("paper_type_id", 0), 0)
                term = _as_int(arguments.get("term", 0), 0)
                order_by = _as_int(arguments.get("order_by", 2), 2)
                max_pages = _as_int(arguments.get("max_pages", 2), 2)
                per_slot_expand = _as_int(arguments.get("per_slot_expand", 3), 3)
                min_quality_score = _as_int(arguments.get("min_quality_score", 0), 0)

                crawler = await self._get_crawler(subject)
                result = await crawler.compose_paper_blueprint(
                    blueprint=arguments.get("blueprint") or [],
                    subject=subject,
                    edu_level=edu_level,
                    learn_grade=arguments.get("learn_grade", ""),
                    learn_grade_id=learn_grade_id,
                    textbook_version=arguments.get("textbook_version", ""),
                    elective_mode=arguments.get("elective_mode", ""),
                    elective_keywords=arguments.get("elective_keywords"),
                    exclude_elective=arguments.get("exclude_elective", False),
                    year=year,
                    province=arguments.get("province", ""),
                    province_id=province_id,
                    paper_type_id=paper_type_id,
                    term=term,
                    order_by=order_by,
                    max_pages=max_pages,
                    per_slot_expand=per_slot_expand,
                    min_quality_score=min_quality_score,
                    dedup_by_stem=arguments.get("dedup_by_stem", True),
                    strict_subject=arguments.get("strict_subject", True),
                )
                result["current_subject"] = subject
                if edu_level:
                    result["applied_edu_level"] = edu_level
                return result

            elif tool_name == "create_paper":
                from backend.database.models import save_paper
                questions = [{"question_id": qid} for qid in arguments.get("question_ids", [])]
                paper_id = await save_paper(
                    paper_name=arguments.get("paper_name", "未命名试卷"),
                    questions=questions
                )
                return {
                    "success": True,
                    "paper_id": paper_id,
                    "message": f"试卷创建成功，ID: {paper_id}"
                }

            elif tool_name == "get_papers":
                from backend.database.models import list_papers
                papers = await list_papers(limit=arguments.get("limit", 10))
                return {
                    "success": True,
                    "papers": papers,
                    "count": len(papers)
                }

            elif tool_name == "get_question_detail":
                crawler = await self._get_crawler()
                result = await crawler.get_question_detail(
                    question_id=arguments.get("question_id", "")
                )
                return result

            elif tool_name == "batch_get_question_details":
                crawler = await self._get_crawler()
                result = await crawler.batch_get_question_details(
                    question_ids=arguments.get("question_ids", [])
                )
                # 缓存获取到的题目详情
                for q in result.get("questions", []):
                    qid = q.get("question_id")
                    if qid:
                        self.question_cache[qid] = q
                return result

            elif tool_name == "select_best_question":
                # 子AI选题功能
                from backend.mcp.sub_ai_selector import select_best_question as sub_ai_select

                question_ids = arguments.get("question_ids", [])[:5]
                requirement = arguments.get("requirement", "")

                # 优先从缓存获取题目详情
                questions = []
                missing_ids = []
                for qid in question_ids:
                    if qid in self.question_cache:
                        questions.append(self.question_cache[qid])
                    else:
                        missing_ids.append(qid)

                # 如果有缺失的题目，再去获取
                if missing_ids:
                    crawler = await self._get_crawler()
                    details_result = await crawler.batch_get_question_details(missing_ids)
                    for q in details_result.get("questions", []):
                        qid = q.get("question_id")
                        if qid:
                            self.question_cache[qid] = q
                            questions.append(q)

                if not questions:
                    return {"success": False, "error": "无法获取候选题目详情"}

                # 调用子AI选择最佳题目（传递完整题目信息，包括题干）
                result = await sub_ai_select(questions=questions, requirement=requirement, model=sub_model)

                # 添加说明信息
                if result.get("success"):
                    result["message"] = f"子AI已从{len(questions)}道候选题目中选择了最符合要求的题目"

                return result

            else:
                return {"success": False, "error": f"未知工具: {tool_name}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _generate_fallback_response(self, tool_results: List[Dict]) -> str:
        """当API返回空内容时，根据工具结果生成回复"""
        if not tool_results:
            return "操作已完成。"

        responses = []
        for tr in tool_results:
            try:
                result = json.loads(tr.get("content", "{}"))
                tool_id = tr.get("tool_call_id", "")

                # search_questions 结果
                if "questions" in result:
                    questions = result.get("questions", [])
                    total = result.get("total", len(questions))
                    if questions:
                        responses.append(f"搜索到 {total} 道题目，已展示 {len(questions)} 道。")
                    else:
                        responses.append("未找到符合条件的题目，请尝试其他关键词。")

                # get_question_detail 结果
                elif "stem" in result:
                    responses.append("已获取题目详情。")

                # batch_get_question_details 结果
                elif "questions" in result and "count" in result:
                    count = result.get("count", 0)
                    responses.append(f"已获取 {count} 道题目的详情。")

                # create_paper 结果
                elif "paper_id" in result:
                    paper_id = result.get("paper_id")
                    responses.append(f"试卷创建成功！试卷ID: {paper_id}")

                # get_papers 结果
                elif "papers" in result:
                    count = result.get("count", 0)
                    responses.append(f"找到 {count} 份已保存的试卷。")

                # 错误情况
                elif result.get("success") == False:
                    error = result.get("error", "未知错误")
                    responses.append(f"操作失败: {error}")

            except json.JSONDecodeError:
                pass

        if responses:
            return "\n\n".join(responses) + "\n\n请查看上方的详细结果。如需继续操作，请告诉我。"
        else:
            return "操作已完成，请查看上方的工具执行结果。"

    def _build_messages(self, history: List[Dict], user_message: str, subject: str = "高中数学") -> List[Dict]:
        """构建消息列表"""
        system_prompt = get_system_prompt(subject)
        messages = [{"role": "system", "content": system_prompt}]

        # 添加历史消息
        for msg in history:
            if msg["role"] == "user":
                messages.append({"role": "user", "content": msg["content"]})
            elif msg["role"] == "assistant":
                msg_data = {"role": "assistant", "content": msg["content"]}
                if msg.get("tool_calls"):
                    msg_data["tool_calls"] = msg["tool_calls"]
                messages.append(msg_data)
            elif msg["role"] == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", ""),
                    "content": msg["content"]
                })

        # 添加当前用户消息
        messages.append({"role": "user", "content": user_message})
        return messages

    async def _call_api(
        self,
        client: httpx.AsyncClient,
        messages: List[Dict],
        *,
        model: Optional[str] = None,
        include_tools: bool = True,
        tools_override: Optional[List[Dict[str, Any]]] = None,
        max_retries: int = 3,
    ) -> Dict:
        """调用对话 API（OpenAI-compatible），带重试机制"""
        last_error = None
        effective_model = (model or MAIN_MODEL).strip() or MAIN_MODEL
        endpoint = self._resolve_chat_endpoint(effective_model)
        base_url = endpoint["base_url"]
        provider = endpoint["provider"]
        api_key = endpoint["api_key"]
        if not api_key:
            return {"success": False, "error": f"未配置 {provider} API Key（当前模型: {effective_model}）"}

        for attempt in range(max_retries):
            try:
                payload = {
                    "model": effective_model,
                    "messages": messages,
                    "max_tokens": MAIN_MODEL_MAX_TOKENS,
                    "temperature": MAIN_MODEL_TEMPERATURE
                }
                if include_tools:
                    payload["tools"] = tools_override if tools_override is not None else TOOLS
                    payload["tool_choice"] = "auto"

                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers=self._chat_headers(provider, api_key),
                    json=payload
                )

                if response.status_code == 200:
                    return {"success": True, "data": response.json()}
                else:
                    detail = ""
                    try:
                        data = response.json()
                        if isinstance(data, dict):
                            err = data.get("error")
                            if isinstance(err, dict) and isinstance(err.get("message"), str):
                                detail = err["message"]
                            elif isinstance(data.get("message"), str):
                                detail = data["message"]
                    except Exception:
                        detail = (response.text or "").strip()

                    detail = (detail or "").strip().replace("\n", " ")
                    if detail:
                        last_error = (
                            f"API错误: {response.status_code} - {detail[:240]} "
                            f"(provider={provider}, model={effective_model})"
                        )
                    else:
                        last_error = f"API错误: {response.status_code} (provider={provider}, model={effective_model})"
            except httpx.ConnectError as e:
                last_error = f"连接失败: {str(e)}"
            except httpx.RemoteProtocolError as e:
                last_error = f"协议错误: {str(e)}"
            except Exception as e:
                last_error = f"请求错误: {str(e)}"

            # 等待后重试
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))

        return {"success": False, "error": last_error}

    async def _call_api_streaming(
        self, client: httpx.AsyncClient, messages: List[Dict], *, model: Optional[str] = None
    ):
        """流式调用对话 API（OpenAI-compatible），用于最终文本回复"""
        effective_model = (model or MAIN_MODEL).strip() or MAIN_MODEL
        endpoint = self._resolve_chat_endpoint(effective_model)
        base_url = endpoint["base_url"]
        provider = endpoint["provider"]
        api_key = endpoint["api_key"]
        if not api_key:
            yield {"type": "error", "content": f"未配置 {provider} API Key（当前模型: {effective_model}）"}
            return

        payload = {
            "model": effective_model,
            "messages": messages,
            "max_tokens": MAIN_MODEL_MAX_TOKENS,
            "temperature": MAIN_MODEL_TEMPERATURE,
            "stream": True
        }

        try:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                headers=self._chat_headers(provider, api_key),
                json=payload
            ) as response:
                if response.status_code != 200:
                    detail = ""
                    try:
                        raw = await response.aread()
                        text = raw.decode("utf-8", errors="ignore")
                        try:
                            data = json.loads(text)
                            if isinstance(data, dict):
                                err = data.get("error")
                                if isinstance(err, dict) and isinstance(err.get("message"), str):
                                    detail = err["message"]
                                elif isinstance(data.get("message"), str):
                                    detail = data["message"]
                        except Exception:
                            detail = text
                    except Exception:
                        detail = ""

                    detail = (detail or "").strip().replace("\n", " ")
                    if detail:
                        yield {
                            "type": "error",
                            "content": (
                                f"API错误: {response.status_code} - {detail[:240]} "
                                f"(provider={provider}, model={effective_model})"
                            ),
                        }
                    else:
                        yield {
                            "type": "error",
                            "content": f"API错误: {response.status_code} (provider={provider}, model={effective_model})",
                        }
                    return

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield {"type": "text_delta", "content": content}
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            yield {"type": "error", "content": f"流式请求错误: {str(e)}"}

    async def chat(
        self,
        history: List[Dict],
        user_message: str,
        subject: str = "高中数学",
        *,
        model: Optional[str] = None,
        sub_model: Optional[str] = None,
    ) -> AsyncGenerator[Dict, None]:
        """
        处理对话，支持多轮工具调用
        AI可以连续调用多个工具直到完成任务
        返回生成器，逐步返回响应
        """
        # 更新当前学科
        self.current_subject = subject

        main_model = (model or MAIN_MODEL).strip() or MAIN_MODEL
        sub_model_effective = (sub_model or "").strip() or None
        endpoint = self._resolve_chat_endpoint(main_model)
        if not endpoint["api_key"]:
            provider = endpoint["provider"]
            yield {"type": "error", "content": f"未配置 {provider} API Key（当前模型: {main_model}）"}
            return

        messages = self._build_messages(history, user_message, subject=subject)
        iteration = 0
        all_tool_results = []  # 收集所有工具结果用于fallback
        tools_override = self._determine_tools_for_request(history, user_message)

        async with httpx.AsyncClient(timeout=httpx.Timeout(API_TIMEOUT, connect=30.0)) as client:
            while iteration < MAX_TOOL_ITERATIONS:
                iteration += 1

                # 通知前端当前是第几轮
                if iteration > 1:
                    yield {
                        "type": "iteration",
                        "round": iteration,
                        "message": f"AI 正在进行第 {iteration} 轮操作..."
                    }

                # 调用API（始终包含工具，让AI自主决定是否使用）
                result = await self._call_api(
                    client,
                    messages,
                    model=main_model,
                    include_tools=True,
                    tools_override=tools_override,
                )

                if not result["success"]:
                    yield {
                        "type": "error",
                        "content": result["error"]
                    }
                    return

                data = result["data"]
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                finish_reason = choice.get("finish_reason", "")

                # 检查是否有工具调用
                tool_calls = message.get("tool_calls")

                if tool_calls:
                    # 限制每轮最多执行3个工具调用
                    if len(tool_calls) > 3:
                        tool_calls = tool_calls[:3]
                    
                    # 返回助手消息（包含工具调用意图）
                    assistant_content = message.get("content") or ""
                    if not assistant_content.strip():
                        tool_names: List[str] = []
                        for tc in tool_calls:
                            try:
                                tool_names.append(tc.get("function", {}).get("name", ""))
                            except Exception:
                                tool_names.append("")
                        tool_names = [n for n in tool_names if n]
                        if tool_names:
                            assistant_content = f"（第 {iteration} 轮：调用工具 {', '.join(tool_names)}）"
                        else:
                            assistant_content = f"（第 {iteration} 轮：调用工具）"
                    yield {
                        "type": "assistant",
                        "content": assistant_content,
                        "tool_calls": tool_calls,
                        "iteration": iteration
                    }

                    # 执行每个工具调用（最多3个）
                    tool_results = []
                    for tool_call in tool_calls:
                        tool_name = tool_call["function"]["name"]
                        try:
                            tool_args = json.loads(tool_call["function"]["arguments"])
                        except json.JSONDecodeError:
                            tool_args = {}
                        tool_args = self._coerce_tool_args(tool_name, tool_args)
                        tool_id = tool_call["id"]

                        # 通知前端工具开始执行
                        yield {
                            "type": "tool_start",
                            "tool_call_id": tool_id,
                            "tool_name": tool_name,
                            "arguments": tool_args,
                            "iteration": iteration
                        }

                        # 执行工具
                        tool_result = await self.execute_tool(tool_name, tool_args, sub_model=sub_model_effective)

                        # 通知前端工具执行完成
                        yield {
                            "type": "tool_result",
                            "tool_call_id": tool_id,
                            "tool_name": tool_name,
                            "result": tool_result,
                            "iteration": iteration
                        }

                        tool_result_msg = {
                            "tool_call_id": tool_id,
                            "role": "tool",
                            "content": json.dumps(tool_result, ensure_ascii=False)
                        }
                        tool_results.append(tool_result_msg)
                        all_tool_results.append(tool_result_msg)

                    # 将助手消息和工具结果添加到消息列表，继续下一轮
                    messages.append(message)
                    messages.extend(tool_results)

                    # 继续循环，让AI决定下一步
                    continue

                else:
                    # 没有工具调用，AI已完成任务
                    # 如果之前有工具调用，使用流式输出最终回复
                    if all_tool_results:
                        # 通知前端开始流式输出
                        yield {
                            "type": "stream_start",
                            "iteration": iteration
                        }

                        # 使用流式API获取最终回复
                        final_content = ""
                        async for chunk in self._call_api_streaming(client, messages, model=main_model):
                            if chunk["type"] == "text_delta":
                                final_content += chunk["content"]
                                yield chunk
                            elif chunk["type"] == "error":
                                yield chunk
                                return

                        # 如果流式输出为空，使用fallback
                        if not final_content:
                            final_content = self._generate_fallback_response(all_tool_results)
                            yield {"type": "text_delta", "content": final_content}

                        yield {
                            "type": "assistant_final",
                            "content": final_content,
                            "total_iterations": iteration
                        }
                    else:
                        # 没有工具调用，直接返回（简单对话场景）
                        final_content = message.get("content", "")

                        # 也使用流式输出
                        if final_content:
                            yield {"type": "stream_start", "iteration": iteration}
                            # 模拟流式输出（分段发送）
                            chunk_size = 10
                            for i in range(0, len(final_content), chunk_size):
                                yield {"type": "text_delta", "content": final_content[i:i+chunk_size]}
                                await asyncio.sleep(0.02)  # 小延迟模拟打字效果
                            yield {
                                "type": "assistant_final",
                                "content": final_content,
                                "total_iterations": iteration
                            }
                        else:
                            yield {
                                "type": "assistant_final",
                                "content": "",
                                "total_iterations": iteration
                            }
                    return

            # 达到最大轮数限制
            yield {
                "type": "assistant_final",
                "content": f"已完成 {MAX_TOOL_ITERATIONS} 轮操作。" + self._generate_fallback_response(all_tool_results),
                "total_iterations": iteration,
                "max_reached": True
            }


# 单例
chat_service = ChatService()
