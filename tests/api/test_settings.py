# -*- coding: utf-8 -*-
"""settings 接口矩阵: AI/微信版本(安全接口); 任务栏/目录选择等动屏接口标 manual"""
import pytest


def test_ai_settings_roundtrip(client):
    r = client.get("/api/settings/ai").json()
    assert "provider" in r and "api_key" in r and "models" in r
    post = client.post("/api/settings/ai", json={
        "provider": "doubao", "api_key": "k-e2e-123", "models": ["doubao-seed-2-0-mini-260428"]})
    assert post.status_code == 200 and post.json()["count"] == 1
    again = client.get("/api/settings/ai").json()
    assert again["api_key"] == "k-e2e-123"


def test_wechat_version_roundtrip(client):
    g = client.get("/api/settings/wechat-version").json()
    assert "version" in g
    r = client.post("/api/settings/wechat-version", json={"version": "4.1.13.12"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert client.get("/api/settings/wechat-version").json()["version"] == "4.1.13.12"
    # 空版本拒绝
    bad = client.post("/api/settings/wechat-version", json={"version": "  "})
    assert bad.json()["ok"] is False


@pytest.mark.manual
def test_wechat_status_detect(client):
    """依赖本机微信, 手动跑"""
    d = client.get("/api/settings/wechat-status").json()
    assert "running" in d