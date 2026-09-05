# -*- coding: utf-8 -*-
"""卡密授权(离线 RSA 验签): 客户端验证模块

- 公钥: 内嵌常量(卡密系统 keys/public_key.pem, 构建时可替换; 无期限授权可通过
  项目根/安装根 guest.key 文件启用——内容随意(可为公钥文本), 存在即视为永久授权)
- 卡密格式: base64url(载荷JSON + SHA256withRSA签名), 载荷 {exp, lv, hw}
- 激活文件: <数据目录>/license.json = {card, exp, lv} + HMAC 防篡改
- 到期: 精确定死; 距到期<=3天 status.warn 提示即将到期
"""
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone

from .cardlib.codec import decode_card

# 公钥(卡密系统 keys/public_key.pem)——构建时可整体替换此块
PUBLIC_KEY_PEM = """
    -----BEGIN PUBLIC KEY-----
    MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAs1vDA/tGoXJgCm+omyAM
    Lk4ayzIGbAtHsva3gr9+fJEqJl3xM7+aPBq7SFRM/KgyyxFf9tIijleiFdI0SbjD
    BMmJEZa84bLxb8UTUy33LyXpaRjnt+fQheYUW0fR99//Ohgp44ODU8cxWY7kYOln
    hvyb3s3WoL5/2fJIwsQfVfDHqqtsxboPvcydXJLDVDHvy+sa+3j1uLbO1AdkPh7M
    TOwsT6psaARPvHRSmvlq0CJ03c9yLai1RqdS8qveEQ82laa1smMIDNxXrC4F/m6I
    /aTZLOmrrlAvD7de9mrNTspSIPkbgbDrK9Tw/9HHSN6ChIEJ4fMhy4pozEhOdE5r
    6wIDAQAB
    -----END PUBLIC KEY-----
"""


# 激活文件 HMAC 盐(内嵌常量, 防随手改文件; 非防逆向)
_HMAC_SALT = b"wechat-collector-license-hmac-2026"


def _license_path():
    from ..database import data_dir
    return os.path.join(data_dir(), "license.json")


def _guest_key_path():
    """客人钥匙(永久授权)路径: 打包版=exe上级(安装根)/guest.key; dev=项目根/guest.key
    可用环境变量 WECHAT_GUEST_KEY_PATH 覆盖(测试/灵活部署)"""
    ov = os.environ.get("WECHAT_GUEST_KEY_PATH")
    if ov:
        return ov
    from .. import env as _env
    if _env.is_prod():
        import sys
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))))
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(base, "guest.key")


def has_guest_key() -> bool:
    """检测客人钥匙(存在=永久授权, 无期限)"""
    try:
        return os.path.exists(_guest_key_path())
    except Exception:
        return False


def _sign_activation(card: str, exp: str, lv: int) -> str:
    body = json.dumps({"card": card, "exp": exp, "lv": lv}, separators=(",", ":")).encode()
    return hmac.new(_HMAC_SALT, body, hashlib.sha256).hexdigest()


def _verify_activation(d: dict) -> bool:
    try:
        body = json.dumps({"card": d["card"], "exp": d["exp"], "lv": d.get("lv", 1)}, separators=(",", ":")).encode()
        expect = hmac.new(_HMAC_SALT, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expect, d.get("sig", ""))
    except Exception:
        return False


def _load_activation() -> dict | None:
    try:
        with open(_license_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        if not _verify_activation(d):
            return None
        return d
    except Exception:
        return None


def _save_activation(card: str, exp: str, lv: int):
    os.makedirs(os.path.dirname(_license_path()), exist_ok=True)
    with open(_license_path(), "w", encoding="utf-8") as f:
        json.dump({"card": card, "exp": exp, "lv": lv,
                   "sig": _sign_activation(card, exp, lv)}, f)


def _parse_exp(exp: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)   # 无时区按 UTC 处理
        return dt
    except Exception:
        return None


def verify_card(card: str, bind_fp: str = "") -> dict:
    """验签并返回 {ok, msg, expire, lv, permanent, warn}"""
    card = (card or "").strip()
    if not card:
        return {"ok": False, "msg": "卡密不能为空"}
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    try:
        payload, signature = decode_card(card)
        load_pem_public_key(PUBLIC_KEY_PEM.encode("utf-8")).verify(
            signature,
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception as e:
        return {"ok": False, "msg": f"卡密无效({e.__class__.__name__})"}
    exp = payload.get("exp", "")
    lv = int(payload.get("lv", 1))
    # 到期判断(永久授权: exp 为空视为永久)
    dt = _parse_exp(exp) if exp else None
    if dt is not None and dt <= datetime.now(timezone.utc):
        return {"ok": False, "msg": f"卡密已过期({exp})"}
    # 设备指纹绑定(卡密含 hw 才校验)
    hw = payload.get("hw", "")
    if hw and bind_fp:
        from .cardlib.fingerprint import normalize_fingerprint
        if normalize_fingerprint(hw) != normalize_fingerprint(bind_fp):
            return {"ok": False, "msg": "卡密已绑定其他设备指纹"}
    try:
        _save_activation(card, exp or "", lv)
    except Exception:
        pass
    return {"ok": True, "expire": exp or "", "lv": lv,
            "permanent": not exp,
            "warn": _warn(exp, dt)}


def _warn(exp: str, dt: datetime | None) -> bool:
    if not dt:
        return False
    try:
        return (dt - datetime.now(timezone.utc)) <= timedelta(days=3)
    except Exception:
        return False


def _ensure_guest_activation() -> dict:
    """客人钥匙激活: 也落 license.json(与普通卡统一显示; 无期限/lv=1; 幂等)"""
    act = _load_activation()
    if act and act.get("guest"):
        return act
    try:
        _save_activation("guest", "", 1)
    except Exception:
        pass
    return {"card": "guest", "exp": "", "lv": 1}


def status() -> dict:
    """当前授权状态: 开发环境直接放行 > 客人钥匙 > 有效激活 > 无"""
    from .. import env as _env
    if _env.is_dev():
        return {"ok": True, "expire": "", "permanent": True, "warn": False, "guest": False, "dev": True}
    if has_guest_key():
        _ensure_guest_activation()
        return {"ok": True, "expire": "", "permanent": True, "warn": False, "guest": True}
    act = _load_activation()
    if not act:
        return {"ok": False, "expire": "", "permanent": False, "warn": False, "guest": False}
    dt = _parse_exp(act.get("exp", "")) if act.get("exp") else None
    if act.get("exp") and dt is None:
        return {"ok": False, "expire": "", "permanent": False, "warn": False, "guest": False}
    if dt is not None and dt <= datetime.now(timezone.utc):
        return {"ok": False, "expire": "", "permanent": False, "warn": False, "guest": False,
                "msg": "授权已过期"}
    return {"ok": True, "expire": act.get("exp", ""), "permanent": not act.get("exp"),
            "warn": _warn(act.get("exp", ""), dt), "guest": False}