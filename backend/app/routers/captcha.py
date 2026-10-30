"""工作量证明人机验证的公开接口：发题与交卷

这两个接口都不需要登录：登录、注册、找回密码都要先在这里拿题与换令牌。
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..captcha import issue_challenge, verify_solution
from ..requestinfo import client_ip_from_request

router = APIRouter(prefix="/api/captcha", tags=["captcha"])


class VerifyBody(BaseModel):
    challenge: str = Field("", max_length=128)
    nonce: str = Field("", max_length=32)


@router.get("/challenge")
def get_challenge(request: Request):
    """发一道新题；本机开发等豁免来源会拿到 required=False"""
    return {"ok": True, **issue_challenge(client_ip_from_request(request))}


@router.post("/verify")
def verify(body: VerifyBody, request: Request):
    """校验答案并换取一次性令牌；同一 challenge 只能成功一次"""
    ok, reason, token, expires_in = verify_solution(
        body.challenge, body.nonce, client_ip_from_request(request)
    )
    if not ok:
        raise HTTPException(400, reason)
    return {"ok": True, "token": token, "expiresIn": expires_in}
