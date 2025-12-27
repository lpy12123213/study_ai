"""
配置文件 - 统一管理API和模型配置

该模块作为兼容层保留，实际配置定义移动到 `core.settings`。
"""

from core.settings import (  # noqa: F401
    API_TIMEOUT,
    DEFAULT_SUBJECT,
    DIFFICULTY_QUERY_MODE,
    MAIN_MODEL,
    MAIN_MODEL_MAX_TOKENS,
    MAIN_MODEL_TEMPERATURE,
    MAX_TOOL_ITERATIONS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    SUB_AI_TIMEOUT,
    SUB_MODEL,
    SUB_MODEL_MAX_TOKENS,
    SUB_MODEL_TEMPERATURE,
    get_config_summary,
    settings,
)
