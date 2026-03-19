"""聊天接口模块"""

import logging
import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.config import settings
from src.dependencies.auth import get_authorized_headers
from src.schemas.chat import ChatCompletionRequest, YuanBaoChatCompletionRequest
# 注意：顶部不再导入 services 里的函数
from src.utils.chat import get_model_info, parse_messages

logger = logging.getLogger(__name__)
router = APIRouter()

async def clean_stream_generator(original_generator):
    """
    根据 Debug 结果定制的清洗生成器
    """
    is_thinking = False
    thought_started = False

    async for chunk in original_generator:
        if chunk == "[DONE]":
            yield chunk
            continue

        try:
            openai_obj = json.loads(chunk)
            if "choices" in openai_obj and openai_obj["choices"]:
                delta = openai_obj["choices"][0].get("delta", {})
                content_str = delta.get("content", "")

                if content_str and content_str.startswith("{"):
                    try:
                        inner = json.loads(content_str)
                        msg_type = inner.get("type")
                        clean_text = ""

                        if msg_type == "think":
                            t_content = inner.get("content", "")
                            if not thought_started:
                                # 开始思考，注入标签
                                clean_text = f"<thought>\n{t_content}"
                                thought_started = True
                                is_thinking = True
                            else:
                                clean_text = t_content
                        
                        elif msg_type == "text":
                            t_msg = inner.get("msg", "")
                            if is_thinking:
                                # 思考转正文，闭合标签
                                clean_text = f"\n</thought>\n\n{t_msg}"
                                is_thinking = False
                            else:
                                clean_text = t_msg
                        
                        elif msg_type in ["tips", "meta"]:
                            clean_text = ""

                        openai_obj["choices"][0]["delta"]["content"] = clean_text
                        yield json.dumps(openai_obj, ensure_ascii=False)
                        continue

                    except json.JSONDecodeError:
                        pass

            yield json.dumps(openai_obj, ensure_ascii=False)
        except Exception:
            yield chunk

@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    headers: dict = Depends(get_authorized_headers),
):
    """聊天完成接口"""
    # 【核心修复】将这两个导入放在这里！
    # 只有当请求进入时才导入，从而彻底切断启动时的循环依赖链
    from src.services.chat.completion import create_completion_stream
    from src.services.chat.conversation import create_conversation

    try:
        # 强制创建新对话 (如果你需要记忆功能，可以改回 if not request.chat_id)
        request.chat_id = await create_conversation(settings.agent_id, headers)
        
        prompt = parse_messages(request.messages)
        model_info = get_model_info(request.model) or {"model": "hy_deepseek_r1", "support_functions": []}

        chat_request = YuanBaoChatCompletionRequest(
            agent_id=settings.agent_id,
            chat_id=request.chat_id,
            prompt=prompt,
            chat_model_id=model_info["model"],
            multimedia=request.multimedia,
            support_functions=model_info.get("support_functions", [])
        )

        # 这里就能正常调用了
        raw_gen = create_completion_stream(chat_request, headers, request.should_remove_conversation)
        
        logger.info(f"Streaming response for chat_id: {request.chat_id}")
        return EventSourceResponse(clean_stream_generator(raw_gen), media_type="text/event-stream")
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
