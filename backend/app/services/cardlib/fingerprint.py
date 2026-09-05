"""设备指纹：归一化 + SHA-256 哈希。

指纹输入可能是：
- JSON（{"mac","cpu","board","disk",...}）：按固定字段顺序提取拼接
- 纯文本：原样视为已拼接指纹串

归一化规则是【发卡端 / 验签端 / 指纹客户端】共用的唯一规范（见 docs/开发规范.md），
两端实现必须一致（cardlib 与 frontend/lib/fingerprint.ts 镜像）。
"""
import hashlib
import json

# 字段提取顺序（与前端 lib/fingerprint.ts 保持一致）
FINGERPRINT_FIELDS = [
    "mac", "cpu_id", "cpu", "board_serial", "board", "disk_serial", "disk", "serial",
]


def normalize_fingerprint(raw: str) -> str:
    """把输入（JSON 或纯文本）归一化为规范指纹串；空输入返回空串。"""
    s = (raw or "").strip()
    if not s:
        return ""
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            parts = [
                str(data[k])
                for k in FINGERPRINT_FIELDS
                if data.get(k) not in (None, "")
            ]
            if parts:
                return "|".join(parts)
    except (json.JSONDecodeError, ValueError):
        pass  # 非 JSON，按纯文本处理
    return s


def calc_fingerprint(text: str) -> str:
    """指纹串（已归一化或原始文本）-> SHA-256 十六进制哈希。

    注意：请先经 normalize_fingerprint 归一化再哈希；直接调用等同原样哈希。
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()