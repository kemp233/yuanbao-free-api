"""聊天接口模块"""

import logging
import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.config import settings
from src.dependencies.auth import get_authorized_headers
from src.schemas.chat import ChatCompletionRequest, YuanBaoChatCompletionRequest
#from src.services.chat.completion import create_completion_stream
from src.services.chat.conversation import create_conversation
from src.utils.chat import get_model_info, parse_messages

logger = logging.getLogger(__name__)
router = APIRouter()

async def clean_stream_generator(original_generator):
    """
    根据 Debug 结果定制的清洗生成器
    """
    is_thinking = False

    async for chunk in original_generator:
        # 1. 处理结束标记
        if chunk == "[DONE]":
            yield chunk
            continue

        try:
            # 2. 直接解析 JSON (Debug 显示 chunk 就是纯 JSON 字符串)
            openai_obj = json.loads(chunk)
            
            if "choices" in openai_obj and openai_obj["choices"]:
                delta = openai_obj["choices"][0].get("delta", {})
                content_str = delta.get("content", "")

                # 3. 解析嵌套的元宝 JSON
                if content_str and content_str.startswith("{"):
                    try:
                        inner = json.loads(content_str)
                        msg_type = inner.get("type")
                        clean_text = ""

                        if msg_type == "think":
                            t_content = inner.get("content", "")
                            if not is_thinking:
                                clean_text = f"<thought>\n{t_content}"
                                is_thinking = True
                            else:
                                clean_text = t_content
                        
                        elif msg_type == "text":
                            t_msg = inner.get("msg", "")
                            if is_thinking:
                                # 思考结束，注入标签并拼接正文
                                clean_text = f"\n</thought>\n\n{t_msg}"
                                is_thinking = False
                            else:
                                clean_text = t_msg
                        
                        # 过滤掉无用的信令包 (tips, meta 等)
                        elif msg_type in ["tips", "meta"]:
                            clean_text = ""

                        # 4. 替换内容并序列化回字符串
                        openai_obj["choices"][0]["delta"]["content"] = clean_text
                        yield json.dumps(openai_obj, ensure_ascii=False)
                        continue

                    except json.JSONDecodeError:
                        pass # 内部解析失败，保持原样

            # 默认返回原始 JSON 字符串
            yield json.dumps(openai_obj, ensure_ascii=False)
            
        except Exception as e:
            # 容错处理
            yield chunk

@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    headers: dict = Depends(get_authorized_headers),
):
    """聊天完成接口"""
    try:
        # 强制创建新对话以防历史记录干扰
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

        # 获取底层字符串流
        raw_gen = create_completion_stream(chat_request, headers, request.should_remove_conversation)
        
        # 包装并交给 EventSourceResponse (它会自动加 data: 前缀)
        logger.info(f"Streaming cleaned response for chat_id: {request.chat_id}")
        return EventSourceResponse(clean_stream_generator(raw_gen), media_type="text/event-stream")
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
