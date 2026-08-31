# -*- coding: utf-8 -*-
"""冲突软件接口: 检测本机冲突软件 / 关闭冲突进程 / 展示冲突表
采集/一键设置/单点自动设置/快速开始 开始前由前端统一检测并提示"""
import json
import subprocess

from fastapi import APIRouter

from ..services import conflict_check
from ..repositories import settings_repo  # noqa: F401  (保持风格占位)

router = APIRouter(prefix="/api/conflicts", tags=["conflicts"])


@router.get("/check")
def check():
    """检测本机冲突软件: {ok: 无冲突?, conflicts: [...], }"""
    ok, conflicts = conflict_check.check_conflicts()
    return {"ok": ok, "conflicts": conflicts}


@router.get("")
def list_all():
    """冲突软件表全部条目(供前端展示/编辑)"""
    return {"items": conflict_check.list_conflicts()}


@router.post("/kill")
def kill(names: dict):
    """关闭指定冲突软件的命中进程(表内配置软件, 安全白名单)
    参数: {"names": ["有道翻译", ...]} 或 全空=关闭全部冲突
    返回: {ok, killed: [{name, pids}], failed: [{name, pids}]}
    """
    want = set((names or {}).get("names") or [])
    ok_all, conflicts = conflict_check.check_conflicts()
    killed, failed = [], []
    for c in conflicts:
        if want and c["name"] not in want:
            continue
        pids = c.get("matched_pids") or []
        if not pids:
            continue
        bad = []
        for pid in pids:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, timeout=15, check=False)
            except Exception:
                bad.append(pid)
        (failed if bad else killed).append({"name": c["name"], "pids": [p for p in pids if p not in bad]})
    return {"ok": not failed, "killed": killed, "failed": failed}