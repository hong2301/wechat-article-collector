"""RSA 密钥对：生成 / 读写 PEM。

私钥与公钥均为 PEM 格式：
- keys/private_key.pem（严禁入库，.gitignore 已忽略）
- keys/public_key.pem（可入库，随产品构建注入）
"""
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_pair(bits: int = 2048) -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=bits)


def save_private_key(key: rsa.RSAPrivateKey, path: Path | str) -> None:
    Path(path).write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def save_public_key(key: rsa.RSAPrivateKey | rsa.RSAPublicKey, path: Path | str) -> None:
    pub = key.public_key() if isinstance(key, rsa.RSAPrivateKey) else key
    Path(path).write_bytes(
        pub.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def load_private_key(path: Path | str) -> rsa.RSAPrivateKey:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    key = load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TypeError("PEM 不是 RSA 私钥")
    return key


def load_public_key(path: Path | str) -> rsa.RSAPublicKey:
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    key = load_pem_public_key(Path(path).read_bytes())
    if not isinstance(key, rsa.RSAPublicKey):
        raise TypeError("PEM 不是 RSA 公钥")
    return key