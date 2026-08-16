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


# ========== 评论区识别 ==========


COMMENTS_PROMPT = """\
请从这张微信公众号文章评论区截图中提取所有可见评论，严格以JSON数组输出。
每条评论为一个对象，字段如下：
{
  "名称": "用户名",
  "地区": "IP属地",
  "时间": "评论时间",
  "点赞数量": "点赞数或0",
  "正文": "评论文本内容",
  "层级": 1或2,
  "是否缩进": "该评论相对最左边评论是否向右缩进,是或否",
  "是否置顶": "是"或"否",
  "是否作者回复": "是"或"否",
  "是否作者点赞": "是"或"否",
  "回复文本": "如果正文含'回复某某某：'则填写'回复某某某：'前缀，否则留空"
}

识别规则：
1. 【层级/缩进判断是重点】
   - 一级评论：名称行在评论区最左边，没有缩进
   - 二级评论：整条评论（头像+名称+正文）相对一级评论**明显向右缩进**，"是否缩进"填"是"
   - 逐条对比：该评论名称行的左边缘是否比最靠左评论的名称行明显靠右
   - 有缩进→层级填2，无缩进→层级填1
2. 每条评论右下角有"回复"和"..."按钮（灰色小字），不要提取这些按钮文字
3. 置顶标签：名称行出现绿色"置顶"二字
4. 作者标签：名称行出现绿色"作者"二字，表示该评论是文章作者发的
5. 作者回复：若该评论正文行下有绿色"作者回复"标记则为"是"
6. 作者点赞：评论正文下有绿色"作者点赞"标记则为"是"
7. "回复"标签：评论文本中若含"回复某某某：评论文本"，"回复某某某："前缀填入"回复文本"字段
8. 点赞数：名称行最右侧小拇指图标旁边的数字，无数字则为0

输出顺序：从上到下，一级评论后紧跟它的二级评论（缩进的）再跟下一条一级评论。
只输出JSON数组，不要输出其他说明文字。数组为空时输出[]。"""


def doubao_extract_comments(shot_b64, api_key, timeout=30):
    """调用豆包识图，从评论区截图提取评论数据
    返回: list[dict]  每个dict包含 名称/地区/时间/点赞数量/正文/层级/
          是否置顶/是否作者回复/是否作者点赞/回复文本; 失败返回 []"""
    try:
        import requests
        import json as _json
        b64 = shot_b64
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        payload = {
            "model": DOUBAO_MODEL,
            "input": [{"role": "user", "content": [
                {"type": "input_image", "image_url": "data:image/webp;base64," + b64},
                {"type": "input_text", "text": COMMENTS_PROMPT},
            ]}],
        }
        headers = {"Authorization": "Bearer " + api_key,
                   "Content-Type": "application/json"}
        resp = requests.post(DOUBAO_URL, headers=headers, json=payload, timeout=timeout)
        if resp.status_code != 200:
            log(f"豆包评论识别HTTP {resp.status_code}")
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
        # 提取JSON数组（兼容模型可能包裹在```json...```中）
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            return []
        result = _json.loads(m.group(0))
        if not isinstance(result, list):
            return []
        # 过滤/清洗
        cleaned = []
        for item in result:
            if not isinstance(item, dict):
                continue
            name = (item.get("名称") or "").strip()
            if not name:
                continue
            # 层级: 优先"是否缩进"=是→2级; 否则按"层级"字段
            _indent = str(item.get("是否缩进", "")).strip()
            _lvl = 2 if ("是" in _indent) else int(item.get("层级") or 1)
            if _lvl not in (1, 2):
                _lvl = 1
            cleaned.append({
                "名称": name,
                "地区": (item.get("地区") or "").strip(),
                "时间": (item.get("时间") or "").strip(),
                "点赞数量": str(item.get("点赞数量") or "0").strip(),
                "正文": (item.get("正文") or "").strip(),
                "层级": _lvl,
                "是否置顶": "是" if "是" in str(item.get("是否置顶", "")) else "否",
                "是否作者回复": "是" if "是" in str(item.get("是否作者回复", "")) else "否",
                "是否作者点赞": "是" if "是" in str(item.get("是否作者点赞", "")) else "否",
                "回复文本": (item.get("回复文本") or "").strip(),
            })
        return cleaned
    except Exception as e:
        log(f"豆包评论识别异常: {e}")
        return []


__all__ = ["DOUBAO_URL", "DOUBAO_MODEL", "DOUBAO_PROMPT",
           "_parse_interact_text", "doubao_recognize_interact",
           "COMMENTS_PROMPT", "doubao_extract_comments"]
