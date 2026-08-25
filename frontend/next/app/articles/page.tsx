"use client";

import { useEffect, useRef, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import dayjs from "dayjs";
import { Table, Button, Typography, Space, Tag, message, Modal, Empty, Input, Tooltip, Progress, DatePicker, InputNumber, Spin, Switch, Select } from "antd";
import { ArrowLeftOutlined, DeleteOutlined, PlusOutlined, ImportOutlined, InboxOutlined, SearchOutlined, ClearOutlined, UpOutlined, DownOutlined, MessageOutlined, FolderOpenOutlined, DownloadOutlined, ReloadOutlined, FileExcelOutlined } from "@ant-design/icons";
import * as XLSX from "xlsx";
import PaginationBar, { calcPageSize } from "../components/PaginationBar";
import { hideTaskbar, showTaskbar } from "../components/taskbar";

const API = "http://127.0.0.1:8000/api/accounts";
const ART_PREFIX = "https://mp.weixin.qq.com/s/";

// 合并「起~止」为一体范围输入框
function NumRange({ value, onChange }: {
  value: [number | null, number | null];
  onChange: (v: [number | null, number | null]) => void;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", border: "1px solid #d9d9d9", borderRadius: 6, backgroundColor: "#fff", height: 22, padding: "0 2px" }}>
      <InputNumber size="small" variant="borderless" controls={false} min={0} placeholder="起"
        value={value[0] === null ? undefined : value[0]}
        onChange={(v) => onChange([v ?? null, value[1]])} style={{ width: 40 }} />
      <span style={{ color: "#bfc7cf", fontSize: 12, margin: "0 1px" }}>~</span>
      <InputNumber size="small" variant="borderless" controls={false} min={0} placeholder="止"
        value={value[1] === null ? undefined : value[1]}
        onChange={(v) => onChange([value[0], v ?? null])} style={{ width: 40 }} />
    </div>
  );
}

interface Article {
  id: number;
  title: string;
  date: string;
  art_biz: string;
  reads: string;
  likes: string;
  forwards: string;
  favorites: string;
  comments: string;
  write_time: string;
  original: string;
  ip: string;
  comment_count?: number;   // 实际采集评论数(comments表)
  comment_recog?: number;   // 识别出来的评论数
}

export default function ArticlePage() {
  const router = useRouter();
  const [biz, setBiz] = useState("");
  const [name, setName] = useState("");
  const [articles, setArticles] = useState<Article[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [sortInfo, setSortInfo] = useState<{ key: string; order: "ascend" | "descend" }>({ key: "acc_name", order: "ascend" });
  const [dateRange, setDateRange] = useState<[any, any] | null>(null);
  const [quickActive, setQuickActive] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(true);
  // 更新设置(与公众号页共享配置): 窗口分离/4指标/阅读数/保存Html
  const [windowSplit, setWindowSplit] = useState(true);
  const [capture4metrics, setCapture4metrics] = useState(false);
  const [captureRead, setCaptureRead] = useState(false);
  const [saveHtml, setSaveHtml] = useState(false);
  // 评论采集设置(独立key updateConfig)
  const [captureComments, setCaptureComments] = useState(false);
  const [maxComments, setMaxComments] = useState<number | null>(null);
  const [maxLevel1, setMaxLevel1] = useState<number | null>(null);
  const [maxLevel2, setMaxLevel2] = useState<number | null>(0);
  const [cfgLoaded, setCfgLoaded] = useState(false);   // 恢复完成才允许写回
  // 从localStorage恢复更新设置(独立key updateConfig)
  useEffect(() => {
    try {
      const d = JSON.parse(localStorage.getItem("updateConfig") || "{}");
      if (typeof d.window_split === "boolean") setWindowSplit(d.window_split);
      if (typeof d.capture_4metrics === "boolean") setCapture4metrics(d.capture_4metrics);
      if (typeof d.capture_read === "boolean") setCaptureRead(d.capture_read);
      if (typeof d.save_html === "boolean") setSaveHtml(d.save_html);
      if (typeof d.capture_comments === "boolean") setCaptureComments(d.capture_comments);
      if ("max_comments" in d) setMaxComments(d.max_comments);
      if ("max_level1" in d) setMaxLevel1(d.max_level1);
      if ("max_level2" in d) setMaxLevel2(d.max_level2);
      if (d.date_start && d.date_end) setDateRange([dayjs(d.date_start), dayjs(d.date_end)]);
      if (d.quick) setQuickActive(d.quick);
    } catch { /* 忽略 */ }
    setCfgLoaded(true);
  }, []);
  // 变更写回localStorage(恢复完成后生效, 避免初始默认值覆盖存储)
  useEffect(() => {
    if (!cfgLoaded) return;
    try {
      const d = JSON.parse(localStorage.getItem("updateConfig") || "{}");
      d.window_split = windowSplit; d.capture_4metrics = capture4metrics;
      d.capture_read = captureRead; d.save_html = saveHtml;
      d.capture_comments = captureComments; d.max_comments = maxComments;
      d.max_level1 = maxLevel1; d.max_level2 = maxLevel2;
      d.date_start = dateRange ? dateRange[0].format("YYYY-MM-DD") : "";
      d.date_end = dateRange ? dateRange[1].format("YYYY-MM-DD") : "";
      d.quick = quickActive;
      localStorage.setItem("updateConfig", JSON.stringify(d));
    } catch { /* 忽略 */ }
  }, [cfgLoaded, windowSplit, capture4metrics, captureRead, saveHtml, captureComments, maxComments, maxLevel1, maxLevel2, dateRange, quickActive]);
  const NUM_FIELDS = [
    { key: "reads", label: "阅读" },
    { key: "likes", label: "点赞" },
    { key: "forwards", label: "转发" },
    { key: "favorites", label: "喜欢" },
    { key: "comments", label: "评论" },
  ];
  const [ranges, setRanges] = useState<Record<string, [number | null, number | null]>>(
    Object.fromEntries(NUM_FIELDS.map((f) => [f.key, [null, null]]))
  );
  const [accFilter, setAccFilter] = useState<string[]>([]);  // 公众号多选(全部文章模式), 空=全选
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState(false);
  const [dlKey, setDlKey] = useState<string>("");   // 正在下载的文章art_biz(空=无下载中)
  const [kw, setKw] = useState("");
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [dlOpen, setDlOpen] = useState(false);           // 下载选中弹窗
  const [dlItems, setDlItems] = useState<{ art_biz: string; title: string; status: string; msg: string }[]>([]);
  const [dlCount, setDlCount] = useState(0);             // 已完成数
  const [dlRun, setDlRun] = useState(false);            // 下载中
  const dlAbortRef = useRef<AbortController | null>(null);  // 下载取消控制
  // 更新弹窗(单篇文章更新)
  const [updOpen, setUpdOpen] = useState(false);
  const [updStarted, setUpdStarted] = useState(false);
  const [updTask, setUpdTask] = useState<Article | null>(null);
  const [updLogs, setUpdLogs] = useState<string[]>([]);
  const [updQueue, setUpdQueue] = useState<Article[]>([]);   // 更新队列(单篇=1个)
  const [updIdx, setUpdIdx] = useState(0);                   // 当前队列下标
  const [updCount, setUpdCount] = useState(0);               // 已更新文章数
  const [updStartTs, setUpdStartTs] = useState(0);           // 开始时间戳
  const [updStartTime, setUpdStartTime] = useState("");     // 开始时间显示
  const [updSpeed, setUpdSpeed] = useState(0);               // 更新速度(篇/分)
  const updAbortRef = useRef<AbortController | null>(null);
  const [updStopped, setUpdStopped] = useState(false);   // 是否已停止(停止后按钮变关闭)
  const updLogRef = useRef<HTMLDivElement>(null);
  // 更新日志自动滚动
  useEffect(() => {
    if (updLogRef.current) updLogRef.current.scrollTop = updLogRef.current.scrollHeight;
  }, [updLogs]);
  // 更新速度: 每完成一篇重算
  useEffect(() => {
    if (updCount > 0 && updStartTs > 0) {
      const mins = (Date.now() - updStartTs) / 60000;
      setUpdSpeed(mins > 0 ? Math.round((updCount / mins) * 10) / 10 : 0);
    }
  }, [updCount]);
  const [addOpen, setAddOpen] = useState(false);
  const [newLink, setNewLink] = useState("");
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importingPct, setImportingPct] = useState(0);
  const [failedLinks, setFailedLinks] = useState<string[]>([]);
  const [dupRows, setDupRows] = useState<any[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const tableWrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const b = q.get("biz") || "";
    const n = q.get("name") || "";
    setBiz(b);
    if (n) setName(n);   // 立即显示公众号名, 不等接口
    load(b);             // biz 空=全部文章; 有值=该公众号文章
  }, []);

  // 测量表格容器高度 -> 行区滚动且底栏固定
  // 无日期的(新增)排最前(按id倒序), 有日期的按日期倒序
  function sortArticles(list: Article[]) {
    const noDate = list.filter((a) => !a.date).sort((a, b) => b.id - a.id);
    const hasDate = list.filter((a) => a.date).sort((a, b) => (new Date(b.date).getTime() - new Date(a.date).getTime()) || (b.id - a.id));
    return [...noDate, ...hasDate];
  }

  async function load(b: string) {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ biz: b, page: String(page), page_size: String(pageSize) });
      // 筛选参数
      if (dateRange) { qs.set("date_start", dateRange[0].format("YYYY-MM-DD")); qs.set("date_end", dateRange[1].format("YYYY-MM-DD")); }
      if (kw.trim()) qs.set("kw", kw.trim());
      for (const f of NUM_FIELDS) {
        const [lo, hi] = ranges[f.key];
        if (lo != null) qs.set(`min_${f.key}`, String(lo));
        if (hi != null) qs.set(`max_${f.key}`, String(hi));
      }
      if (accFilter.length && !accFilter.includes("__all__")) qs.set("accs", accFilter.join(","));
      // 排序(acc_name 映射后端 name)
      qs.set("order_by", sortInfo.key === "acc_name" ? "name" : sortInfo.key);
      qs.set("order_dir", sortInfo.order === "ascend" ? "asc" : "desc");
      const r = await fetch(`${API}/articles-by-biz?${qs.toString()}`);
      const d = await r.json();
      setName(d.name || "");
      const arts = d.items ?? d.articles ?? [];
      setTotal(d.total ?? (d.articles ? d.articles.length : 0));
      setArticles(sortArticles(arts));
      // 全部文章模式: 公众号多选默认全选
      if (b === "all") {
        const names = Array.from(new Set(arts.map((a: any) => a.acc_name || ""))).filter(Boolean) as string[];
        setAccFilter(["__all__"]);   // 默认选中'全部'
        void names;
      } else {
        setAccFilter([]);
      }
      setLoadErr(false);
    } catch { message.error("加载失败"); setLoadErr(true); }
    finally { setLoading(false); }
  }
  // 下载当前文章为本地HTML(保存到对应公众号文件夹)
  async function downloadHtml(a: Article) {
    if (!a.art_biz) { message.warning("该文章无art_biz"); return; }
    if (dlKey) { message.info("正在下载其他文章, 请稍候"); return; }
    const link = `https://mp.weixin.qq.com/s/${a.art_biz}`;
    setDlKey(a.art_biz);
    const hint = message.loading("正在下载...", 0);
    try {
      const d = await (await fetch("http://127.0.0.1:8000/api/settings/save-article-html", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ link, account_name: name || "" }),
      })).json();
      hint();
      if (d.ok) message.success("已保存: " + (d.info || d.path || ""));
      else message.error(d.error || "保存失败");
    } catch {
      hint();
      message.error("无法连接后端");
    } finally { setDlKey(""); }
  }
  // 下载选中文章: 弹窗显示进度, 逐篇保存HTML到公众号文件夹
  async function downloadSelected() {
    if (selectedKeys.length === 0) { message.warning("请先勾选要下载的文章"); return; }
    const rows = shown.filter((s) => selectedKeys.includes(s.id));
    if (rows.length === 0) return;
    const init = rows.map((r) => ({ art_biz: r.art_biz || "", title: (r.title || r.art_biz || "").slice(0, 24), status: "等待", msg: "" }));
    setDlItems(init); setDlCount(0); setDlOpen(true); setDlRun(true);
    dlAbortRef.current = new AbortController();
    let done = 0;
    for (let i = 0; i < rows.length; i++) {
      if (dlAbortRef.current?.signal.aborted) break;  // 已取消
      const a = rows[i];
      if (!a.art_biz) {
        setDlItems((p) => p.map((x, j) => j === i ? { ...x, status: "失败", msg: "无art_biz" } : x));
        continue;
      }
      if (dlAbortRef.current?.signal.aborted) break;
      setDlItems((p) => p.map((x, j) => j === i ? { ...x, status: "下载中" } : x));
      try {
        const link = `https://mp.weixin.qq.com/s/${a.art_biz}`;
        const resp = await fetch("http://127.0.0.1:8000/api/settings/save-article-html", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ link, account_name: name || "" }),
          signal: dlAbortRef.current?.signal,
        });
        const d = await resp.json();
        if (d.ok) setDlItems((p) => p.map((x, j) => j === i ? { ...x, status: "成功", msg: (d.info || "").slice(0, 60) } : x));
        else setDlItems((p) => p.map((x, j) => j === i ? { ...x, status: "失败", msg: d.error || "" } : x));
      } catch (e: unknown) {
        if ((e as Error)?.name === "AbortError") break;  // 用户取消
        setDlItems((p) => p.map((x, j) => j === i ? { ...x, status: "失败", msg: "无法连接后端" } : x));
      }
      done++;
      setDlCount(done);
    }
    setDlRun(false);
    const cancelled = dlAbortRef.current?.signal.aborted;
    if (cancelled) message.warning(`已取消, 完成 ${done} 篇`);
    else message.success(`下载完成: ${done} 篇`);
  }
  // 单篇更新: 打开更新确认弹窗(队列=1个)
  function openUpdate(a: Article) {
    setUpdQueue([a]);
    setUpdIdx(0);
    setUpdTask(a);
    setUpdStarted(false);
    setUpdLogs([]);
    setUpdOpen(true);
  }
  // 更新选中: 选中文章批量入队
  function openUpdateSelected() {
    if (selectedKeys.length === 0) { message.warning("请先勾选要更新的文章"); return; }
    const rows = shown.filter((s) => selectedKeys.includes(s.id));
    if (rows.length === 0) return;
    setUpdQueue(rows);
    setUpdIdx(0);
    setUpdTask(rows[0]);
    setUpdStarted(false);
    setUpdLogs([]);
    setUpdOpen(true);
  }
  // 确认更新: 按队列启动(多个串行完整更新流程)
  function confirmUpdate() {
    if (updQueue.length === 0) return;
    setUpdStopped(false);
    setUpdStarted(true);
    runUpd(0);
  }
  // 关闭更新弹窗: 收起界面 + 刷新文章列表(更新数据后重新拉取)
  function closeUpd() {
    setUpdOpen(false);
    reload();
  }
  // 停止更新: 通知后端中止 + 断开SSE, 按钮变关闭
  function stopUpdate() {
    fetch("http://127.0.0.1:8000/api/collect/stop", { method: "POST" }).catch(() => {});
    updAbortRef.current?.abort();
    setUpdStopped(true);
  }
  // 更新队列第 idx 个: 调后端 /api/collect/update(独立更新流程), done 后自动下一个
  function runUpd(idx: number) {
    const a = updQueue[idx];
    if (!a) {
      setUpdIdx(updQueue.length);   // 全部完成, 进度显示 N/N
      message.success("全部更新完成");
      return;
    }
    setUpdIdx(idx);
    setUpdTask(a);
    if (idx === 0) {
      setUpdStartTs(Date.now());
      setUpdStartTime(new Date().toLocaleString("zh-CN", { hour12: false }));
      setUpdCount(0); setUpdSpeed(0);
      setUpdLogs([`开始更新「${a.title || a.art_biz || ""}」`]);
    } else {
      setUpdLogs((p) => [...p, `--- 开始更新「${a.title || a.art_biz || ""}」(${idx + 1}/${updQueue.length}) ---`]);
    }
    if (!a.art_biz) { setUpdLogs((p) => [...p, "❌ 无文章链接"]); setUpdCount((c) => c + 1); runUpd(idx + 1); return; }
    const link = `https://mp.weixin.qq.com/s/${a.art_biz}`;
    const controller = new AbortController();
    updAbortRef.current = controller;
    const payload = {
      name: name || "",
      biz: biz || "",
      link,
      window_split: windowSplit,
      capture_4metrics: capture4metrics,
      capture_read: captureRead,
      save_html: saveHtml,
      save_dir: "",
      max_comments: captureComments ? maxComments : 0,
      max_level1: captureComments ? maxLevel1 : 0,
      max_level2: captureComments ? maxLevel2 : 0,
    };
    (async () => {
      let finished = false;
      try {
        const resp = await fetch("http://127.0.0.1:8000/api/collect/update", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload), signal: controller.signal,
        });
        if (!resp.ok || !resp.body) throw new Error("更新接口失败");
        const reader = resp.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let i2;
          while ((i2 = buf.indexOf("\n\n")) !== -1) {
            const block = buf.slice(0, i2); buf = buf.slice(i2 + 2);
            if (!block.startsWith("data: ")) continue;
            try {
              const d = JSON.parse(block.slice(6));
              if (d.type === "log" && d.msg) {
                setUpdLogs((p) => [...p, d.msg]);
                if (d.msg.includes("禁用鼠标和键盘")) message.warning("⚠️ 采集期间禁用鼠标和键盘，按 ESC 可停止");
              } else if (d.type === "done") {
                finished = true;
                setUpdLogs((p) => [...p, d.ok ? "✅ 更新完成" : `❌ 更新失败: ${d.reason || ""}`]);
                // 处理完成才算一篇
                setUpdCount((c) => c + 1);
              }
            } catch { /* 忽略坏帧 */ }
          }
        }
        setUpdLogs((p) => [...p, "⏹ 连接已断开"]);
        if (finished && updAbortRef.current === controller) {
          runUpd(idx + 1);
        }
      } catch (e: unknown) {
        if ((e as Error)?.name !== "AbortError") {
          setUpdLogs((p) => [...p, `❌ 更新接口异常: ${(e as Error)?.message || e}`]);
        }
      }
    })();
  }
  // 导出文章列表为 xlsx
  async function exportExcel() {
    message.info("正在导出全部数据...");
    try {
      // 带筛选参数取全量(page不传/0)
      const qs = new URLSearchParams({ biz: String(biz || "") });
      if (dateRange) { qs.set("date_start", dateRange[0].format("YYYY-MM-DD")); qs.set("date_end", dateRange[1].format("YYYY-MM-DD")); }
      if (kw.trim()) qs.set("kw", kw.trim());
      for (const f of NUM_FIELDS) {
        const [lo, hi] = ranges[f.key];
        if (lo != null) qs.set(`min_${f.key}`, String(lo));
        if (hi != null) qs.set(`max_${f.key}`, String(hi));
      }
      if (accFilter.length && !accFilter.includes("__all__")) qs.set("accs", accFilter.join(","));
      const d = await (await fetch(`${API}/articles-by-biz?${qs.toString()}`)).json();
      const all = Array.isArray(d.articles) ? d.articles : (d.items || []);
      if (all.length === 0) { message.info("没有可导出的数据"); return; }
      const rows = all.map((a: Article) => ({
        "ID": a.id, "标题": a.title || "", "日期": a.date || "",
        "art_biz": a.art_biz || "", "阅读": a.reads ?? "", "点赞": a.likes ?? "",
        "转发": a.forwards ?? "", "喜欢": a.favorites ?? "", "评论": (a as any).comments ?? "",
        "原创": a.original || "", "IP属地": a.ip || "", "写入时间": a.write_time || "",
      }));
      const ws = XLSX.utils.json_to_sheet(rows);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, "文章");
      XLSX.writeFile(wb, `${name || "文章列表"}.xlsx`);
    } catch { message.error("导出失败"); }
  }
  // 打开当前公众号的下载文件夹(D:/article_data/公众号名)
  async function openAccountDir() {
    // 全部文章模式: 打开总文件夹; 单公众号: 打开对应公众号文件夹
    const isAll = biz === "all";
    try {
      const url = isAll
        ? `http://127.0.0.1:8000/api/settings/open-downloads`
        : `http://127.0.0.1:8000/api/settings/open-downloads?sub=${encodeURIComponent(name || "")}`;
      const d = await (await fetch(url, { method: "POST" })).json();
      if (!d.ok) message.error(d.error || "打开失败");
    } catch { message.error("无法连接后端"); }
  }

  // 取列值(空值恒最前)
  function colVal(a: Article, key: string): string | number {
    const v = (a as any)[key] ?? "";
    if (key === "date" || key === "write_time") return typeof v === "string" ? v.trim() : String(v);
    return v;
  }
  // 排序已后端化, 直接用接口已排序数据
  const sorted = articles;

  // 筛选后端化, shown=已排序数据
  const shown = articles;
  // 日期快捷范围
  function toggleQuick(days: number, key: string) {
    if (quickActive === key) {
      setDateRange(null); setQuickActive(null);
    } else {
      const end = dayjs();
      const start = end.subtract(Math.max(0, days - 1), "day");
      setDateRange([start.startOf("day"), end.endOf("day")]);
      setQuickActive(key);
    }
  }
  const hasFilter = useMemo(() => {
    return !!(dateRange || kw.trim() || Object.values(ranges).some(([a, b]) => a != null || b != null));
  }, [dateRange, kw, ranges]);
  function clearFilter() {
    setDateRange(null); setQuickActive(null); setKw("");
    setRanges(Object.fromEntries(NUM_FIELDS.map((f) => [f.key, [null, null]])));
  }
  function reload() { if (biz) load(biz); }
  // 分页变化重载
  useEffect(() => { if (biz !== undefined && biz !== null) reload(); /* eslint-disable-next-line */ }, [page, pageSize]);
  // 筛选变化重载(回第1页)
  useEffect(() => { setPage(1); if (biz !== undefined && biz !== null) reload(); /* eslint-disable-next-line */ },
    [dateRange, kw, ranges, accFilter]);
  // 排序变化重载(回第1页)
  useEffect(() => { setPage(1); if (biz !== undefined && biz !== null) reload(); /* eslint-disable-next-line */ },
    [sortInfo]);
  // 初始自动计算每页条数
  useEffect(() => { setPageSize(calcPageSize()); }, []);
  // 更新弹窗显示=隐藏任务栏, 关闭=恢复
  useEffect(() => { if (updOpen) hideTaskbar(); else showTaskbar(); /* eslint-disable-next-line */ }, [updOpen]);

  async function importFile(f: File) {
    setImporting(true); setImportingPct(0); setFailedLinks([]); setDupRows([]);
    const fd = new FormData();
    fd.append("file", f);
    let total = 0, addedCount = 0;
    const fails: string[] = [];
    try {
      const r = await fetch(`${API}/articles-by-biz/import?biz=${encodeURIComponent(biz)}`, { method: "POST", body: fd });
      if (!r.body) throw 0;
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const block = buf.slice(0, idx); buf = buf.slice(idx + 2);
          const dm = block.match(/^data: (.+)$/m);
          if (!dm) continue;
          const d = JSON.parse(dm[1]);
          if (d.total) total = d.total;
          if (d.dups) setDupRows(d.dups);
          if (d.done !== undefined) {
            setImportingPct(Math.round((d.done / (total || 1)) * 100));
            if (d.ok) addedCount++;
            else if (d.dup) { /* 重复跳过, 不视为失败 */ }
            else fails.push(d.name || "(未知)");
          }
        }
      }
    } catch { setImporting(false); message.error("导入失败"); return; }
    setImportingPct(100);
    setFailedLinks(fails);
    reload();
    const hasFail = fails.length > 0, hasDup = dupRows.length > 0;
    if (hasFail || hasDup) {
      message.warning(`导入完成: 新增${addedCount}${hasDup ? `, 重复${dupRows.length}` : ""}${hasFail ? `, 失败${fails.length}` : ""}`);
    } else {
      setTimeout(() => { setImporting(false); message.success(`导入完成: 新增${addedCount}`); }, 1000);
    }
  }
  // 用导入文件数据覆盖已有重复记录
  async function replaceDup(row: any) {
    try {
      const r = await fetch(`${API}/articles-by-biz/save`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ biz: row.biz || biz, art_biz: row.art_biz, title: row.title, date: row.date, reads: row.reads,
          likes: row.likes, forwards: row.forwards, favorites: row.favorites, comments: row.comments, original: row.original, ip: row.ip }) });
      if (!r.ok) { message.error("替换失败"); return; }
      message.success("已替换"); setDupRows((prev) => prev.filter((d) => d.art_biz !== row.art_biz)); reload();
    } catch { message.error("替换失败"); }
  }
  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) importFile(f);
    e.target.value = "";
  }

  function openAdd() { setNewLink(""); setAddOpen(true); }

  async function saveNew() {
    const link = newLink.trim();
    if (!link) { message.warning("请输入文章链接"); return; }
    setSaving(true);
    try {
      const r = await fetch(`${API}/articles-by-biz`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ biz, link }),
      });
      if (!r.ok) { const e = await r.json().catch(() => ({})); message.error(e.detail || "保存失败"); return; }
      message.success("已新增");
      setAddOpen(false); setNewLink(""); reload();
    } catch { message.error("保存失败"); }
    finally { setSaving(false); }
  }

  async function deleteSelected() {
    if (selectedKeys.length === 0) {
      Modal.warning({ title: "未选择", content: "请在左侧勾选要删除的文章", okText: "知道了" });
      return;
    }
    Modal.confirm({ title: "删除选中", content: `确定删除选中的 ${selectedKeys.length} 篇文章？`, okText: "确认", cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        for (const id of selectedKeys) { await fetch(`${API}/articles-by-biz/${String(id)}?biz=${encodeURIComponent(biz)}`, { method: "DELETE" }); }
        setSelectedKeys([]); reload();
      } });
  }
  function del(a: Article) {
    Modal.confirm({ title: "删除文章", content: `确定删除「${a.title?.slice(0, 30)}」？`, okText: "确认", cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => { await fetch(`${API}/articles-by-biz/${a.id}?biz=${encodeURIComponent(biz)}`, { method: "DELETE" }); reload(); } });
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "0 0 8px" }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.push("/")}>返回</Button>
        <Typography.Title level={5} style={{ margin: 0 }}>「{name || "..."}」的文章列表</Typography.Title>
      </div>
      {/* 更新设置卡片(开关行 + 评论采集设置行) */}
      <div style={{ display: "flex", flexDirection: "column", background: "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "12px 18px", margin: "0 0 12px" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", minHeight: 32 }}>
          <span style={{ fontSize: 14, color: "#555" }}>窗口分离</span>
          <Switch checked={windowSplit} onChange={setWindowSplit} />
          <span style={{ marginLeft: 12, fontSize: 14, color: "#555" }}>采集4指标</span>
          <Switch checked={capture4metrics} onChange={setCapture4metrics} />
          <span style={{ marginLeft: 12, fontSize: 14, color: "#555" }}>采集阅读数</span>
          <Switch checked={captureRead} onChange={setCaptureRead} />
          <span style={{ marginLeft: 12, fontSize: 14, color: "#555" }}>保存Html</span>
          <Switch checked={saveHtml} onChange={setSaveHtml} />
          <span style={{ marginLeft: 12, fontSize: 14, color: "#555" }}>评论采集</span>
          <Switch checked={captureComments} onChange={setCaptureComments} />
        </div>
        {captureComments && (
          <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", paddingTop: 10 }}>
            <span style={{ fontSize: 13, color: "#555" }}>文章评论数</span>
            <InputNumber min={0} placeholder="无限" value={maxComments ?? null}
              onChange={(v) => setMaxComments(typeof v === "number" && v >= 0 ? v : null)} style={{ width: 90 }} />
            <span style={{ fontSize: 13, color: "#555" }}>一级评论数</span>
            <InputNumber min={0} placeholder="无限" value={maxLevel1 ?? null}
              onChange={(v) => setMaxLevel1(typeof v === "number" && v >= 0 ? v : null)} style={{ width: 90 }} />
            <span style={{ fontSize: 13, color: "#555" }}>每级二级评论数</span>
            <InputNumber min={0} placeholder="无限" value={maxLevel2}
              onChange={(v) => setMaxLevel2(typeof v === "number" && v >= 0 ? v : null)} style={{ width: 90 }} />
          </div>
        )}
      </div>
      {/* 筛选面板 */}
      <div style={{ background: "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "14px 18px", margin: "0 0 12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
          <DatePicker.RangePicker
            value={dateRange}
            onChange={(v) => { setDateRange(v as any); setQuickActive(null); }}
            placeholder={["开始日期", "结束日期"]}
            allowClear
            style={{ width: 280 }}
          />
          <Space size={4} wrap>
            <Button size="small" type={dateRange === null && quickActive === null ? "primary" : "default"}
              onClick={() => { setDateRange(null); setQuickActive(null); }}>全部</Button>
            <Button size="small" type={quickActive === "1" ? "primary" : "default"} onClick={() => toggleQuick(1, "1")}>今天</Button>
            <Button size="small" type={quickActive === "7" ? "primary" : "default"} onClick={() => toggleQuick(7, "7")}>近一周</Button>
            <Button size="small" type={quickActive === "30" ? "primary" : "default"} onClick={() => toggleQuick(30, "30")}>近一月</Button>
          </Space>
          {biz === "all" && (
            <Select
              mode="multiple" allowClear placeholder="公众号"
              value={accFilter} onChange={(v: any[]) => {
                // 含'全部' => 只看全部(去掉具体项); 否则按所选公众号过滤
                setAccFilter(v && v.includes("__all__") ? ["__all__"] : (v || []));
              }}
              style={{ minWidth: 180, maxWidth: 320 }}
              options={[
                { value: "__all__", label: "全部" },
                ...Array.from(new Set(articles.map((a: any) => a.acc_name || ""))).filter(Boolean).map((n: any) => ({ value: String(n), label: String(n) })),
              ]}
              maxTagCount="responsive"
            />
          )}
          {!collapsed && (
            <Input allowClear prefix={<SearchOutlined style={{ color: "#bfc7cf" }} />}
              placeholder="输入文章标题"
              value={kw} onChange={(e) => setKw(e.target.value)}
              style={{ width: 220 }} />
          )}
          {!collapsed && NUM_FIELDS.map((f) => (
            <Space key={f.key} size={6}>
              <Typography.Text style={{ fontSize: 13, whiteSpace: "nowrap" }}>{f.label}</Typography.Text>
              <NumRange value={ranges[f.key]}
                onChange={(v) => setRanges((prev) => ({ ...prev, [f.key]: v }))} />
            </Space>
          ))}
          <div style={{ flex: 1 }} />
          <Tooltip title={collapsed ? "展开筛选" : "收起筛选"}>
            <Button size="small" type="text" icon={collapsed ? <DownOutlined /> : <UpOutlined />}
              onClick={() => setCollapsed((c) => !c)} />
          </Tooltip>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 8 }}>
          {hasFilter ? (
            <Button size="small" type="link" onClick={clearFilter}><ClearOutlined /> 清除筛选</Button>
          ) : null}
        </div>
      </div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files?.[0]; if (f) importFile(f); }}
        style={{ display: "flex", flexDirection: "column", flex: shown.length ? 1 : undefined, background: dragOver ? "#eef4ff" : "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "16px 18px", transition: ".2s", border: dragOver ? "2px dashed #1565c0" : "2px solid transparent" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <Button type="primary" icon={<ReloadOutlined />} onClick={openUpdateSelected}>更新选中</Button>
          <Button icon={<DownloadOutlined />} onClick={downloadSelected}>下载选中</Button>
          <div style={{ flex: 1 }} />
          {biz !== "all" && <Button color="primary" variant="outlined" icon={<PlusOutlined />} onClick={openAdd}>新增</Button>}
          {biz !== "all" && <Button icon={<ImportOutlined />} onClick={() => fileRef.current?.click()}>导入</Button>}
          <Button danger icon={<DeleteOutlined />} onClick={deleteSelected}>删除选中</Button>
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls,.xlsm" style={{ display: "none" }} onChange={onPick} />
        </div>
        {loading ? (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Space vertical size={10} style={{ alignItems: "center" }}>
            <Spin size="large" />
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>正在加载文章…</Typography.Text>
          </Space>
        </div>
        ) : shown.length > 0 ? (
        <div ref={tableWrapRef} style={{ flex: 1, minHeight: 0, position: "relative", overflow: "auto" }}>
        <Table className="articles-table" rowKey="id" dataSource={shown} loading={loading} pagination={false} showSorterTooltip={false} size="small" sticky scroll={{ x: 1500 }}
          onChange={(_p: any, _f: any, sorter: any) => {
            const s = Array.isArray(sorter) ? sorter[0] : sorter;
            const key = s?.columnKey || s?.field;
            const order = s?.order;
            if (key && (order === "ascend" || order === "descend")) setSortInfo({ key, order });
            else setSortInfo(biz === "all" ? { key: "acc_name", order: "ascend" } : { key: "date", order: "descend" });
          }}
          rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
          locale={{ emptyText: <Empty description={loadErr ? "加载失败，请重试" : "暂无文章"} /> }}
          columns={[
            ...(biz === "all" ? [{
              title: "公众号名称", key: "acc_name", dataIndex: "acc_name", width: 120, ellipsis: true, sorter: true,
              sortOrder: sortInfo.key === "acc_name" ? sortInfo.order : null,
              render: (v: string) => <span style={{ fontSize: 12 }}>{v || "-"}</span>,
            }] : []),
            {
              title: "标题", dataIndex: "title", width: 100, ellipsis: false,
              render: (v: string, r: Article) => {
                const text = v || "";
                const ellStyle = { flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
                return (
                  <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                    {r.original === "原创" ? <Tag color="green" style={{ margin: 0, flexShrink: 0 }}>原创</Tag> : null}
                    <Tooltip title={text}>
                      {r.art_biz ? <a href={ART_PREFIX + r.art_biz} target="_blank" style={ellStyle}>{text}</a> : <span style={ellStyle}>{text}</span>}
                    </Tooltip>
                  </div>
                );
              },
            },
            {
              title: "日期", dataIndex: "date", width: 70, sorter: true,
              sortOrder: sortInfo.key === "date" ? sortInfo.order : null,
              render: (v: string) => {
                const t = v || "";
                const m = t.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
                const short = m ? `${m[1]}/${Number(m[2])}/${Number(m[3])}` : t;
                return <Tooltip title={t}><span style={{ cursor: "default" }}>{short}</span></Tooltip>;
              },
            },
            {
              title: "评论", dataIndex: "comments", width: 110,
              sorter: true, sortOrder: sortInfo.key === "comments" ? sortInfo.order : null,
              render: (v: string, r: Article) => (
                <Space size={4}>
                  <span title={`实际采集 ${r.comment_count ?? 0} / 4指标留言数 ${v || 0}`}>
                    {r.comment_count ?? 0}/{v || 0}
                  </span>
                  <Button size="small" type="link" icon={<MessageOutlined />}
                    onClick={() => router.push(`/comments?art_biz=${encodeURIComponent(r.art_biz || "")}&biz=${encodeURIComponent(biz)}&name=${encodeURIComponent(name || "")}&title=${encodeURIComponent(r.title || "")}`)}>查看</Button>
                </Space>
              ),
            },
            { title: "阅读", dataIndex: "reads", width: 80, sorter: true, sortOrder: sortInfo.key === "reads" ? sortInfo.order : null },
            { title: "点赞", dataIndex: "likes", width: 80, sorter: true, sortOrder: sortInfo.key === "likes" ? sortInfo.order : null },
            { title: "转发", dataIndex: "forwards", width: 80, sorter: true, sortOrder: sortInfo.key === "forwards" ? sortInfo.order : null },
            { title: "喜欢", dataIndex: "favorites", width: 80, sorter: true, sortOrder: sortInfo.key === "favorites" ? sortInfo.order : null },
            { title: "IP", dataIndex: "ip", width: 80 },
            {
              title: "写入时间", dataIndex: "write_time", width: 70, sorter: true,
              sortOrder: sortInfo.key === "write_time" ? sortInfo.order : null,
              render: (v: string) => {
                const t = v || "";
                const m = t.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
                const short = m ? `${m[1]}/${Number(m[2])}/${Number(m[3])}` : t;
                return <Tooltip title={t}><span style={{ cursor: "default" }}>{short}</span></Tooltip>;
              },
            },
            { title: "操作", dataIndex: "op", width: 180, align: "center", fixed: "right",
              render: (_: unknown, r: Article) => (
                <Space>
                  <Button size="small" type="link" icon={<DownloadOutlined />} loading={dlKey === (r.art_biz || "")} onClick={() => downloadHtml(r)}>下载</Button>
                  <Button size="small" type="link" icon={<ReloadOutlined />} onClick={() => openUpdate(r)}>更新</Button>
                  <Button size="small" type="link" danger icon={<DeleteOutlined />} onClick={() => del(r)}>删除</Button>
                </Space>
              ) },
          ]}
        />
        </div>
        ) : (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "40px 0" }}>
          <Empty description={loadErr ? "加载失败，请重试" : "暂无文章"} />
        </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingTop: 10, flexShrink: 0 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Button size="small" icon={<FolderOpenOutlined />} onClick={openAccountDir}>打开下载数据</Button>
            <Button size="small" icon={<FileExcelOutlined />} onClick={exportExcel}>导出表格</Button>
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <PaginationBar total={total} page={page} pageSize={pageSize}
            onChange={(p, ps) => { setPage(p); if (ps !== pageSize) setPageSize(ps); }} />
          </div>
        </div>
      </div>
      {/* 导入进度/失败弹窗 */}
      <Modal title={failedLinks.length || dupRows.length ? "导入结果" : "正在导入"} open={importing}
        footer={(failedLinks.length || dupRows.length) ? <Button type="primary" onClick={() => setImporting(false)}>关闭</Button> : null}
        closable={(failedLinks.length || dupRows.length) > 0} onCancel={() => setImporting(false)} width={520}>
        {(failedLinks.length || dupRows.length) ? (
          <div>
            {dupRows.length > 0 ? (
              <div style={{ marginBottom: 14 }}>
                <Typography.Paragraph strong>有 {dupRows.length} 条重复（未覆盖）。如文件数据更全，可点击替换更新已有记录：</Typography.Paragraph>
                <Table size="small" rowKey={(r) => r.art_biz} pagination={false} dataSource={dupRows}
                  columns={[
                    { title: "标题", dataIndex: "title", render: (v: string, r: any) => <a href={ART_PREFIX + r.art_biz} target="_blank" style={{ fontSize: 12 }}>{(v || r.art_biz).slice(0, 24)}</a> },
                    { title: "日期", dataIndex: "date", width: 90, render: (v: string) => <span style={{ fontSize: 12 }}>{v || "—"}</span> },
                    { title: "操作", width: 70, align: "center",
                      render: (_: unknown, r: any) => <Button size="small" type="link" onClick={() => replaceDup(r)}>替换</Button> },
                  ]} />
              </div>
            ) : null}
            {failedLinks.length > 0 ? (
              <div>
                <Typography.Paragraph strong style={{ color: "#c62828" }}>有 {failedLinks.length} 条链接导入失败，需手动处理：</Typography.Paragraph>
                <Table size="small" rowKey={(r) => r} pagination={false} dataSource={failedLinks}
                  columns={[{ title: "失败链接", dataIndex: 0, render: (v: string) => <a href={v} target="_blank" style={{ fontSize: 12 }}>{v.slice(0, 60)}</a> }]} />
              </div>
            ) : null}
          </div>
        ) : (
          <div style={{ textAlign: "center", padding: "8px 0" }}>
            <Typography.Title level={5} style={{ marginTop: 0 }}>导入进度</Typography.Title>
            <Progress percent={importingPct} status={importingPct >= 100 ? "success" : "active"} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>解析文件并识别文章链接…</Typography.Text>
          </div>
        )}
      </Modal>

      {/* 下载选中进度弹窗 */}
      <Modal title={`下载进度 ${dlCount}/${dlItems.length}`} open={dlOpen}
        footer={dlRun ? <Button danger onClick={() => { dlAbortRef.current?.abort(); setDlRun(false); setDlOpen(false); }}>取消</Button>
                      : <Button type="primary" onClick={() => setDlOpen(false)}>关闭</Button>}
        closable={false} mask={{ closable: false }} width={520}>
        <Progress percent={dlItems.length ? Math.round((dlCount / dlItems.length) * 100) : 0}
          status={dlRun ? "active" : "success"} />
        <div style={{ maxHeight: 300, overflow: "auto", marginTop: 10, fontSize: 12 }}>
          {dlItems.map((it, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 0" }}>
              <span style={{ width: 46, flexShrink: 0, color: it.status === "成功" ? "#52c41a" : it.status === "失败" ? "#ff4d4f" : it.status === "取消" ? "#999" : "#1677ff", fontWeight: 500 }}>{it.status}</span>
              <span style={{ color: "#333", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.title}</span>
              <span style={{ color: "#888", width: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.msg}</span>
            </div>
          ))}
        </div>
      </Modal>

      <Modal title="新增文章" open={addOpen} onOk={saveNew} confirmLoading={saving} onCancel={() => setAddOpen(false)}
        okText="保存" cancelText="取消">
        <Space vertical style={{ width: "100%" }}>
          <div>请输入文章链接，保存后显示在标题列（无标题则显示链接）。</div>
          <Input placeholder="https://mp.weixin.qq.com/s/..." value={newLink} onChange={(e) => setNewLink(e.target.value)} onPressEnter={saveNew} />
        </Space>
      </Modal>

      {/* 更新弹窗: 确认阶段 -> 更新进行中 */}
      <Modal
        open={updOpen}
        title={updStarted ? `正在更新「${updTask?.title || updTask?.art_biz || ""}」 (${updIdx}/${updQueue.length || 1})` : updQueue.length > 1 ? `确认更新设置 (共 ${updQueue.length} 个)` : "确认更新设置"}
        onCancel={() => { if (updStarted) { stopUpdate(); return; } closeUpd(); }}
        footer={updStarted ? (
          updStopped ? (
            <Button type="primary" onClick={closeUpd}>关闭</Button>
          ) : (
            <Button danger onClick={stopUpdate}>按 ESC 停止</Button>
          )
        ) : (
          <>
            <Button onClick={closeUpd}>取消</Button>
            <Button type="primary" onClick={confirmUpdate}>确认</Button>
          </>
        )}
        width={updStarted ? 880 : 520}
      >
        {updStarted ? (
          <div style={{ display: "flex", gap: 12 }}>
            <div style={{ flex: 1, background: "#fff", border: "1px solid #eee", borderRadius: 8, padding: "4px 0" }}>
              <div style={{ padding: "7px 14px", fontSize: 13, fontWeight: 600, color: "#333", borderBottom: "1px solid #f0f0f0" }}>更新设置</div>
              {[
                { label: "窗口分离", value: windowSplit ? "开" : "关" },
                { label: "采集4指标", value: capture4metrics ? "开" : "关" },
                { label: "采集阅读数", value: captureRead ? "开" : "关" },
                { label: "保存Html", value: saveHtml ? "开" : "关" },
                { label: "评论采集", value: captureComments ? "开" : "关" },
                { label: "文章评论数", value: captureComments ? (maxComments == null ? "无限" : String(maxComments)) : "0" },
                { label: "一级评论数", value: captureComments ? (maxLevel1 == null ? "无限" : String(maxLevel1)) : "0" },
                { label: "每级二级评论数", value: captureComments ? (maxLevel2 == null ? "无限" : String(maxLevel2)) : "0" },
              ].map((row) => (
                <div key={row.label} style={{ display: "flex", alignItems: "center", padding: "7px 14px", fontSize: 13 }}>
                  <span style={{ width: 110, color: "#888", whiteSpace: "nowrap" }}>{row.label}</span>
                  <span style={{ color: "#333", fontWeight: 500 }}>{row.value}</span>
                </div>
              ))}
            </div>
            {updQueue.length > 1 && (
            <div style={{ flex: 1, background: "#fff", border: "1px solid #eee", borderRadius: 8, padding: "4px 0" }}>
              <div style={{ padding: "7px 14px", fontSize: 13, fontWeight: 600, color: "#333", borderBottom: "1px solid #f0f0f0" }}>更新情况</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "10px 14px", fontSize: 13, color: "#555" }}>
                <div>开始时间: <span style={{ color: "#333" }}>{updStartTime}</span></div>
                <div>已更新文章: <span style={{ color: "#333", fontWeight: 600 }}>{updCount} 篇</span></div>
                <div>更新速度: <span style={{ color: "#333" }}>{updSpeed} 篇/分</span></div>
              </div>
            </div>
            )}
          </div>
        ) : (
          <div style={{ background: "#fff", border: "1px solid #eee", borderRadius: 8, padding: "4px 0" }}>
            {[
              { label: "窗口分离", value: windowSplit ? "开" : "关" },
              { label: "采集4指标", value: capture4metrics ? "开" : "关" },
              { label: "采集阅读数", value: captureRead ? "开" : "关" },
              { label: "保存Html", value: saveHtml ? "开" : "关" },
              { label: "评论采集", value: captureComments ? "开" : "关" },
              { label: "文章评论数", value: captureComments ? (maxComments == null ? "无限" : String(maxComments)) : "0" },
              { label: "一级评论数", value: captureComments ? (maxLevel1 == null ? "无限" : String(maxLevel1)) : "0" },
              { label: "每级二级评论数", value: captureComments ? (maxLevel2 == null ? "无限" : String(maxLevel2)) : "0" },
            ].map((row) => (
              <div key={row.label} style={{ display: "flex", alignItems: "center", padding: "7px 14px", fontSize: 13 }}>
                <span style={{ width: 110, color: "#888", whiteSpace: "nowrap" }}>{row.label}</span>
                <span style={{ color: "#333", fontWeight: 500 }}>{row.value}</span>
              </div>
            ))}
          </div>
        )}
        {updStarted && (
          <div style={{ background: "#fafafa", border: "1px solid #eee", borderRadius: 8, padding: "10px 12px", marginTop: 12 }}>
            <Typography.Text strong style={{ fontSize: 13 }}>日志</Typography.Text>
            <div ref={updLogRef} style={{
              marginTop: 8, height: 220, overflow: "auto",
              background: "#1e1e1e", borderRadius: 6, padding: 8,
              fontFamily: "Consolas, monospace", fontSize: 12, color: "#d4d4d4", whiteSpace: "pre-wrap",
            }}>
              {updLogs.length === 0 ? (
                <span style={{ color: "#888" }}>(暂无日志)</span>
              ) : (
                updLogs.map((l, i) => {
                  // [async:任务名] 异步统一青色; [step]橙 [ok]绿 [fail]红 [warn]黄
                  const mAsync = l.match(/^\[async:([^\]]+)\]\s?([\s\S]*)/);
                  const m = mAsync || l.match(/^\[(step|ok|fail|warn)\]\s?([\s\S]*)/);
                  let text = l, color: string | undefined;
                  if (mAsync) { color = "#36cfc9"; text = `[${mAsync[1]}] ${mAsync[2]}`; }
                  else if (m) {
                    color = { step: "#ffa940", ok: "#73d13d", fail: "#ff4d4f", warn: "#ffc53d" }[m[1]];
                    text = m[2];
                  }
                  return <div key={i} style={color ? { color } : undefined}>{text}</div>;
                })
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
