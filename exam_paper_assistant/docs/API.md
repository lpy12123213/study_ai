# API文档

## 基础信息

- 基础URL: `http://localhost:8000`
- 内容类型: `application/json`

## 端点列表

### 健康检查

**GET** `/api/health`

返回服务健康状态

**响应示例：**
```json
{
  "status": "healthy",
  "service": "exam-paper-assistant"
}
```

---

### 创建试卷

**POST** `/api/papers`

创建新试卷并保存题目编号

**请求体：**
```json
{
  "paper_name": "高一数学期末试卷",
  "question_ids": ["12345", "12346", "12347"]
}
```

**响应示例：**
```json
{
  "success": true,
  "paper_id": 1,
  "message": "试卷 '高一数学期末试卷' 创建成功"
}
```

---

### 获取试卷详情

**GET** `/api/papers/{paper_id}`

获取指定试卷的详细信息

**路径参数：**
- `paper_id` (integer): 试卷ID

**响应示例：**
```json
{
  "paper_id": 1,
  "paper_name": "高一数学期末试卷",
  "created_at": "2025-01-15T10:30:00",
  "questions": [
    {
      "question_id": "12345",
      "order": 1,
      "type": "选择题",
      "difficulty": "中等",
      "knowledge_point": "函数",
      "source_url": "https://zujuan.xkw.com/q/12345"
    }
  ]
}
```

---

### 获取试卷列表

**GET** `/api/papers`

获取所有试卷列表

**查询参数：**
- `limit` (integer, 可选): 返回数量限制，默认50

**响应示例：**
```json
[
  {
    "paper_id": 1,
    "paper_name": "高一数学期末试卷",
    "created_at": "2025-01-15T10:30:00",
    "question_count": 15
  }
]
```

---

### 删除试卷

**DELETE** `/api/papers/{paper_id}`

删除指定试卷

**路径参数：**
- `paper_id` (integer): 试卷ID

**响应示例：**
```json
{
  "success": true,
  "message": "试卷删除成功"
}
```

---

### 获取下载链接

**GET** `/api/papers/{paper_id}/download-link`

生成组卷网题目查看链接

**路径参数：**
- `paper_id` (integer): 试卷ID

**响应示例：**
```json
{
  "success": true,
  "paper_name": "高一数学期末试卷",
  "question_count": 15,
  "question_ids": ["12345", "12346"],
  "question_links": [
    "https://zujuan.xkw.com/q/12345",
    "https://zujuan.xkw.com/q/12346"
  ],
  "instructions": [
    "1. 点击下方链接访问组卷网查看题目",
    "2. 在组卷网网站上登录您的账号",
    "3. 将喜欢的题目加入组卷网的题库",
    "4. 使用组卷网的正规下载功能下载试卷"
  ]
}
```

---

### 记录搜索历史

**POST** `/api/search-history`

记录题目搜索历史

**请求体：**
```json
{
  "search_type": "keyword",
  "search_query": "函数",
  "result_count": 20
}
```

**响应示例：**
```json
{
  "success": true,
  "message": "搜索历史已记录"
}
```

---

## MCP工具API

以下工具通过MCP协议提供给AI使用：

### search_questions_by_keyword

通过关键词搜索题目

**参数：**
- `keyword` (string, 必需): 搜索关键词
- `subject` (string, 可选): 学科
- `limit` (integer, 可选): 结果数量限制，默认20

**返回：**
```json
{
  "success": true,
  "keyword": "函数",
  "count": 20,
  "questions": [
    {
      "question_id": "12345",
      "question_type": "选择题",
      "difficulty": "中等",
      "knowledge_point": "函数的性质",
      "source_url": "https://zujuan.xkw.com/q/12345"
    }
  ]
}
```

---

### search_questions_by_knowledge

通过知识点搜索题目

**参数：**
- `knowledge_point` (string, 必需): 知识点名称
- `subject` (string, 必需): 学科
- `limit` (integer, 可选): 结果数量限制，默认20

**返回：**
```json
{
  "success": true,
  "knowledge_point": "三角函数",
  "subject": "数学",
  "count": 20,
  "questions": [...]
}
```

---

### filter_questions

根据条件筛选题目

**参数：**
- `question_ids` (array, 必需): 题目编号列表
- `difficulty` (string, 可选): 难度（简单/中等/困难）
- `question_type` (string, 可选): 题型
- `limit` (integer, 可选): 结果数量限制，默认10

**返回：**
```json
{
  "success": true,
  "count": 10,
  "questions": [...]
}
```

---

### get_question_info

获取题目元数据信息

**参数：**
- `question_id` (string, 必需): 题目编号

**返回：**
```json
{
  "success": true,
  "question_id": "12345",
  "question_type": "选择题",
  "difficulty": "中等",
  "knowledge_points": "函数的性质",
  "year": "2024",
  "source": "某某市期末考试",
  "url": "https://zujuan.xkw.com/q/12345"
}
```

---

### create_paper

创建试卷

**参数：**
- `paper_name` (string, 必需): 试卷名称
- `question_ids` (array, 必需): 题目编号列表

**返回：**
```json
{
  "success": true,
  "paper_id": 1,
  "message": "试卷 '高一数学期末试卷' 创建成功"
}
```

---

## 错误响应

所有API端点在出错时返回统一格式：

```json
{
  "detail": "错误描述信息"
}
```

常见HTTP状态码：
- `200` - 成功
- `400` - 请求参数错误
- `404` - 资源不存在
- `500` - 服务器内部错误

## 使用示例

### Python

```python
import httpx

# 创建试卷
async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:8000/api/papers",
        json={
            "paper_name": "测试试卷",
            "question_ids": ["12345", "12346"]
        }
    )
    print(response.json())
```

### JavaScript

```javascript
// 获取试卷列表
fetch('http://localhost:8000/api/papers')
  .then(response => response.json())
  .then(data => console.log(data));
```

### curl

```bash
# 创建试卷
curl -X POST http://localhost:8000/api/papers \
  -H "Content-Type: application/json" \
  -d '{"paper_name":"测试试卷","question_ids":["12345","12346"]}'
```
