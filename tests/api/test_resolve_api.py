# -*- coding: utf-8 -*-
"""链接解析接口: resolve-name(非mp链接本地拒绝, 不走网络)"""
import pytest


def test_resolve_name_invalid_422(client):
    """非 mp.weixin.qq.com 链接 -> 直接 422(不走网络请求, 安全)"""
    r = client.get("/api/resolve-name", params={"link": "https://example.com/not-mp"})
    assert r.status_code == 422


def test_resolve_name_empty_422(client):
    r = client.get("/api/resolve-name", params={"link": ""})
    assert r.status_code == 422


@pytest.mark.manual
def test_resolve_name_real_manual(client):
    """真实微信文章链接走网络解析, 手动跑"""