# -*- coding: utf-8 -*-
"""backend.app.services.doubao_api: 豆包识图(4指标识别)

识别文章底部互动栏截图: 点赞/转发/喜欢/留言
依赖: requests
"""

import re

DOUBAO_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"

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


def recognize_interact(shot_b64, api_key, model, timeout=30):
    """调用豆包识图，识别互动栏截图的 点赞/转发/喜欢/留言
    入参: shot_b64(base64, 可带 data:image 前缀), api_key(火山方舟 Key), model(模型id)
    返回: (点赞, 转发, 喜欢, 留言) 均为 int; API 调用失败返回 None"""
    try:
        import requests
        b64 = shot_b64
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        payload = {
            "model": model,
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


__all__ = ["recognize_interact"]

COMMENTS_PROMPT = """\
请从这张微信公众号文章评论区截图中提取所有可见评论，严格以JSON数组输出。
每条评论为一个对象，字段如下：
{
  "名称": "用户名",
  "地区": "IP属地",
  "时间": "评论时间",
  "点赞数量": "点赞数或0",
  "正文": "评论文本内容",
  "是否置顶": "是"或"否",
  "是否首评": "是"或"否",
  "是否作者": "是"或"否",
  "是否作者回复": "是"或"否",
  "是否作者点赞": "是"或"否",
  "回复文本": "如果正文含'回复某某某：'则填写'回复某某某：'前缀，否则留空"
}
识别规则：
1. 每条评论右下角有"回复"和"..."按钮（灰色小字），不要提取这些按钮文字
2. 置顶标签：名称行出现绿色"置顶"二字
3. 作者标签：名称行出现绿色"作者"二字表示该评论是文章作者发的,"是否作者"填"是"
4. 作者回复：若该评论正文行下有绿色"作者回复"标记则为"是"
5. 作者点赞：评论正文下有绿色"作者点赞"标记则为"是"
6. "回复"标签：评论文本中若含"回复某某某：评论文本"，"回复某某某："前缀填入"回复文本"字段
7. 首评标签：评论正文行下有绿色"首评"二字，则"是否首评"填"是"，否则"否"
8. 点赞数：名称行最右侧小拇指图标旁边的数字，无数字则为0
输出顺序：从上到下逐条输出。
9. 截断处理（滚动采集时图片可能截断评论）：
   - 若某条评论被**图片顶部截断**（只能看到下半部分）→ 忽略该评论，不要输出（上一张截图已识别过它）
   - 若某条评论被**图片底部截断**（结尾文字缺失）→ 正常输出可见部分即可，不要补全或编造
只输出JSON数组，不要输出其他说明文字。数组为空时输出[]。"""


def doubao_extract_comments(shot_b64s, api_key, timeout=30):
    """豆包识图从评论区截图提取评论
    shot_b64s: 单张base64 或 多张base64列表(交错截图拼接读取, 避免截断)
    返回: list[dict]; 失败返回 []"""
    try:
        import requests as _req
        if isinstance(shot_b64s, str):
            shot_b64s = [shot_b64s]
        contents = []
        for b64 in shot_b64s:
            b = b64
            if "," in b:
                b = b.split(",", 1)[1]
            contents.append({"type": "input_image", "image_url": "data:image/webp;base64," + b})
        contents.append({"type": "input_text", "text": COMMENTS_PROMPT})
        payload = {
            "model": "doubao-seed-2-0-mini-260428",
            "input": [{"role": "user", "content": contents}],
        }
        headers = {"Authorization": "Bearer " + api_key,
                   "Content-Type": "application/json"}
        resp = _req.post(DOUBAO_URL, headers=headers, json=payload, timeout=timeout)
        if resp.status_code != 200:
            return []
        data = resp.json()
        text = ""
        for out in data.get("output", []):
            for c in out.get("content", []):
                if c.get("type") == "output_text":
                    text += (c.get("text") or "")
        text = text.strip()
        if not text:
            return []
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            return []
        import json as _json
        result = _json.loads(m.group(0))
        if not isinstance(result, list):
            return []
        cleaned = []
        for item in result:
            if not isinstance(item, dict):
                continue
            name = (item.get("名称") or "").strip()
            if not name:
                continue
            cleaned.append({
                "名称": name,
                "地区": (item.get("地区") or "").strip(),
                "时间": (item.get("时间") or "").strip(),
                "点赞数量": str(item.get("点赞数量") or "0"),
                "正文": (item.get("正文") or "").strip(),
                "层级": int(item.get("层级") or 1) if str(item.get("层级")).isdigit() else 1,
                "是否置顶": (item.get("是否置顶") or "否"),
                "是否首评": (item.get("是否首评") or "否"),
                "是否作者": (item.get("是否作者") or "否"),
                "是否作者回复": (item.get("是否作者回复") or "否"),
                "是否作者点赞": (item.get("是否作者点赞") or "否"),
                "回复文本": (item.get("回复文本") or "").strip(),
            })
        return cleaned
    except Exception:
        return []


LOCATE_PROMPT = (
    "这是一个程序界面的截图。我有一个目标元素需要定位: 「{desc}」。\n"
    "请在该截图中找到这个元素(按钮/文本框/区域), 并给出它的中心像素坐标。\n"
    "严格只输出一行: <x>,<y>  (整数像素, 相对截图左上角)。\n"
    "如果截图中找不到该元素, 只输出: notfound"
)


def doubao_locate(shot_b64, desc, api_key, model, timeout=30):
    """豆包视觉: 在截图中定位指定元素 -> (x, y) 或 None
    入参: shot_b64(区域截图), desc(目标描述, 如"搜一搜窗口的查询按钮")
    返回: (x, y) 相对截图左上角 或 None(找不到/失败)"""
    try:
        import requests
        b64 = shot_b64
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        payload = {
            "model": model,
            "input": [{"role": "user", "content": [
                {"type": "input_image", "image_url": "data:image/webp;base64," + b64},
                {"type": "input_text", "text": LOCATE_PROMPT.format(desc=desc)},
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
        text = (text or "").strip().replace("<", "").replace(">", "")
        if not text or text.lower() == "notfound" or "," not in text:
            return None
        x, y = text.split(",", 1)
        return int(float(x.strip())), int(float(y.strip()))
    except Exception:
        return None
