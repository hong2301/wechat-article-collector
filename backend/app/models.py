# -*- coding: utf-8 -*-
"""Pydantic 数据模型"""
from typing import Optional
from pydantic import BaseModel


class AccountBase(BaseModel):
    name: str
    biz: str = ""
    status: str = "pending"
    remark: str = ""


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    biz: Optional[str] = None
    status: Optional[str] = None
    remark: Optional[str] = None


class Account(AccountBase):
    id: int
    collected_count: int = 0
