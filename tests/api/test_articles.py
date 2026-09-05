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