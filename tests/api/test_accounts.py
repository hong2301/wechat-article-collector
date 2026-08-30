# -*- coding: utf-8 -*-
"""公众号(accounts)接口矩阵: CRUD / 排序 / 导入(含 __biz 链接本地提码) / 搜索"""
import io
import pytest

GZH = {
    "name": "接口测试号",
    "link": "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=MzA4OTQ5NTk2Mw%3D%3D&scene=124",
    "expect_biz": "Mzg4NTY2NzUxMQ==",   # 唯一, 不与模板库已有序号冲突
}


def test_list_ok(client):
    # 模板库自带初始数据; 只断言返回结构正确
    d = client.get("/api/accounts?page=1&page_size=20").json()
    assert "total" in d and isinstance(d["items"], list)


def test_create(client):
    r = client.post("/api/accounts", json={
        "name": GZH["name"], "biz": GZH["expect_biz"], "status": "pending", "remark": ""})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == GZH["name"] and body["biz"] == GZH["expect_biz"]


def test_create_dup_biz_400(client):
    r = client.post("/api/accounts", json={"name": "重复号", "biz": GZH["expect_biz"]})
    assert r.status_code == 400  # biz 唯一


def test_update(client):
    d = client.get("/api/accounts?page=1&page_size=10").json()
    aid = d["items"][0]["id"]
    r = client.put(f"/api/accounts/{aid}", json={"remark": "e2e备注"})
    assert r.status_code == 200 and r.json()["remark"] == "e2e备注"
    # 改成模板库已有 biz 应 400(若有第二条)
    dup = client.put(f"/api/accounts/{aid}", json={"biz": "MzA4OTQ5NTk2Mw=="})
    assert dup.status_code == 400


def test_search_q(client):
    d = client.get("/api/accounts?page=0&q=接口测试").json()
    assert isinstance(d, list) and any(x["name"] == GZH["name"] for x in d)


def test_sort(client):
    d = client.get("/api/accounts?page=0").json()
    ids = [x["id"] for x in d]
    # 按传入顺序写排序 -> 列表顺序应与 payload 一致(并支持反转)
    r = client.put("/api/accounts/sort", json={"ids": ids})
    assert r.status_code == 200 and r.json()["count"] == len(ids)
    after = [x["id"] for x in client.get("/api/accounts?page=0").json()]
    assert after == ids
    r2 = client.put("/api/accounts/sort", json={"ids": list(reversed(ids))})
    assert r2.status_code == 200
    import time as _t
    _t.sleep(0.7)   # 列表接口 400ms 去重缓存, 等失效再读
    after2 = [x["id"] for x in client.get("/api/accounts?page=0").json()]
    assert after2 == list(reversed(ids))


def test_import_csv_with_biz_link(client):
    """导入: 名称+公众号链接(含__biz) -> 本地提 biz, 零网络请求, 直接入库"""
    csv = (
        "url,title,状态,公众号链接\n"
        "https://mp.weixin.qq.com/s/X7fAdvvZ-Gq_2SW19OKfVw,债文新说,pending,"
        "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=mTESTE2E0001==&scene=124\n"
        "https://mp.weixin.qq.com/s/abc123,天风研究,pending,"
        "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=mTESTE2E0002==\n"
    )
    r = client.post("/api/accounts/import",
                    files={"file": ("t.csv", csv.encode("utf-8"), "text/csv")})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    # 读取 SSE 到最后 done: 应全部成功(0 failed)
    body = r.text
    assert "failed\":0" in body or '"failed": 0' in body or body.count("ok\":true") >= 2
    # 且库里有这两条(本地提 biz 入库)
    d = client.get("/api/accounts?page=0&q=债文新说").json()
    assert d and d[0]["biz"] == "mTESTE2E0001=="


def test_import_empty_file(client):
    # 后端对空文件返回 SSE done(非400), 断言能正常收尾
    r = client.post("/api/accounts/import", files={"file": ("x.csv", b"", "text/csv")})
    assert r.status_code == 200 and "done" in r.text


def test_delete_clear(client):
    # 逐个删除后 total=0(clear 兜底)
    d = client.get("/api/accounts?page=0").json()
    for x in d:
        assert client.delete(f"/api/accounts/{x['id']}").status_code == 204
    r = client.delete("/api/accounts/clear")
    assert r.status_code == 200
    assert client.get("/api/accounts?page=1&page_size=5").json()["total"] == 0


def test_clear_all(client):
    client.post("/api/accounts", json={"name": "待清1", "biz": "mclear001=="})
    r = client.delete("/api/accounts/clear")
    assert r.status_code == 200 and r.json()["deleted"] >= 1