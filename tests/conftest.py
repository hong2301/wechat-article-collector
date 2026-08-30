# -*- coding: utf-8 -*-
"""接口矩阵测试共享 fixture:
- 每次测试复制 scripts/template_collector.db 到临时数据目录(隔离库, 不污染真实数据)
- 通过 WECHAT_COLLECTOR_DATA_DIR 环境变量让后端使用临时库(后端原生支持, 不改代码)
- 使用 fastapi TestClient 直连 app(不起真实端口)
"""
import os
import pathlib
import shutil
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TPL_DB = ROOT / "scripts" / "template_collector.db"

# ============ 隔离库(必须先于 import app.main 设置 env) ============
_TMPROOT = ROOT / ".tmp-tests"
_TMPROOT.mkdir(exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="collector_test_", dir=str(_TMPROOT))
os.environ["WECHAT_COLLECTOR_DATA_DIR"] = _TMP
os.makedirs(os.path.join(_TMP, "logs"), exist_ok=True)
if TPL_DB.exists():
    shutil.copy2(str(TPL_DB), os.path.join(_TMP, "collector.db"))
else:
    raise RuntimeError("缺少模板库: " + str(TPL_DB))

# 必须在 env 设置之后 import app(读取 data_dir)
from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session", autouse=True)
def _cleanup():
    yield
    # 测完清理临时目录
    import shutil
    shutil.rmtree(_TMP, ignore_errors=True)
    try:
        shutil.rmtree(str(ROOT / ".tmp-tests"), ignore_errors=True)
    except Exception:
        pass