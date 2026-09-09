# -*- coding: utf-8 -*-
"""冲突软件接口矩阵: check/list(读本机进程, 无副作用) / kill(仅假名, 不真杀)"""
import pytest


def test_conflicts_check_struct(client):
    r = client.get("/api/conflicts/check")
    assert r.status_code == 200
    d = r.json()
    assert "ok" in d and "conflicts" in d and isinstance(d["conflicts"], list)


def test_conflicts_list_struct(client):
    r = client.get("/api/conflicts")
    assert r.status_code == 200
    d = r.json()
    assert "items" in d and isinstance(d["items"], list)
    assert len(d["items"]) >= 1          # 表内至少内置常用冲突软件


def test_conflicts_kill_nonexist_safe(client):
    """传入不存在的软件名 -> 不匹配任何进程, 不真杀, 返回 ok=True"""
    r = client.post("/api/conflicts/kill", json={"names": ["__不存在的软件__"]})
    assert r.status_code == 200
    d = r.json()
    assert "killed" in d and "failed" in d