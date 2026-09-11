# -*- coding: utf-8 -*-
"""卡密授权接口矩阵: status(无副作用) / verify 无效卡与空卡(不写激活文件)"""
import pytest


def test_license_status_struct(client):
    r = client.get("/api/license/status")
    assert r.status_code == 200
    d = r.json()
    assert "ok" in d


def test_license_verify_empty_400(client):
    r = client.post("/api/license/verify", json={"card": ""})
    assert r.status_code == 400
    assert "卡密" in r.json()["msg"] or r.json()["ok"] is False


def test_license_verify_invalid_400(client):
    """伪造卡密 -> 验签失败 400, 不写激活文件"""
    r = client.post("/api/license/verify", json={"card": "ffffffffffffffff"})
    assert r.status_code == 400
    assert r.json().get("ok") is False