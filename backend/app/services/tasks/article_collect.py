# -*- coding: utf-8 -*-
"""任务子包: 文章采集(列表定位/保存/4指标/阅读数OCR/主流程)"""
from PIL import Image, ImageGrab
from .comment_collect import _collect_comments
import requests as _requests
from datetime import datetime
import ctypes
import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor

from ...core import computer as pc
from ...core import obs
from ...core import ocr as ocr_service
from ...core.common import (_read_point, _finish, _save_reads,
                            _extract_read_from_items, wait_page_stable)
from ...core.robot import (request_stop, clear_stop, stop_requested,
                           bind_tasks_echo, tasks_echo)
from ...database import get_conn
from ...services.doubao_api import recognize_interact as doubao_recognize_interact
from ...services.importer import extract_art_biz
from ...services.fetch_article import fetch_article, save_article_html
from .helpers import (_submit_bg, _done_bg, wait_bg_done)
from .wx_window import (init_wechat_window, search_window_init, search_query,
                        init_app_window, WECHAT_MAIN, WECHAT_APPEX,
                        APP_TITLE, APP_EXE)


@obs.timed("collect.list")
def article_list_wait_stable(date_start="", date_end="", biz="",
                             capture_4metrics=False, capture_read=False,
                             save_html=False, save_dir="",
                             max_comments=None, max_level1=None, max_level2=0):
    """文章列表识别循环: 进入 while 循环, 每次循环第一步检查页面稳定。
    前提: 搜一搜查询(search_query)已加载出公众号链接(本函数不判定, 但依赖其结果)。
    参数:
      date_start, date_end 采集时间范围(YYYY-MM-DD); 空字符串=全部(不限)
      biz              所属公众号 biz 代码(点击文章后数据采集用)
      capture_4metrics 是否采集4指标
      capture_read     是否采集阅读数量
      save_html        是否保存文章为本地HTML(含图片)
      save_dir         保存HTML根目录(空=默认D:/article_data)
    逻辑:
      while 循环(目前为占位, 后续补结束条件):
        1) 检查点位15-16区域页面是否稳定(失败不退出, 有兜底)
        2) 截图+OCR+分类得到 classified
        3) 截断处理: 若 classified 第一个点位不是时间点位,
           从上一轮的 classified 末尾向前找第一个时间点位借来, 插入本轮顶部(序号0)
           (第一轮无上一轮, 跳过)
        4) 日志输出本轮点位详细(序号/类型/文本/data)
    返回: (成功?, 说明文本)
    """
    logs = []

    p15 = _read_point(15)
    p16 = _read_point(16)
    if not p15 or not p16:
        logs.append("缺少点位15/16")
        return False, "; ".join(logs)
    x1, y1 = p15
    x2, y2 = p16
    logs.append(f"列表区域({x1},{y1})-({x2},{y2})")

    # 循环前: 页面稳定判断(100次机会, 每0.1s, 连续20次相同算稳定)
    ok0, info0 = wait_page_stable(x1, y1, x2, y2, same_need=20, timeout=100, interval=0.1)
    if not ok0:
        logs.append(f"初始页面未稳定(20次未达成): {info0}")
        return False, "; ".join(logs)
    logs.append(f"初始页面稳定: {info0}")


    # 稳定后: 截图点位15-16 => OCR => 识别"文章"标记(灰色系深色文字)并点击
    try:
        shot_path, _b64 = pc.screenshot(x1, y1, x2, y2, img_format="png")
        items = ocr_service.ocr(Image.open(shot_path))
        clicked = False
        for cx, cy, text, score, sbox, brightness in items:
            if not text or not text.strip():
                continue
            # 文章标记: 黑字白底(文本含"文章"; 颜色兜底兼容跨机黑/灰渲染)
            if "文章" not in text:
                continue
            with Image.open(shot_path) as _im:   # shot为区域截图, sbox直接相对
                cols = ocr_service.color_sort(_im, region=(
                    min(p[0] for p in sbox), min(p[1] for p in sbox),
                    max(p[0] for p in sbox), max(p[1] for p in sbox)))
            colset = {c for _, _, c in cols[:2]}
            if not cols or "白" not in colset or not ({"黑", "灰"} & colset):
                continue   # 非黑/灰字白底 -> 排除
            # 点击坐标: sbox 相对截图 -> 屏幕绝对(统一 ocr_abs, DPI按比例)
            _cx0, _cy0 = ocr_service.ocr_abs(_im, (x1, y1, x2, y2),
                                             min(p[0] for p in sbox), min(p[1] for p in sbox))
            _cx1, _cy1 = ocr_service.ocr_abs(_im, (x1, y1, x2, y2),
                                             max(p[0] for p in sbox), max(p[1] for p in sbox))
            click_x, click_y = (_cx0 + _cx1) // 2, (_cy0 + _cy1) // 2
            logs.append(f"识别文章标记: {text!r} @({click_x},{click_y})")
            tasks_echo(f"识别文章标记: {text!r} @({click_x},{click_y})")
            pc.mouse_click(click_x, click_y)
            clicked = True
            break
        if not clicked:
            logs.append("未识别到文章标记(黑字白底), 跳过点击")
            tasks_echo("未识别到文章标记(黑字白底), 跳过点击")
    except Exception as e:
        logs.append(f"文章标记识别失败: {e}")

    # while 循环(停止条件: 连续3次截图相同 = 无更多文章)
    prev_classified = None   # 上一轮的 classified(用于截断借时间)
    prev_shot_hash = None    # 上一轮截图md5(无更多文章判定)
    same_shot = 0            # 连续相同截图次数
    date_out_count = 0       # 连续在日期范围之后次数(有日期范围时)
    loop_n = 0

    def echo(msg):
        """本轮日志: 存 logs 并实时转发(打印 + 后端钩子)"""
        logs.append(msg)
        tasks_echo(msg)

    while True:
        if stop_requested():
            echo("收到停止请求, 退出识别循环")
            break
        loop_n += 1
        echo(f"--- 列表循环 {loop_n} ---")

        # 每次循环第一步: 页面稳定判断(失败不退出, 有兜底; 连续10次相同)
        ok, info = wait_page_stable(x1, y1, x2, y2, same_need=10)
        if ok:
            echo(f"第{loop_n}轮页面稳定: {info}")
        else:
            echo(f"第{loop_n}轮页面未稳定(继续, 用兜底): {info} ")

        # 流程一: 截图 -> OCR(得到原始识别数据)
        shot_path, _b64 = pc.screenshot(x1, y1, x2, y2, img_format="png")
        if not shot_path:
            echo(f"第{loop_n}轮截图失败")
            return False, f"第{loop_n}轮截图失败"
        try:
            img = Image.open(shot_path)
            items = ocr_service.ocr(img)
        except Exception as e:
            echo(f"第{loop_n}轮OCR失败: {e}")
            return False, f"第{loop_n}轮OCR失败: {e}"

        # 流程一点五: 检测"余下"加载更多按钮(灰底蓝字) -> 有则点击后重新截图+OCR
        try:
            btn = None
            for cx, cy, text, score, sbox, brightness in items:
                # 格式校验即可(余下N篇字样非常特异, 不需要颜色判定)
                if not text or not re.search(r"余下\s*\d+\s*篇", text):
                    continue
                _bx0, _by0 = ocr_service.ocr_abs(_im, (x1, y1, x2, y2),
                                                min(p[0] for p in sbox), min(p[1] for p in sbox))
                _bx1, _by1 = ocr_service.ocr_abs(_im, (x1, y1, x2, y2),
                                                max(p[0] for p in sbox), max(p[1] for p in sbox))
                btn = ((_bx0 + _bx1) // 2, (_by0 + _by1) // 2, text)
                break
            if btn:
                echo(f"识别到'余下'加载更多按钮: {btn[2]!r} @({btn[0]},{btn[1]}), 点击后重新截图")
                pc.mouse_click(btn[0], btn[1])
                time.sleep(0.3)
                echo("余下按钮已点击, 直接进入下一轮循环(跳过本轮分类/滚动)")
                continue
        except Exception as e:
            echo(f"第{loop_n}轮余下按钮检测失败: {e}")

        # 流程二: 分类 -> 截断借时间 -> 配对时间
        try:
            # 诊断: 本轮 OCR 原始文本(前20条), 确认日期文本是否被识别/可见
            _ocr_texts = [it[2] for it in items if it and len(it) > 2 and it[2]]
            echo(f"第{loop_n}轮OCR原始文本({len(_ocr_texts)}): {' | '.join(_ocr_texts[:20])}")
            classified = ocr_service.classify_items(items, box=(x1, y1, x2, y2), img=img)
        except Exception as e:
            echo(f"第{loop_n}轮分类失败: {e}")
            return False, f"第{loop_n}轮分类失败: {e}"

        # 截断处理: 本轮第一个点位不是时间点位 -> 向上一轮末尾借时间点位(序号0)
        if classified and prev_classified is not None and classified[0][1] != "time":
            borrowed = None
            # 从上一轮 classify 末尾往前找第一个时间点位
            for p in reversed(prev_classified):
                if p[1] == "time":
                    borrowed = p
                    break
            if borrowed is not None:
                # 把借来的时间点位以序号0插入本轮顶部
                borrowed_item = (0, borrowed[1], borrowed[2], borrowed[3], borrowed[4])
                classified.insert(0, borrowed_item)
                echo("截断: 从上一轮借时间点位插入本轮顶部(序号0)")

        # 配对时间: 按顺序遍历, 每个文章点位填入其前面最近的时间点位日期
        cur_t = None
        for p in classified:
            if p[1] == "time" and p[4].get("time"):
                cur_t = p[4]["time"]
            elif p[1] == "article":
                p[4]["time"] = cur_t   # 填配对时间(可能是None, 即无可用时间)

        # 日志输出本轮点位详细
        n_time = sum(1 for p in classified if p[1] == "time")
        n_article = sum(1 for p in classified if p[1] == "article")
        echo(f"第{loop_n}轮识别点位 {len(classified)} 个"
             f"(时间{n_time}/文章{n_article})")
        for seq, ptyp, ptxt, _pbox, pdata in classified:
            if ptyp == "time":
                echo(f"  时间点位[{seq}] {ptxt!r} 日期={pdata.get('time')}")
            else:
                echo(f"  文章点位[{seq}] {ptxt!r}"
                     f" 阅读={pdata.get('reads')} 赞={pdata.get('likes')}"
                     f" 配对时间={pdata.get('time')}")

        prev_classified = classified

        # 遍历文章点位: 时间在日期范围内(或时间为空=不确定) -> 点击文章点位
        # 点击坐标: (box最小x, box中心y), 用电脑控制模块 mouse_click
        s_d = date_start.replace("-", "/") if date_start else None
        e_d = date_end.replace("-", "/") if date_end else None
        for seq, ptyp, ptxt, pbox, pdata in classified:
            if ptyp != "article":
                continue
            t = pdata.get("time")
            should_click = False
            if not t:
                should_click = True              # 时间为空(不确定) -> 点击
            elif s_d and t < s_d or e_d and t > e_d:
                should_click = False             # 时间在范围外 -> 跳过
            else:
                should_click = True              # 在范围内 -> 点击
            if not should_click:
                echo(f"  跳过文章[{seq}] {ptxt!r} 时间{t} 不在范围")
                continue
            # box 四点取 最小x + 中心y(按y序文章中心)
            xs = [p[0] for p in pbox]
            ys = [p[1] for p in pbox]
            click_x = min(xs)
            click_y = int(sum(ys) / len(ys))
            echo(f"  点击文章[{seq}] {ptxt!r} 时间{t} @({click_x},{click_y})")
            pc.mouse_click(click_x, click_y)
            time.sleep(0.3)   # 点击后等待页面响应

            # 点击后: 采集该文章数据(获取链接+写文章表)
            ok_c, text_c = article_data_collect(
                collect_type=1, capture_4metrics=capture_4metrics,
                capture_read=capture_read, save_html=save_html, save_dir=save_dir, biz=biz,
                list_reads=pdata.get("reads"), list_likes=pdata.get("likes"),
                max_comments=max_comments, max_level1=max_level1, max_level2=max_level2)
            echo(f"  文章数据采集: {'成功' if ok_c else '失败'} | {text_c}")
            time.sleep(0.5)   # 采集完成间隔

        # 日期范围判断(有日期范围时才启用; 全部=空串跳过, 靠三次OCR兜底) 放在三次OCR相同判断上面
        if date_start or date_end:
            # 收集本轮 time 点位的标准日期(yyyy/mm/dd), 去除 None;
            # 排除序号0(=截断借来, 属于上一张图, 不参与本轮判定)
            times = [p[4].get("time") for p in classified
                     if p[0] != 0 and p[1] == "time" and p[4].get("time")]
            # 范围起止转 yyyy/mm/dd 便于字符串比较
            s = date_start.replace("-", "/") if date_start else None
            e = date_end.replace("-", "/") if date_end else None
            if times and any(not (s and t < s) and not (e and t > e) for t in times):
                # 存在范围内 -> 重置计数, 继续
                date_out_count = 0
                echo(f"第{loop_n}轮: 存在范围内文章, 继续")
            elif times:
                # 全不在范围内: 时间若比范围早(已滚过范围) -> 累计停止
                if any(s and t < s for t in times):
                    date_out_count = date_out_count + 1
                    echo(f"第{loop_n}轮: 时间点位已过日期范围(比范围早)({date_out_count}/2)")
                    if date_out_count >= 2:
                        echo("连续2次已过日期范围, 停止")
                        return False, "连续2次已过日期范围"
                else:
                    # 时间比范围晚(顶部还有更新的, 未滚到范围) -> 继续滚动
                    date_out_count = 0
                    echo(f"第{loop_n}轮: 时间点位在日期范围之后(未到范围), 继续")
            else:
                date_out_count = 0       # 本轮无时间点位, 不判定, 重置

        # 停止条件: 连续3轮OCR列表截图完全相同 -> 无更多文章, 停止(返回True)
        # 注意: 独立重新截图列表区域, 避免被各采集步骤的截图覆盖污染
        cur_shot_hash = None
        try:
            _sp, _ = pc.screenshot(x1, y1, x2, y2, img_format="png")
            if _sp:
                with open(_sp, "rb") as _f:
                    cur_shot_hash = hashlib.md5(_f.read()).hexdigest()
        except Exception:
            cur_shot_hash = None
        if prev_shot_hash == cur_shot_hash:
            same_shot = same_shot + 1
        else:
            same_shot = 1
        prev_shot_hash = cur_shot_hash
        if same_shot >= 5:
            echo(f"第{loop_n}轮: 连续5次列表截图相同, 判定无更多文章, 停止")
            return True, "无更多文章"

        # 滚动: 鼠标移到点位15, 触发滚动配置 id=3(向下)
        try:
            conn = get_conn()
            try:
                row = conn.execute("SELECT distance, direction FROM scrolls WHERE id=3").fetchone()
            finally:
                conn.close()
            s_dist = int(float(row["distance"])) if row else 0
            s_dir = row["direction"] if row else "down"
        except Exception:
            s_dist, s_dir = 0, "down"
        # 第二次确认截图相同(同2次)时: 滚动前先反向回滚 1/10 距离, 排除"假到底"
        # (页面未刷新/加载动画未触发造成截图不变), 回滚再回来可能触发新内容
        if same_shot == 2 and s_dist > 0:
            back_dir = "up" if s_dir == "down" else "down"
            pc.scroll(x1, y1, max(1, int(s_dist / 10)), direction=back_dir)
            echo(f"第{loop_n}轮: 第2次确认相同, 先向{back_dir}回滚 {max(1, int(s_dist/10))}px 再继续")
        if s_dist > 0:
            pc.scroll(x1, y1, s_dist, direction=s_dir)
            echo(f"第{loop_n}轮末尾: 在点位15({x1},{y1})向{s_dir}滚动 {s_dist}px")
        else:
            echo("滚动配置3无效, 跳过滚动")

    return True, "; ".join(logs)


def _save_article_base(link, biz, list_reads=None, list_likes=None):
    """步骤2: 写文章表(完整同步逻辑, 被整体异步提交)
    先抓元信息(标题/时间/原创/ip) -> 带元信息写表; 抓取失败仅写链接
    返回 (new_id, name, art, 文本); 失败 new_id=None"""
    logs = []
    try:
        art = extract_art_biz(link)
        tag = f"元数据#{art[:10]}"
        tasks_echo(f"[async:{tag}] 正在采集...")
        # 抓取文章元信息(网络请求, 失败不阻断, 失败仅写链接)
        meta = None
        try:
            meta = fetch_article(link)
        except Exception as e:
            logs.append(f"元信息抓取失败: {e}")
        if meta:
            a_title, a_date, a_original, a_ip = meta
            logs.append(f"元信息: {a_title} | {a_date or '无时间'} | {a_original} | {a_ip or '无ip'}")
        else:
            a_title, a_date, a_original, a_ip = "", "", "", ""
            logs.append("元信息抓取失败, 仅写入链接")

        conn = get_conn()
        try:
            acc = conn.execute("SELECT id, name FROM accounts WHERE biz=?", (biz,)).fetchone()
            account_id = acc["id"] if acc else None
            name = acc["name"] if acc else ""
            # 检查是否已存在(同biz+art_biz唯一), 存在则复用/跳过新增
            exists = conn.execute(
                "SELECT id FROM articles WHERE biz=? AND art_biz=?",
                (biz, art)).fetchone()
            if exists:
                new_id = exists["id"]
                # 已存在: 有元信息时补全缺失字段, 每次都刷新写入时间
                wt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if meta:
                    conn.execute(
                        "UPDATE articles SET title=?, date=?, original=?, ip=?, write_time=? WHERE id=?",
                        (a_title, a_date, a_original, a_ip, wt, new_id))
                    logs.append(f"文章已存在, 更新元信息 id={new_id}")
                else:
                    conn.execute("UPDATE articles SET write_time=? WHERE id=?", (wt, new_id))
                    logs.append(f"文章已存在, 复用 id={new_id}")
            else:
                wt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cur = conn.execute(
                    "INSERT INTO articles(account_id, name, date, title, original, ip, art_biz, biz, write_time) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (account_id, name, a_date, a_title, a_original, a_ip, art, biz, wt))
                new_id = cur.lastrowid
                logs.append(f"已写入文章表 id={new_id}")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logs.append(f"写入文章表失败: {e}")
        return None, "", "", "; ".join(logs)

    # 列表页识别到的阅读数/点赞先更新
    if list_reads is not None or list_likes is not None:
        try:
            conn = get_conn()
            try:
                if list_reads is not None and list_likes is not None:
                    conn.execute("UPDATE articles SET reads=?, likes=? WHERE id=?",
                                 (list_reads, list_likes, new_id))
                    logs.append(f"列表阅读/赞: {list_reads}/{list_likes} 已写入 id={new_id}")
                elif list_reads is not None:
                    conn.execute("UPDATE articles SET reads=? WHERE id=?", (list_reads, new_id))
                    logs.append(f"列表阅读: {list_reads} 已写入 id={new_id}")
                else:
                    conn.execute("UPDATE articles SET likes=? WHERE id=?", (list_likes, new_id))
                    logs.append(f"列表赞: {list_likes} 已写入 id={new_id}")
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logs.append(f"列表阅读/赞写入失败: {e}")

    tasks_echo(f"[async:{tag}] 采集完成, 文章已写入 id={new_id}")
    return new_id, name, art, "; ".join(logs)


def _save_html_block(link, name="", tag="", base_dir=None):
    """步骤3: 保存文章为本地HTML(公众号分类目录, 含图片本地化) - 独立流程
    后台异步执行(save_article_html 内含网络请求), 完成后回调日志"""
    if not tag:
        try:
            tag = f"保存Html#{extract_art_biz(link)[:10]}"
        except Exception:
            tag = "保存Html"
    tasks_echo(f"[async:{tag}] 正在保存...")
    try:
        html_path, info = save_article_html(link, account_name=name, base_dir=base_dir)
        ok_txt = "成功: " + info if html_path else "失败: " + info
        tasks_echo(f"[async:{tag}] {ok_txt}")
    except Exception as e:
        tasks_echo(f"[async:{tag}] 异常: {e}")

def _bg_ai_metrics(shot_b64, api_key, model, biz, art):
    """后台线程任务: 豆包识图4指标(网络请求) -> 更新文章数据
    成功写指标值(按biz+art_biz匹配)"""
    tag = f"4指标#{art[:10]}"
    try:
        metrics = None
        if shot_b64 and api_key and model:
            tasks_echo(f"[async:{tag}] 正在豆包识图...")
            metrics = doubao_recognize_interact(shot_b64, api_key, model)
            if metrics is not None:
                tasks_echo(f"[async:{tag}] 点赞{metrics[0]} 转发{metrics[1]} 喜欢{metrics[2]} 留言{metrics[3]}")
            else:
                tasks_echo(f"[async:{tag}] 识图失败")
        else:
            tasks_echo(f"[async:{tag}] 未配置AI模型或截图失败")

        # 更新文章数据: 成功写指标值
        data = {"biz": biz, "art_biz": art}
        if metrics is not None:
            data.update({
                "likes": str(metrics[0]), "forwards": str(metrics[1]),
                "favorites": str(metrics[2]), "comments": str(metrics[3]),
            })
        r = _requests.put(
            "http://127.0.0.1:8000/api/accounts/articles-by-biz/save",
            json=data, timeout=15,
        )
        if r.status_code == 200:
            try:
                _upd = (r.json() or {}).get("updated", 0)
            except Exception:
                _upd = "?"
            tasks_echo(f"[async:{tag}] 数据已更新(命中{_upd}行, art={art})")
        else:
            tasks_echo(f"[async:{tag}] 更新失败: HTTP {r.status_code}")
    except Exception as e:
        tasks_echo(f"[async:{tag}] 异常: {e}")


def _collect_metrics(biz, art):
    """4指标采集: 截图30/31区域(主线程) -> 豆包识图异步提交(网络, 不阻塞)
    截图后立即返回, 识图与更新由后台线程完成"""
    # 实时输出: 每步直接 tasks_echo
    p30 = _read_point(30)   # 4指标区域左上
    p31 = _read_point(31)   # 4指标区域右下
    shot_b64 = None
    if p30 and p31:
        # 页面稳定判断(30/31区域, 50次机会, 连续15次相同判稳定; 不稳定也继续执行)
        ok_stable, info = wait_page_stable(
            p30[0], p30[1], p31[0], p31[1], same_need=15, timeout=50, interval=0.1)
        tasks_echo(f"4指标: 页面稳定={ok_stable}({info})")
        try:
            shot_path, shot_b64 = pc.screenshot(
                p30[0], p30[1], p31[0], p31[1], img_format="png", as_base64=True)
            if not shot_b64:
                tasks_echo("4指标区域截图失败")
                shot_b64 = None
        except Exception as e:
            tasks_echo(f"4指标区域截图失败: {e}")
            shot_b64 = None
    else:
        tasks_echo("缺少点位30/31(4指标区域), 跳过4指标")
        shot_b64 = None

    # 从 ai_model 表取 key + 模型; 未配置则跳过识图只留截图
    api_key = ""
    model = ""
    try:
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT api_key, model_id FROM ai_model ORDER BY id LIMIT 1").fetchone()
            if row:
                api_key = row["api_key"] or ""
                model = row["model_id"] or ""
        finally:
            conn.close()
    except Exception:
        pass

    # 豆包识图+写表整体异步提交(网络耗时, 不阻塞主流程)
    _submit_bg(_bg_ai_metrics, shot_b64, api_key, model, biz, art)


def _bg_reads_ocr(png_path, box, biz, art):
    """后台线程任务: 阅读数截图OCR识别(耗时) -> 识别到写文章表
    独立异步执行, 不阻塞主流程; 日志实时转发"""
    tag = f"阅读数#{art[:10]}"
    try:
        img = Image.open(png_path).convert("RGB")
        items = ocr_service.ocr(img)
        reads = _extract_read_from_items(items, box, img=img)
        if reads is not None:
            tasks_echo(f"[async:{tag}] 识别到阅读数 {reads}")
            _save_reads(biz, art, reads)
        else:
            tasks_echo(f"[async:{tag}] OCR未找到'阅读'+数字或颜色不符")
    except Exception as e:
        tasks_echo(f"[async:{tag}] 阅读数OCR异常: {e}")


def _collect_reads(collect_type, link, biz, art):
    """采集阅读数: 滚到底->Ctrl+R刷新->稳定检测OCR识别
    写库按 biz+art_biz 匹配, 不依赖写表结果; 列表页已识别到阅读数时主函数跳过高不此调用"""
    # 实时输出: 每步直接 tasks_echo
    p15 = _read_point(15)
    if not p15:
        tasks_echo(f"[warn] 阅读数: 缺少点位15={bool(p15)}, 跳过阅读数采集")
        return
    # 1) 鼠标移到文章列表左上(点位15), 向下滚动5000px(0.5s内完成)
    pc.scroll(p15[0], p15[1], 50000, direction="down", duration=0.5)
    tasks_echo("阅读数: 在点位15滚动5000px")
    time.sleep(0.5)
    # 2) Ctrl+R 刷新当前页(刷新后阅读数区域可见), 等0.8s
    pc.ctrl_key("R")
    tasks_echo("阅读数: Ctrl+R 刷新")
    time.sleep(0.8)
    # 3) 刷新后: 页面稳定检测(点位32/33区域, 50次机会, 连续20次相同) -> OCR提取阅读数
    p32 = _read_point(32)
    p33 = _read_point(33)
    if not (p32 and p33):
        tasks_echo("缺少点位32/33(阅读数区域), 跳过阅读数识别")
    else:
        ok_stable, info = wait_page_stable(
            p32[0], p32[1], p33[0], p33[1], same_need=20, timeout=50, interval=0.1)
        if not ok_stable:
            # 未稳定也继续: 页面可能仍在加载/动, 不等稳定直接截图识别
            tasks_echo(f"阅读数: 结果页未稳定({info}), 继续尝试识别...")
        # 稳定或未稳定: 都截图 -> OCR识别丢后台异步, 识别到写文章表
        png_path, b64 = pc.screenshot(
            p32[0], p32[1], p33[0], p33[1], img_format="png", as_base64=True)
        if not b64:
            tasks_echo("阅读数: 稳定后截图失败")
        else:
            tasks_echo("阅读数: 截图完成, OCR识别后台进行...")
            _submit_bg(_bg_reads_ocr, png_path, (p32[0], p32[1]), biz, art)


@obs.timed("collect.article")
def article_data_collect(collect_type=0, capture_4metrics=False, capture_read=False,
                         save_html=False, save_dir="", biz="", list_reads=None, list_likes=None,
                         max_comments=None, max_level1=None, max_level2=0):
    """文章数据采集(编排主函数, 各块拆分到 _save_article_base
    /_collect_metrics/_collect_reads/_collect_comments; 复制链接逻辑留本函数)。
    参数:
      collect_type / capture_4metrics / capture_read / save_html / save_dir
      biz / list_reads / list_likes 同前
      max_comments     文章最大评论采集数(None=无限)
      max_level1       一级评论采集数(None=无限)
      max_level2       每级二级评论采集数(0=不采二级, None=无限)
    流程: 复制链接 -> 提取art_biz -> 写表(异步) -> 保存Html(异步)
    -> 4指标 -> 阅读数 -> 评论(需阅读数点位); 统一出口 _finish(Ctrl+W)。
    异步设计: 写表/保存Html/豆包识图/阅读数OCR 丢线程池, 主流程不阻塞网络耗时。
    """
    logs = []
    copy_seen = False   # 标志: 是否成功拿到链接(点到过复制按钮/打开过文章页); 成功才True, 轮尽仍False

    def step(msg):
        """步骤日志: 实时转发(带[step]标记) + 入汇总"""
        logs.append(msg)
        tasks_echo(f"[step] {msg}")

    if collect_type == 0:
        step("触发类型不确定, 无法采集")
        return _finish(logs, copy_seen, False, "触发类型不确定, 无法采集")

    # 1) 获取复制链接(2次机会): 点18(3点菜单) -> 点27(复制链接) -> 读剪贴板60次
    #    (不依赖点位28/29: 不再截图OCR检测'复制'字样, 点18后直接点27再读剪贴板验证)
    COPY_TRIES = 2          # 复制链接最大尝试次数(想改 5 次只需改这里)
    p18 = _read_point(18)   # 文章右上角3点
    p27 = _read_point(27)   # 点击复制链接
    if not p18 or not p27:
        step("缺少点位18/27(3点/复制链接)")
        return _finish(logs, copy_seen, False, "缺少点位18/27(3点/复制链接)")
    link = None
    for _try in range(1, COPY_TRIES + 1):
        step(f"--- 复制链接 第{_try}次 ---")
        pc.clear_clipboard()
        step(f"点击点位18(3点)({p18[0]},{p18[1]})")
        pc.mouse_click(p18[0], p18[1])
        time.sleep(0.5)   # 等菜单弹出
        # 直接点击复制链接按钮(点位27), 然后读剪贴板验证
        step(f"点击点位27(复制链接)({p27[0]},{p27[1]})")
        pc.mouse_click(p27[0], p27[1])
        for _i in range(1, 60):
            time.sleep(0.1)
            v = pc.read_clipboard_text()
            if v:
                link = v
                break
        step(f"已复制链接: {link[:60]}" if link else "未读取到剪贴板链接")
        if not link:
            # 未读到: 点击右半屏中点(收起当前3点菜单), 等0.5s, 清剪贴板后进入下一次尝试
            _sw = ctypes.windll.user32.GetSystemMetrics(0)
            _sh = ctypes.windll.user32.GetSystemMetrics(1)
            _mx, _my = int(_sw * 3 / 4), int(_sh / 2)
            step(f"未读到链接, 点击右半屏中点({_mx},{_my})收起菜单")
            pc.mouse_click(_mx, _my)
            time.sleep(1.0)   # 等菜单收起稳定, 下一轮重新点3点
        else:
            copy_seen = True    # 拿到链接=确实打开过文章页(收尾 Ctrl+W 关闭文章页合理)
            break   # 已拿到链接, 跳出
    if not link:
        step(f"{COPY_TRIES}次复制链接均未获取到, 本轮结束")
        pc.mouse_click(p18[0], p18[1])
        return _finish(logs, copy_seen, False, "未获取到链接")

    # art_biz 同步提取(供 4指标/阅读数 使用, 不依赖写表)
    art = extract_art_biz(link)
    if not art:
        step("链接提取art_biz失败")
        return _finish(logs, copy_seen, False, "链接提取art_biz失败")

    # 2) 写文章表(完整流程: 抓元信息->写表, 整体异步提交, 不阻塞后续)
    _submit_bg(_save_article_base, link, biz, list_reads, list_likes)

    # 3) 保存Html(独立流程, 并行异步)
    if save_html:
        _submit_bg(_save_html_block, link, base_dir=save_dir)  # 开始/完成日志由后台函数输出

    # 4) 4指标(开启时)
    if capture_4metrics:
        tasks_echo("[step] 正在采集4指标...")
        _collect_metrics(biz, art)

    # 5) 采集阅读数(开启且列表无阅读数时)
    # 列表页已识别到阅读数时不再重复采集
    if capture_read and list_reads is None:
        tasks_echo("[step] 正在采集阅读数...")
        _collect_reads(collect_type, link, biz, art)

    # 6) 采集评论(3个采集参数不全0时, 在阅读数之后)
    if not (max_comments == 0 and max_level1 == 0 and max_level2 == 0):
        tasks_echo("[step] 正在采集评论...")
        _collect_comments(collect_type, link, art, biz,
                          max_comments=max_comments, max_level1=max_level1, max_level2=max_level2)

    # 细节已实时输出, 最终只返回状态摘要
    return _finish([], copy_seen, True, "采集完成")
__all__ = ["init_wechat_window", "search_window_init", "search_query",
           "article_list_wait_stable", "init_app_window",
           "article_data_collect",
           "request_stop", "clear_stop", "stop_requested",
           "bind_tasks_echo", "tasks_echo"]
