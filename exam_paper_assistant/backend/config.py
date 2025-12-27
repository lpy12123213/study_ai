"""
配置文件 - 统一管理API和模型配置
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ============ OpenRouter API 配置 ============
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# ============ 模型配置 ============
# 主AI模型（用于对话和工具调用编排）
MAIN_MODEL = os.getenv("MAIN_MODEL", "openai/gpt-5-mini")

# 子AI模型（用于题目选择）
SUB_MODEL = os.getenv("SUB_MODEL", "openai/gpt-5-mini")

# ============ 模型参数配置 ============
# 主AI参数
MAIN_MODEL_TEMPERATURE = float(os.getenv("MAIN_MODEL_TEMPERATURE", "0.7"))
MAIN_MODEL_MAX_TOKENS = int(os.getenv("MAIN_MODEL_MAX_TOKENS", "2000"))

# 子AI参数
SUB_MODEL_TEMPERATURE = float(os.getenv("SUB_MODEL_TEMPERATURE", "0.3"))
SUB_MODEL_MAX_TOKENS = int(os.getenv("SUB_MODEL_MAX_TOKENS", "1000"))

# ============ 对话配置 ============
MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "10"))  # 最大工具调用轮数

# ============ 爬虫配置 ============
DEFAULT_SUBJECT = os.getenv("DEFAULT_SUBJECT", "高中数学")
# 难度过滤模式：multi（默认，简单/困难多档查询）/ single（严格单档查询）
DIFFICULTY_QUERY_MODE = os.getenv("DIFFICULTY_QUERY_MODE", "multi").strip().lower()

# ============ 超时配置 ============
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "120"))  # API请求超时时间（秒）
SUB_AI_TIMEOUT = int(os.getenv("SUB_AI_TIMEOUT", "60"))  # 子AI请求超时时间（秒）


def get_config_summary():
    """获取配置摘要（用于调试）"""
    return {
        "main_model": MAIN_MODEL,
        "sub_model": SUB_MODEL,
        "main_temperature": MAIN_MODEL_TEMPERATURE,
        "sub_temperature": SUB_MODEL_TEMPERATURE,
        "max_iterations": MAX_TOOL_ITERATIONS,
        "default_subject": DEFAULT_SUBJECT,
        "difficulty_query_mode": DIFFICULTY_QUERY_MODE,
        "api_configured": bool(OPENROUTER_API_KEY)
    }
