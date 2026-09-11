# -*- coding: utf-8 -*-
"""采集编排接口: task-state(读计数) / stop(无任务时安全) 可自动测; start/update(含评论采集) 动微信标 manual"""
import pytest


def test_task_state_struct(client):
    r = client.get("/api/collect/task-state")
    assert r.status_code == 200
    d = r.json()
    assert "running_count" in d and "running" in d
    assert d["running_count"] == 0 and d["running"] is False   # 测试环境无运行任务


def test_stop_safe(client):
    """无任务时调用 stop 应安全返回 ok"""
    r = client.post("/api/collect/stop")
    assert r.status_code == 200
    assert r.json().get("ok") is True


@pytest.mark.manual
def test_collect_start_manual(client):
    """真实采集动微信/锁键鼠, 手动跑"""


@pytest.mark.manual
def test_collect_update_manual(client):
    """单篇更新动微信, 手动跑"""


@pytest.mark.manual
def test_collect_comments_manual(client):
    """评论采集=单篇更新(update 接口 + 仅评论参数), 手动跑"""