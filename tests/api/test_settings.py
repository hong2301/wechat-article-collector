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


def test_wechat_version_builtin(client):
    """微信基准版本 = 内置硬编码常量(version_info), 不再存库/无写接口"""
    g = client.get("/api/settings/wechat-version").json()
    assert g["version"], "应返回内置微信基准版本"
    # 写接口已删除(硬编码, 数据库剔除)
    r = client.post("/api/settings/wechat-version", json={"version": "4.1.13.12"})
    assert r.status_code == 405
    assert client.get("/api/settings/wechat-version").json()["version"] == g["version"]


@pytest.mark.manual
def test_wechat_status_detect(client):
    """依赖本机微信, 手动跑"""
    d = client.get("/api/settings/wechat-status").json()
    assert "running" in d

# ========== 补齐: 存储路径/版本/系统控制(无屏幕动作可自动测) ==========

def test_save_dir_roundtrip(client):
    r = client.post("/api/settings/save-dir", json={"dir": "D:/e2e-save"})
    assert r.status_code == 200 and r.json()["ok"] is True
    g = client.get("/api/settings/save-dir").json()
    assert g["dir"] == "D:/e2e-save"


def test_app_version(client):
    d = client.get("/api/settings/app-version").json()
    assert d["version"], "应返回内置程序版本"


def test_open_downloads_mock(client, monkeypatch):
    """open-downloads 会 os.startfile 打开资源管理器 -> mock 掉, 仅验目录创建与返回"""
    import os as _os
    monkeypatch.setattr(_os, "startfile", lambda p: None)
    r = client.post("/api/settings/open-downloads", params={"sub": ""})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["dir"]


def test_launch_wechat_notfound_mock(client, monkeypatch):
    """无微信安装路径场景(mock isfile=False) -> ok=False 未找到(不真启动)"""
    import os as _os
    monkeypatch.setattr(_os.path, "isfile", lambda p: False)
    r = client.post("/api/settings/launch-wechat")
    assert r.status_code == 200 and r.json()["ok"] is False


def test_wechat_check_struct(client):
    """版本确认: 本地版本 + 网络试探; 只断言结构(db=内置基准版本)"""
    d = client.get("/api/settings/wechat-check").json()
    assert "db" in d and "local" in d and "online" in d


@pytest.mark.manual
def test_pick_dir_manual(client):
    """弹系统文件夹选择器(Tk), 手动跑"""


@pytest.mark.manual
def test_save_article_html_manual(client):
    """保存单篇HTML需网络拉取微信文章, 手动跑"""
