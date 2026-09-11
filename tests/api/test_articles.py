# -*- coding: utf-8 -*-
"""文章/评论(scrolls 只测 CRUD; articles 空库行为; 自动设置/采集动微信标 manual)"""
import pytest


def test_scrolls_crud(client):
    r = client.post("/api/scrolls", json={"name": "e2e滚动", "distance": "500", "point_id": 15,
                                          "direction": "down", "remark": ""})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert client.put(f"/api/scrolls/{sid}", json={"distance": "600"}).json()["distance"] == "600"
    assert client.delete(f"/api/scrolls/{sid}").status_code == 204


@pytest.mark.manual
def test_scroll_run_manual(client):
    """run 会真实滚动鼠标, 手动跑"""


def test_articles_empty_query(client):
    r = client.get("/api/accounts/articles-by-biz?biz=all&page=1&page_size=5").json()
    assert r["biz"] == "all" and "items" in r


def test_articles_create_dup(client):
    # 需要先有公众号(biz)——用模板库已有序号 MzA4OTQ5NTk2Mw==
    r = client.post("/api/accounts/articles-by-biz", json={
        "biz": "MzA4OTQ5NTk2Mw==", "link": "https://mp.weixin.qq.com/s/e2eTEST0001", "title": "e2e文章"})
    assert r.status_code == 201
    r2 = client.post("/api/accounts/articles-by-biz", json={
        "biz": "MzA4OTQ5NTk2Mw==", "link": "https://mp.weixin.qq.com/s/e2eTEST0001", "title": "e2e文章"})
    assert r2.status_code == 400   # 同 art_biz 唯一


def test_articles_by_biz_list(client):
    # 自建数据(不依赖模板遗留/其它用例顺序): 建号->建文章->查列表
    c = client.post("/api/accounts", json={"name": "e2e文章号", "biz": "marte2e01=="})
    assert c.status_code == 201
    client.post("/api/accounts/articles-by-biz", json={
        "biz": "marte2e01==", "link": "https://mp.weixin.qq.com/s/marte2e01AAAA", "title": "e2e标题"})
    d = client.get("/api/accounts/articles-by-biz?biz=marte2e01%3D%3D&page=1&page_size=5").json()
    assert d["name"] == "e2e文章号" and d["total"] >= 1 and d["items"][0]["title"] == "e2e标题"


@pytest.mark.manual
def test_collect_manual(client):
    """采集动微信/锁键鼠, 手动跑"""


@pytest.mark.manual
def test_autosetup_manual(client):
    """点位自动设置动微信/锁键鼠, 手动跑"""

# ========== 补齐: 文章更新/删除/导入SSE/日历/滚动导入/一键设置stop ==========

def _mk_gzh_and_article(client, tag):
    """建号+建文章, 返回 (biz, art_biz, artid)"""
    biz = f"mk{tag}=="
    c = client.post("/api/accounts", json={"name": f"补测号{tag}", "biz": biz, "status": "pending", "remark": ""})
    assert c.status_code == 201, c.text
    aid = c.json()["id"]
    a = client.post("/api/accounts/articles-by-biz", json={
        "biz": biz, "link": f"https://mp.weixin.qq.com/s/{tag}AAAAAA", "title": f"补测文章{tag}"})
    assert a.status_code == 201
    return biz, f"{tag}AAAAAA", aid


def test_save_article_put(client):
    biz, art, _ = _mk_gzh_and_article(client, "sav1")
    r = client.put("/api/accounts/articles-by-biz/save", json={
        "biz": biz, "art_biz": art, "reads": "999", "likes": "8"})
    assert r.status_code == 200
    assert r.json()["updated"] == 1
    # 回查列表确认 reads 已更新
    d = client.get(f"/api/accounts/articles-by-biz?biz={biz}&page=1&page_size=5").json()
    assert d["items"][0]["reads"] == "999"


def test_delete_article_by_biz_and_404(client):
    biz, art, _ = _mk_gzh_and_article(client, "del1")
    d = client.get(f"/api/accounts/articles-by-biz?biz={biz}&page=0").json()
    artid = d["articles"][0]["id"]
    assert client.delete(f"/api/accounts/articles-by-biz/{artid}", params={"biz": biz}).status_code == 204
    assert client.delete(f"/api/accounts/articles-by-biz/{artid}", params={"biz": biz}).status_code == 404


def test_delete_comments_empty_ok(client):
    r = client.delete("/api/accounts/comments", params={"ids": "1,2"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_scrolls_list_and_import(client):
    d = client.get("/api/scrolls").json()
    assert isinstance(d, list)
    csv = "滚动id,滚动名称,距离,点位id,方向,备注\n,补测滚动,500,15,down,\n"
    r = client.post("/api/scrolls/import", files={"file": ("s.csv", csv.encode(), "text/csv")})
    assert r.status_code == 200 and r.json()["added"] == 1
    names = [x["name"] for x in client.get("/api/scrolls").json()]
    assert "补测滚动" in names


def test_account_articles_struct(client):
    biz, art, aid = _mk_gzh_and_article(client, "art1")
    d = client.get(f"/api/accounts/{aid}/articles").json()
    assert d["articles"] and d["articles"][0]["art_biz"] == art


def test_account_calendar_struct(client):
    biz, art, aid = _mk_gzh_and_article(client, "cal1")
    d = client.get(f"/api/accounts/calendar/{aid}").json()
    assert "count" in d and "daily" in d


def test_delete_article_by_aid(client):
    biz, art, aid = _mk_gzh_and_article(client, "del2")
    d = client.get(f"/api/accounts/{aid}/articles").json()
    artid = d["articles"][0]["id"]
    assert client.delete(f"/api/accounts/{aid}/articles/{artid}").status_code == 204
    assert client.delete(f"/api/accounts/{aid}/articles/{artid}").status_code == 404


def test_import_articles_sse(client):
    biz, art, _ = _mk_gzh_and_article(client, "imp1")
    csv = "链接,标题,日期\nhttps://mp.weixin.qq.com/s/imp1BBBBBB,导入文,2026-09-01\n"
    r = client.post("/api/accounts/articles-by-biz/import", params={"biz": biz},
                    files={"file": ("a.csv", csv.encode(), "text/csv")})
    assert r.status_code == 200 and "event: done" in r.text


def test_import_comments_sse(client):
    biz, art, _ = _mk_gzh_and_article(client, "imp2")
    csv = "comment_biz,作者,内容,时间,级别\nimp2CCCC,测试者,好文,2026-09-01,1\n"
    r = client.post("/api/accounts/comments/import", params={"art_biz": art},
                    files={"file": ("c.csv", csv.encode(), "text/csv")})
    assert r.status_code == 200 and "event: done" in r.text


def test_autosetup_stop_safe(client):
    """无自动设置任务时 stop 安全返回"""
    r = client.post("/api/auto-setup/stop")
    assert r.status_code == 200 and "ok" in r.json()


@pytest.mark.manual
def test_autosetup_point_manual(client):
    """点位自动设置动微信/锁键鼠, 手动跑"""


@pytest.mark.manual
def test_autosetup_scroll_manual(client):
    """滚动自动设置动微信/锁键鼠, 手动跑"""


@pytest.mark.manual
def test_autosetup_runall_manual(client):
    """一键设置动微信/锁键鼠, 手动跑"""


@pytest.mark.manual
def test_autosetup_lock_manual(client):
    """输入锁定拦键鼠, 手动跑"""
