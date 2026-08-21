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


class PointBase(BaseModel):
    name: str = ""
    x: str = ""
    y: str = ""
    remark: str = ""


class PointCreate(PointBase):
    pass


class PointUpdate(BaseModel):
    name: Optional[str] = None
    x: Optional[str] = None
    y: Optional[str] = None
    remark: Optional[str] = None


class Point(PointBase):
    id: int
