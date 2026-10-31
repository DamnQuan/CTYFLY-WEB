"""本地上传：航司 Logo 图片

安全要点：
- 只接受光栅图，PNG / JPG / WebP / GIF，按**文件头 magic bytes** 判定，
  完全不信客户端给的 Content-Type 与文件名后缀；SVG 一律拒绝
  SVG 可内嵌脚本，作为图片托管等同存储型 XSS。
- 落盘文件名由服务端随机生成，杜绝路径穿越与覆盖已有文件。
- 体积上限由 BodySizeLimitMiddleware 与读取时双重把关。
"""
import secrets

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from ..audit import log_event
from ..config import MAX_UPLOAD_BYTES, UPLOAD_DIR, UPLOAD_URL_PREFIX
from ..deps import require_auth, require_capability
from ..ratelimit import enforce
from ..requestinfo import client_ip_from_request, user_agent

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

# 文件头 -> 扩展名，顺序无关，逐个前缀比对
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)


def sniff_image_ext(head: bytes) -> str | None:
    """按文件头识别图片类型，非光栅图返回 None"""
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext
    # WebP: 'RIFF' + 4 字节长度 + 'WEBP'
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


def _limit_text() -> str:
    return f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB"


@router.post("/airline-logo")
async def upload_airline_logo(request: Request, file: UploadFile = File(...),
                              user: dict = Depends(require_auth)):
    """上传航司 Logo，返回可直接写入 logo_url 的同源相对地址"""
    enforce(request, "upload", 20, 3600)

    head = await file.read(16)
    if not head:
        raise HTTPException(400, "请选择要上传的图片")

    ext = sniff_image_ext(head)
    if not ext:
        raise HTTPException(400, "仅支持 PNG / JPG / WebP / GIF 格式的图片")

    # 读取剩余内容，多读 1 字节用于判断是否超限
    rest = await file.read(MAX_UPLOAD_BYTES + 1)
    data = head + rest
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"图片不能超过 {_limit_text()}")

    name = f"airline-{secrets.token_hex(12)}{ext}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / name).write_bytes(data)

    url = f"{UPLOAD_URL_PREFIX}/{name}"
    log_event("airline", "上传航司 Logo", actor=user, target_type="upload", target_id=name,
              detail=f"{len(data) // 1024} KB {ext}",
              ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True, "url": url, "bytes": len(data)}


@router.post("/partner-logo")
async def upload_partner_logo(request: Request, file: UploadFile = File(...),
                              user: dict = Depends(require_capability("manage_notices"))):
    """上传合作伙伴 Logo，管理能力：manage_notices，返回同源相对地址"""
    enforce(request, "upload", 20, 3600)

    head = await file.read(16)
    if not head:
        raise HTTPException(400, "请选择要上传的图片")

    ext = sniff_image_ext(head)
    if not ext:
        raise HTTPException(400, "仅支持 PNG / JPG / WebP / GIF 格式的图片")

    rest = await file.read(MAX_UPLOAD_BYTES + 1)
    data = head + rest
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"图片不能超过 {_limit_text()}")

    name = f"partner-{secrets.token_hex(12)}{ext}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / name).write_bytes(data)

    url = f"{UPLOAD_URL_PREFIX}/{name}"
    log_event("admin", "上传合作伙伴 Logo", actor=user, target_type="upload", target_id=name,
              detail=f"{len(data) // 1024} KB {ext}",
              ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True, "url": url, "bytes": len(data)}


@router.post("/archive-image")
async def upload_archive_image(request: Request, file: UploadFile = File(...),
                               user: dict = Depends(require_auth)):
    """飞圈事件检索图片：登录用户投稿与管理员审核共用，返回同源相对地址"""
    enforce(request, "upload", 30, 3600)

    head = await file.read(16)
    if not head:
        raise HTTPException(400, "请选择要上传的图片")

    ext = sniff_image_ext(head)
    if not ext:
        raise HTTPException(400, "仅支持 PNG / JPG / WebP / GIF 格式的图片")

    rest = await file.read(MAX_UPLOAD_BYTES + 1)
    data = head + rest
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"图片不能超过 {_limit_text()}")

    name = f"archive-{secrets.token_hex(12)}{ext}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / name).write_bytes(data)

    url = f"{UPLOAD_URL_PREFIX}/{name}"
    log_event("archive", "上传事件图片", actor=user, target_type="upload", target_id=name,
              detail=f"{len(data) // 1024} KB {ext}",
              ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True, "url": url, "bytes": len(data)}
