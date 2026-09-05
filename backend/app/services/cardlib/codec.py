"""卡密编解码：载荷 JSON + 签名 -> base64url 卡密串。

格式约定（见 docs/设计方案.md）:
    卡密 = base64url( 载荷JSON字节 + SHA256withRSA签名原始字节 )
    载荷JSON: { "exp": ISO到期时间, "lv": 权限码, "hw": 设备指纹哈希(可选) }

注意：签名是随机字节可能包含 '.' 等不可预测字符，故不用分隔符，
而是利用 RSA 签名长度固定（key_size/8）直接尾截。
"""
import base64
import json
from typing import Any

SIGNATURE_LEN = 256  # RSA-2048 签名固定 256 字节；换密钥位数需同步修改(key_size//8)


def build_payload(exp: str, lv: int = 1, hw: str = "") -> dict:
    """构造载荷；hw 为空 = 不绑定机器（如测试卡）。"""
    payload: dict[str, Any] = {"exp": exp, "lv": lv}
    if hw:
        payload["hw"] = hw
    return payload


def encode_card(payload: dict, signature: bytes) -> str:
    """载荷 JSON 字节 + 签名字节 -> base64url 卡密串。"""
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    data = body + signature
    return base64.urlsafe_b64encode(data).decode("ascii")


def decode_card(card: str) -> tuple[dict, bytes]:
    """卡密串 -> (载荷 dict, 原始签名 bytes)。"""
    data = base64.urlsafe_b64decode(card.encode("ascii"))
    signature = data[-SIGNATURE_LEN:]
    body = data[:-SIGNATURE_LEN]
    return json.loads(body), signature