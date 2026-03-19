"""聊天接口模块"""

import logging
import json
from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.config import settings
from src.dependencies.auth import get_authorized_headers
from src.schemas.chat import ChatCompletionRequest, YuanBaoChatCompletionRequest
from src.services.chat.completion import create_completion_stream
from src.services.chat.conversation import create_conversation
from src.utils.chat import get_model_info, parse_messages

logger = logging.getLogger(__name__)
router = APIRouter()


async def clean_stream_generator(original_generator):
    """
    包装原始生成器，清洗腾讯元宝返回的原始 JSON 数据
    """
    async for event in original_generator:
        # event 通常是一个字典，包含 "id", "event", "data" 等字段
        if isinstance(event, dict) and "data" in event:
            try:
                # 1. 解析 OpenAI 格式的 data 字符串
                data_json = json.loads(event["data"])
                
                # 2. 检查 choices 中是否有 delta 内容
                if "choices" in data_json and len(data_json["choices"]) > 0:
                    delta = data_json["choices"][0].get("delta", {})
                    content = delta.get("content", "")

                    if content:
                        try:
                            # 3. 核心：尝试解析嵌套在 content 里的元宝原始 JSON
                            # 元宝返回的内容格式如: {"type": "think", "content": "..."} 或 {"type": "text", "msg": "..."}
                            inner_json = json.loads(content)
                            
                            clean_content = ""
                            if inner_json.get("type") == "think":
                                # 提取深度思考内容
                                # 许多客户端支持识别 <thought> 标签，或者你可以直接输出内容
                                clean_content = inner_json.get("content", "")
                                # 如果你希望在客户端显示“思考中”区域，可以解开下面这行的注释
                                # clean_content = f"<thought>\n{clean_content}\n</thought>"
                                
                            elif inner_json.get("type") == "text":
                                # 提取最终回答内容
                                clean_content = inner_json.get("msg", "")
                            
                            # 4. 将清洗后的纯文本回填到 OpenAI 格式中
                            data_json["choices"][0]["delta"]["content"] = clean_content
                            event["data"] = json.dumps(data_json, ensure_ascii=False)
                            
                        except (json.JSONDecodeError, TypeError):
                            # 如果 content 不是 JSON 格式（比如已经清洗过或是结束标记），保持原样
                            pass
                
                yield event
            except Exception as e:
                # 发生解析错误时，至少保证原始数据能发出去
                logger.error(f"Cleaning stream error: {e}")
                yield event
        else:
            yield event


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    headers: dict = Depends(get_authorized_headers),
):
    """聊天完成接口

    Args:
        request: 聊天请求参数
        headers: 认证请求头

    Returns:
        EventSourceResponse: SSE 流式响应
    """
    try:
        if not request.chat_id:
            request.chat_id = await create_conversation(settings.agent_id, headers)
            logger.info(f"Conversation created with chat_id: {request.chat_id}")

        prompt = parse_messages(request.messages)
        model_info = get_model_info(request.model)
        if not model_info:
            raise HTTPException(status_code=400, detail="invalid model")

        chat_request = YuanBaoChatCompletionRequest(
            agent_id=settings.agent_id,
            chat_id=request.chat_id,
            prompt=prompt,
            chat_model_id=model_info["model"],
            multimedia=request.multimedia,
            support_functions=model_info.get("support_functions"),
        )

        # 获取原始生成器
        raw_generator = create_completion_stream(chat_request, headers, request.should_remove_conversation)
        
        # 使用清洗函数包装生成器
        cleaned_generator = clean_stream_generator(raw_generator)
        
        logger.info(f"Streaming chat completion for chat_id: {request.chat_id} (cleaned)")
        return EventSourceResponse(cleaned_generator, media_type="text/event-stream")
        
    except Exception as e:
        logger.error(f"Error in chat_completions: {e}")
        raise HTTPException(status_code=500, detail=str(e))
