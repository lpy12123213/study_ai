"""
学科配置 - 组卷网学科ID映射

该模块作为兼容层保留，实际配置定义移动到 `core.subjects`。
"""

from core.subjects import (  # noqa: F401
    COMMON_SUBJECTS,
    DEFAULT_DIFFICULTY,
    DIFFICULTY_ALIASES,
    DIFFICULTY_LEVELS,
    EDU_LEVELS,
    SUBJECTS,
    get_all_subjects,
    get_subject_config,
    get_subjects_by_edu,
    normalize_difficulty,
    resolve_subject,
)
