"""
学科配置 - 组卷网学科ID映射
"""
from typing import Dict, List, Any

# 学段定义
EDU_LEVELS = {
    "小学": 1,
    "初中": 2,
    "高中": 3,
    "中职": 4,
}

# 学科配置：包含 bankId 和默认知识点分类ID
SUBJECTS: Dict[str, Dict[str, Any]] = {
    # 小学
    "小学语文": {"bank_id": 24, "edu_id": 1, "category_id": "100987", "short_name": "语文"},
    "小学数学": {"bank_id": 23, "edu_id": 1, "category_id": "100875", "short_name": "数学"},
    "小学英语": {"bank_id": 25, "edu_id": 1, "category_id": "101088", "short_name": "英语"},
    "小学道德与法治": {"bank_id": 31, "edu_id": 1, "category_id": "101190", "short_name": "道法"},
    "小学科学": {"bank_id": 32, "edu_id": 1, "category_id": "101295", "short_name": "科学"},

    # 初中
    "初中语文": {"bank_id": 1, "edu_id": 2, "category_id": "100001", "short_name": "语文"},
    "初中数学": {"bank_id": 2, "edu_id": 2, "category_id": "100109", "short_name": "数学"},
    "初中英语": {"bank_id": 3, "edu_id": 2, "category_id": "100253", "short_name": "英语"},
    "初中物理": {"bank_id": 4, "edu_id": 2, "category_id": "100371", "short_name": "物理"},
    "初中化学": {"bank_id": 5, "edu_id": 2, "category_id": "100409", "short_name": "化学"},
    "初中生物": {"bank_id": 6, "edu_id": 2, "category_id": "100443", "short_name": "生物"},
    "初中道德与法治": {"bank_id": 7, "edu_id": 2, "category_id": "100499", "short_name": "道法"},
    "初中历史": {"bank_id": 8, "edu_id": 2, "category_id": "100540", "short_name": "历史"},
    "初中地理": {"bank_id": 9, "edu_id": 2, "category_id": "100593", "short_name": "地理"},
    "初中科学": {"bank_id": 26, "edu_id": 2, "category_id": "101400", "short_name": "科学"},

    # 高中
    "高中语文": {"bank_id": 10, "edu_id": 3, "category_id": "100621", "short_name": "语文"},
    "高中数学": {"bank_id": 11, "edu_id": 3, "category_id": "100693", "short_name": "数学"},
    "高中英语": {"bank_id": 12, "edu_id": 3, "category_id": "100770", "short_name": "英语"},
    "高中物理": {"bank_id": 13, "edu_id": 3, "category_id": "100823", "short_name": "物理"},
    "高中化学": {"bank_id": 14, "edu_id": 3, "category_id": "100855", "short_name": "化学"},
    "高中生物": {"bank_id": 15, "edu_id": 3, "category_id": "100886", "short_name": "生物"},
    "高中政治": {"bank_id": 16, "edu_id": 3, "category_id": "100916", "short_name": "政治"},
    "高中历史": {"bank_id": 17, "edu_id": 3, "category_id": "100948", "short_name": "历史"},
    "高中地理": {"bank_id": 18, "edu_id": 3, "category_id": "100977", "short_name": "地理"},
    "高中日语": {"bank_id": 33, "edu_id": 3, "category_id": "101500", "short_name": "日语"},
    "高中信息技术": {"bank_id": 27, "edu_id": 3, "category_id": "101450", "short_name": "信息"},
}

# 常用学科列表（用于前端显示）
COMMON_SUBJECTS = [
    "高中数学", "高中语文", "高中英语", "高中物理", "高中化学", "高中生物",
    "高中政治", "高中历史", "高中地理",
    "初中数学", "初中语文", "初中英语", "初中物理", "初中化学", "初中生物",
    "初中道德与法治", "初中历史", "初中地理",
    "小学数学", "小学语文", "小学英语",
]

# 难度配置（统一为三档）
DEFAULT_DIFFICULTY = "中等"
DIFFICULTY_LEVELS = {"简单", "中等", "困难"}
DIFFICULTY_ALIASES = {
    "容易": "简单",
    "较易": "简单",
    "一般": "中等",
    "适中": "中等",
    "较难": "困难",
    "难": "困难",
}


def normalize_difficulty(difficulty: str, strict: bool = True) -> str:
    """将难度归一到 简单/中等/困难（严格模式下会拒绝未知值）"""
    d = (difficulty or "").strip()
    if not d:
        if strict:
            raise ValueError("difficulty_required")
        return ""
    if d in DIFFICULTY_LEVELS:
        return d
    if d in DIFFICULTY_ALIASES:
        return DIFFICULTY_ALIASES[d]
    # 兼容常见描述
    if "难" in d:
        return "困难"
    if "中" in d or "适" in d or "一" in d:
        return "中等"
    if "易" in d or "简" in d:
        return "简单"
    if strict:
        raise ValueError("invalid_difficulty")
    return d


def resolve_subject(subject_name: str, edu_level: str = "", strict: bool = True) -> str:
    """解析学科名称，并可选强校验学段"""
    name = (subject_name or "").strip()
    if not name:
        raise ValueError("subject_required")

    if name in SUBJECTS:
        resolved = name
    elif not strict:
        resolved = ""
        for key in SUBJECTS:
            if name in key or key in name:
                resolved = key
                break
        if not resolved:
            raise ValueError("subject_not_found")
    else:
        raise ValueError("subject_not_found")

    if edu_level:
        edu_id = EDU_LEVELS.get(edu_level)
        if not edu_id:
            raise ValueError("invalid_edu_level")
        if SUBJECTS[resolved]["edu_id"] != edu_id:
            raise ValueError("subject_edu_mismatch")

    return resolved

def get_subject_config(subject_name: str) -> Dict[str, Any]:
    """获取学科配置"""
    return SUBJECTS.get(subject_name, SUBJECTS["高中数学"])

def get_all_subjects() -> List[Dict[str, Any]]:
    """获取所有学科列表（用于前端选择器）"""
    result = []
    for name in COMMON_SUBJECTS:
        if name in SUBJECTS:
            config = SUBJECTS[name]
            result.append({
                "name": name,
                "short_name": config["short_name"],
                "bank_id": config["bank_id"],
                "edu_id": config["edu_id"],
            })
    return result

def get_subjects_by_edu(edu_name: str) -> List[Dict[str, Any]]:
    """按学段获取学科"""
    edu_id = EDU_LEVELS.get(edu_name)
    if not edu_id:
        return []

    result = []
    for name, config in SUBJECTS.items():
        if config["edu_id"] == edu_id:
            result.append({
                "name": name,
                "short_name": config["short_name"],
                "bank_id": config["bank_id"],
            })
    return result
