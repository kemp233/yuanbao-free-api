import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# 模型映射
MODELS_INFO = {
    "hunyuan-latest": {"model": "hy_deepseek_r1", "support_functions": []},
    "deepseek-r1": {"model": "hy_deepseek_r1", "support_functions": []},
    "deepseek-r1-search": {"model": "hy_deepseek_r1", "support_functions": ["web_search"]},
}

def get_model_info(model_name: str) -> Dict:
    return MODELS_INFO.get(model_name, MODELS_INFO["deepseek-r1"])

def parse_messages(messages: Any) -> str:
    try:
        for msg in reversed(messages):
            role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else None)
            content = getattr(msg, "content", "") or (msg.get("content", "") if isinstance(msg, dict) else "")
            if role == "user":
                return content
    except Exception as e:
        logger.error(f"Parse messages error: {e}")
    return ""

async def process_response_stream(response, chat_id, model=None):
    """
    极简底层处理：只负责从 data: 中提取 JSON 字符串
    """
    try:
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                data = line[5:].strip()
                if data:
                    yield data # 返回纯 JSON 字符串
    except Exception as e:
        logger.error(f"Stream error: {e}")
