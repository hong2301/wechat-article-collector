# -*- coding: utf-8 -*-
"""点位排序工具: 按依赖关系给一键设置排执行顺序
   - 规则: 被依赖越多的点位越靠前(它是别人的基础, 先设置)
   - 约束: 每个点位的依赖必须排在它自己前面(拓扑合法)
   - 算法: Kahn 拓扑排序 + 优先队列, 每步在"依赖已全部就绪"的候选中
           选"被依赖次数"最多者; 同分取 id 小者
   - 结果写入 sort_config(type='point'), 一键设置(_point_order_from_db)直接生效

用法:
    python scripts/tools/sort_points.py              # 默认 data/collector.db
    python scripts/tools/sort_points.py 模板库路径    # 指定库
    from scripts.tools.sort_points import compute_order, sort_and_write
"""
import heapq
import json
import os
import sqlite3
import sys

KEY = "depend_points"


def compute_order(rows):
    """rows: [(id, depend_points_json)] -> 排序后的 id 列表(拓扑合法)"""
    deps = {}          # id -> [依赖id...]
    dep_count = {}     # id -> 被依赖次数
    for pid, dp in rows:
        lst = json.loads(dp or "[]")
        deps[pid] = [int(x) for x in lst]
        dep_count[pid] = 0
    for pid, lst in deps.items():
        for d in lst:
            dep_count[d] = dep_count.get(d, 0) + 1
    indeg = {pid: len(lst) for pid, lst in deps.items()}   # 未就绪依赖数

    # Kahn: 候选=依赖全就绪(indeg==0), 按 被依赖数 desc, id asc
    heap = []
    for pid in deps:
        if indeg[pid] == 0:
            heapq.heappush(heap, (-dep_count[pid], pid))
    order = []
    while heap:
        _, pid = heapq.heappop(heap)
        order.append(pid)
        for other, lst in deps.items():
            if pid in lst:
                indeg[other] -= 1
                if indeg[other] == 0:
                    heapq.heappush(heap, (-dep_count[other], other))
    if len(order) != len(deps):
        raise ValueError("存在循环依赖, 无法拓扑排序")
    return order


def validate(order, deps):
    """校验: 每个点位依赖必须排在它自己前面; 返回 (是否合法, 错误信息)"""
    pos = {pid: i for i, pid in enumerate(order)}
    for pid, lst in deps.items():
        for d in lst:
            if pos.get(d, -1) >= pos[pid]:
                return False, f"{pid} 的依赖 {d} 排在它后面"
    return True, ""


def sort_and_write(db_path, echo=True):
    """读库 -> 计算排序 -> 校验 -> 写入 sort_config(type='point'); 返回新顺序"""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f"SELECT id, {KEY} FROM points").fetchall()
        order = compute_order(rows)
        deps = {pid: [int(x) for x in json.loads(dp or "[]")] for pid, dp in rows}
        ok, err = validate(order, deps)
        if not ok:
            raise ValueError(f"排序不合法: {err}")
        conn.execute("DELETE FROM sort_config WHERE type='point'")
        for i, pid in enumerate(order):
            conn.execute(
                "INSERT OR REPLACE INTO sort_config(record_id, sort_order, type) VALUES(?,?,?)",
                (pid, i, 'point'))
        conn.commit()
    finally:
        conn.close()
    if echo:
        _echo(db_path, order, deps)
    return order


def _echo(db_path, order, deps):
    conn = sqlite3.connect(db_path)
    name_of = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM points").fetchall()}
    conn.close()
    print(f"✔ {db_path} 排序完成(拓扑校验通过):")
    for i, pid in enumerate(order):
        print(f"  [{i:>2}] #{pid:>2} {name_of.get(pid, '?'):<14} 依赖{json.dumps(deps.get(pid, []))}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "collector.db")
    sort_and_write(target)