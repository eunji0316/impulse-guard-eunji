"""서비스 공용: 입력 규칙과 로컬 전용 검사

모든 서비스(위험도, 5단계 LLM 문구 등)의 요청 본문은 StrictBody를 상속한다.
- 정해진 칸만 받는다 (extra='forbid'). 회원 아이디, 상품명, OCR 원문 같은 칸이 섞여 오면 422로 거부한다
- 서버는 요청 내용을 저장하거나 로그에 남기지 않는다 (uvicorn access log도 끔, __main__.py)
"""
from typing import Annotated, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import config


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


# 숫자 하나 또는 모름(null). 문자열, true/false, NaN, 무한대는 받지 않는다
Num = Optional[Annotated[float, Field(strict=True, allow_inf_nan=False)]]


async def validation_error(request: Request, exc):
    """입력 오류는 어느 칸이 왜 틀렸는지만 알린다 (받은 값은 되돌려 주지 않는다. NaN도 여기서 422)"""
    detail = [{'loc': list(e.get('loc', ())), 'type': e.get('type', '')} for e in exc.errors()]
    return JSONResponse({'detail': detail}, status_code=422)


async def local_only(request: Request, call_next):
    """127.0.0.1(::1)에서 온 요청만 받는다"""
    host = request.client.host if request.client else ''
    if host not in config.LOCAL_CLIENTS:
        return JSONResponse({'detail': 'local only'}, status_code=403)
    return await call_next(request)
