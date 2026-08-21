# -*- coding: utf-8 -*-
"""FastAPI 入口"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .routers import accounts, resolve_api, points

app = FastAPI(title="微信公众号采集器后端", version="3.1.0")

# CORS: 允许前端(localhost:3000 / Electron)访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(accounts.router)
app.include_router(resolve_api.router)
app.include_router(points.router)
