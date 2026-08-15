# -*- coding: utf-8 -*-
"""豆包 Doubao-Seed-2.0-mini 识图测试(火山方舟 responses API)"""
import base64
import requests

API_KEY = "ark-f3f8cc43-f651-478c-b2b0-aa599b191df6-a93af"
URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
MODEL = "doubao-seed-2-0-mini-260428"
IMAGE_PATH = r"C:\Users\86150\Desktop\Screenshot 2026-08-15 164948.png"

PROMPT = (
    "这是一张微信公众号文章底部的互动栏截图，从左到右可能依次有："
    "点赞(大拇指图标)、转发(箭头图标)、喜欢(爱心图标)、留言(气泡图标+文字)。\n"
    "每个图标右侧是它的数量，有的指标可能不出现(比如没有转发、没有留言)。"
    "请先通过图标判断存在哪些指标，再读取每项的数值。\n"
    "严格按以下格式逐行输出，数字用阿拉伯数字，即使该项为0也输出该行：\n"
    "点赞: <数字>\n转发: <数字>\n喜欢: <数字>\n留言: <数字>，若无留言则填0"
)


def call_doubao(image_path, prompt=PROMPT):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    payload = {
        "model": MODEL,
        "input": [{"role": "user", "content": [
            {"type": "input_image", "image_url": f"data:image/png;base64,{b64}"},
            {"type": "input_text", "text": prompt},
        ]}],
    }
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    resp = requests.post(URL, headers=headers, json=payload, timeout=60)
    print(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(resp.text)
        return None
    data = resp.json()
    text = ""
    for out in data.get("output", []):
        for c in out.get("content", []):
            if c.get("type") == "output_text":
                text += (c.get("text") or "")
    return text


if __name__ == "__main__":
    print(f"识别: {IMAGE_PATH}\n模型: {MODEL}\n")
    r = call_doubao(IMAGE_PATH)
    if r:
        print("===== 豆包返回 =====")
        print(r)
