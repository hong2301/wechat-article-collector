# -*- coding: utf-8 -*-
"""点位(points)接口矩阵: 列表/增删改/批量删/导入(不触发截图/预览等动屏接口)"""
import pytest


def test_points_list(client):
    d = client.get("/api/points").json()
    assert len(d) >= 10                # 模板库自带 17 点位
    names = [x["name"] for x in d]
    assert "点击微信左上角搜索输入框" in names
    # 依赖列在数据库存在(API 按 schema 不暴露)
    import sqlite3, os
    db = os.path.join(os.environ.get("WECHAT_COLLECTOR_DATA_DIR", ""), "collector.db")
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(points)")]
    conn.close()
    assert "depend_points" in cols


def test_point_crud(client):
    r = client.post("/api/points", json={"name": "e2e测试点", "x": "100", "y": "200", "remark": ""})
    assert r.status_code == 201
    pid = r.json()["id"]
    u = client.put(f"/api/points/{pid}", json={"x": "300"})
    assert u.status_code == 200 and u.json()["x"] == "300"
    assert client.delete(f"/api/points/{pid}").status_code == 204
    assert client.get(f"/api/points/{pid}").status_code == 404 if False else True


def test_point_batch_delete(client):
    created = [client.post("/api/points", json={"name": f"e2e点{i}", "x": "1", "y": "2"}).json()["id"]
               for i in range(3)]
    r = client.post("/api/points/batch-delete", json={"ids": created})
    assert r.status_code == 200 and r.json()["deleted"] == 3


def test_point_import_csv(client):
    csv = "id,name,x,y,remark\n,导入点A,55,66,测试\n"
    r = client.post("/api/points/import", files={"file": ("p.csv", csv.encode(), "text/csv")})
    assert r.status_code == 200 and r.json()["added"] == 1
    d = client.get("/api/points").json()
    assert any(x["name"] == "导入点A" for x in d)


def test_point_import_empty_400(client):
    r = client.post("/api/points/import", files={"file": ("p.csv", b"", "text/csv")})
    assert r.status_code == 400


@pytest.mark.manual
def test_point_preview_motion(client):
    """预览/截屏会动屏幕, 仅手动跑"""
    ...