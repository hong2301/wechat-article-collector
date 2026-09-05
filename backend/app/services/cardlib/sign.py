"""签名 / 验签：SHA256withRSA（PKCS#1 v1.5 + SHA-256）。"""
import json

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def _payload_bytes(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def sign_dict(payload: dict, private_key: rsa.RSAPrivateKey) -> bytes:
    """对载荷 dict 签名，返回原始签名字节。"""
    return private_key.sign(
        _payload_bytes(payload),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def sign_payload(payload: dict, private_key_pem: str) -> bytes:
    """兼容入口：传入私钥 PEM 文件路径。"""
    from .keys import load_private_key

    return sign_dict(payload, load_private_key(private_key_pem))


def verify_card(card: str, public_key_pem: str) -> dict | None:
    """验签卡密串，成功返回载荷 dict，失败（篡改/损坏/密钥不符）返回 None。"""
    from .codec import decode_card
    from .keys import load_public_key

    try:
        payload, signature = decode_card(card)
        load_public_key(public_key_pem).verify(
            signature,
            _payload_bytes(payload),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return payload
    except Exception:
        # 签名不匹配 / 载荷被篡改 / 结构损坏 / 密钥不符，一律视为无效
        return None