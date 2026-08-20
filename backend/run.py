# -*- coding: utf-8 -*-
"""后端启动入口: python backend/run.py"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
