# -*- coding: utf-8 -*-
"""core.doubao_api: 豆包(Doubao-Seed-2.0-mini)识图识别互动栏数据
依赖: 仅标准库 + requests (runtime)
"""
import re

DOUBAO_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
DOUBAO_MODEL = "doubao-seed-2-0-mini-260428"

DOUBAO_PROMPT = (
    "这是一张微信公众号文章底部的互动栏截图，从左到右可能依次有：点赞(大拇指图标)、"
    "转发(箭头图标)、喜欢(爱心图标)、留言(气泡图标+文字)。"
    "每个图标右侧是它的数量，有的指标可能不出现(比如没有转发、没有留言)。"
    "请先通过图标判断存在哪些指标，再读取每项的数值。"
    "严格按以下格式逐行输出，数字用阿拉伯数字，即使该项为0也输出该行："
    "点赞: <数字>；转发: <数字>；喜欢: <数字>；留言: <数字,无留言填0>"
)


def _parse_interact_text(text):
    """解析豆包输出的互动数据文本，返回 (点赞, 转发, 喜欢, 留言)；解析不到某项填 0"""
    likes = forwards = favorites = comments = 0
    if text:
        m = re.search(r"点赞[：:\s]*?(-?\d+)", text)
        if m:
            likes = int(m.group(1))
        m = re.search(r"转发[：:\s]*?(-?\d+)", text)
        if m:
            forwards = int(m.group(1))
        m = re.search(r"喜欢[：:\s]*?(-?\d+)", text)
        if m:
            favorites = int(m.group(1))
        m = re.search(r"留言[：:\s]*?(-?\d+)", text)
        if m:
            comments = int(m.group(1))
    return likes, forwards, favorites, comments


def doubao_recognize_interact(shot_b64, api_key, timeout=30):
    """调用豆包识图，识别互动栏截图的 点赞/转发/喜欢/留言
    入参: shot_b64(base64, 可带 data:image 前缀), api_key(火山方舟 Key)
    返回: (点赞, 转发, 喜欢, 留言) 均为 int; API 调用失败返回 None"""
    try:
        import requests
        b64 = shot_b64
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        payload = {
            "model": DOUBAO_MODEL,
            "input": [{"role": "user", "content": [
                {"type": "input_image", "image_url": "data:image/webp;base64," + b64},
                {"type": "input_text", "text": DOUBAO_PROMPT},
            ]}],
        }
        headers = {"Authorization": "Bearer " + api_key,
                   "Content-Type": "application/json"}
        resp = requests.post(DOUBAO_URL, headers=headers, json=payload, timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        text = ""
        for out in data.get("output", []):
            for c in out.get("content", []):
                if c.get("type") == "output_text":
                    text += (c.get("text") or "")
        if not text.strip():
            return None
        return _parse_interact_text(text)
    except Exception:
        return None


__all__ = ["DOUBAO_URL", "DOUBAO_MODEL", "DOUBAO_PROMPT",
           "_parse_interact_text", "doubao_recognize_interact"]
