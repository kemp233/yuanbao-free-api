import logging
import json
import time
from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse
from src.config import settings
from src.dependencies.auth import get_authorized_headers
from src.schemas.chat import ChatCompletionRequest, YuanBaoChatCompletionRequest

logger = logging.getLogger(__name__)
router = APIRouter()

async def clean_stream_generator(original_generator, model_name):
    """
    强制 OpenAI 格式化生成器
    """
    is_thinking = False
    
    async for chunk in original_generator:
        # 处理结束标记
        if chunk == "[DONE]":
            yield "[DONE]"
            continue

        try:
            # 1. 尝试解析。如果 chunk 本身已经是包装好的 OpenAI 格式，先拆开
            inner_str = chunk
            if '"choices"' in chunk:
                temp_obj = json.loads(chunk)
                inner_str = temp_obj["choices"][0]["delta"].get("content", "")

            # 2. 如果内容不是 JSON 结构（如 [DONE] 或 纯文字），尝试直接包装
            if not inner_str.strip().startswith("{"):
                # 如果是 Cherry Studio 发出的非 JSON 杂质（如 status），直接跳过
                continue

            # 3. 解析腾讯原始 JSON
            inner_json = json.loads(inner_content_str if 'inner_content_str' in locals() else inner_str)
            msg_type = inner_json.get("type")
            clean_text = ""

            if msg_type == "think":
                text = inner_json.get("content", "")
                clean_text = f"<thought>\n{text}" if not is_thinking else text
                is_thinking = True
            elif msg_type == "text":
                text = inner_json.get("msg", "")
                clean_text = f"\n</thought>\n\n{text}" if is_thinking else text
                is_thinking = False
            else:
                continue # 忽略 tips, meta 等

            # 4. 强制构造 OpenAI 格式发给客户端
            openai_packet = {
                "choices": [{"delta": {"content": clean_text}, "finish_reason": None}],
                "model": model_name,
                "created": int(time.time())
            }
            yield json.dumps(openai_packet, ensure_ascii=False)

        except Exception as e:
            continue

@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, headers: dict = Depends(get_authorized_headers)):
    from src.services.chat.completion import create_completion_stream
    from src.services.chat.conversation import create_conversation
    from src.utils.chat import get_model_info, parse_messages

    try:
        # 强制创建新会话避免超长报错
        request.chat_id = await create_conversation(settings.agent_id, headers)
        prompt = parse_messages(request.messages)
        model_info = get_model_info(request.model)

        chat_request = YuanBaoChatCompletionRequest(
            agent_id=settings.agent_id,
            chat_id=request.chat_id,
            prompt=prompt,
            chat_model_id=model_info["model"],
            multimedia=request.multimedia,
            support_functions=model_info.get("support_functions", [])
        )

        raw_gen = create_completion_stream(chat_request, headers, request.should_remove_conversation)
        
        # 这里的关键：无论底层发什么，我们都通过包装器保证输出是 OpenAI 格式
        return EventSourceResponse(
            clean_stream_generator(raw_gen, request.model), 
            media_type="text/event-stream"
        )
    except Exception as e:
        logger.error(f"Endpoint Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
