const { app, BrowserWindow, nativeImage, shell, dialog } = require('electron')
const path = require('path')
const fs = require('fs')
const { spawn, execFileSync } = require('child_process')

// ---------- 自动更新(electron-updater, 仅生产; 需 GitHub Token 发版才生效) ----------
function setupAutoUpdater(win) {
  if (isDev) return
  try {
    const { autoUpdater } = require('electron-updater')
    autoUpdater.autoDownload = false     // 先询问用户再下载
    autoUpdater.on('update-available', (info) => {
      log(`发现新版本 ${info.version}`)
      dialog.showMessageBox(win, {
        type: 'info', title: '发现新版本',
        message: `发现新版本 v${info.version}, 是否现在更新?`,
        buttons: ['更新', '稍后'],
      }).then((r) => { if (r.response === 0) autoUpdater.downloadUpdate() })
    })
    autoUpdater.on('update-downloaded', () => {
      dialog.showMessageBox(win, {
        type: 'info', title: '更新已就绪',
        message: '新版本已下载, 重启应用以完成更新。',
        buttons: ['立即重启', '稍后'],
      }).then((r) => { if (r.response === 0) autoUpdater.quitAndInstall() })
    })
    autoUpdater.on('error', (err) => log(`自动更新失败: ${err.message}`))
    autoUpdater.checkForUpdates().catch((e) => log(`更新检查未开始: ${e.message}`))
    log('自动更新检查已启动')
  } catch (e) {
    log('electron-updater 不可用, 跳过自动更新: ' + e.message)
  }
}

const isDev = !app.isPackaged
const BACKEND_PORT = 8000
let backendProc = null
let mainWindow = null

// ---------- 单实例锁: 重复双击只保留一个窗口 ----------
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    log('检测到重复启动, 聚焦已有窗口')
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })
}

// 日志落盘: %APPDATA%/WeChatCollector/main.log (便于排查双击启动问题)
const LOG_MAX = 5 * 1024 * 1024   // 日志超 5MB 重命名轮转
function logFile() {
  const dir = app.getPath('userData')
  try { fs.mkdirSync(dir, { recursive: true }) } catch (e) {}
  return path.join(dir, 'main.log')
}
function log(msg) {
  try {
    const f = logFile()
    if (fs.existsSync(f) && fs.statSync(f).size > LOG_MAX) {
      fs.renameSync(f, f + '.old')   // 轮转: main.log -> main.log.old
    }
    fs.appendFileSync(f, `[${new Date().toISOString()}] ${msg}\n`)
  } catch (e) {}
}

// 生产模式: 数据目录 = exe 同级 data/ (与 release 目录布局一致)
function dataDir() {
  return path.join(path.dirname(app.getPath('exe')), 'data')
}

// 生产模式: 拉起 PyInstaller 打包的 Python 后端(exe 旁的独立进程)
async function startBackend() {
  if (isDev) {
    log('开发模式: 后端由 npm run dev:backend 自行启动')
    return
  }
  // 已有后端在跑(上次强杀残留等): 直接复用, 避免端口冲突和孤儿堆积
  try {
    const resp = await fetch(`http://127.0.0.1:${BACKEND_PORT}/api/health`)
    if (resp.ok) {
      log('检测到已有后端在运行, 直接复用(不重复启动)')
      backendProc = { pid: -1, killed: true }  // 非本进程启动, 退出时不 taskkill
      return
    }
  } catch (e) { /* 端口未开, 正常拉起 */ }
  const exe = path.join(process.resourcesPath, 'backend', 'collector-backend.exe')
  log(`启动后端: ${exe}`)
  backendProc = spawn(exe, [], {
    env: {
      ...process.env,
      WECHAT_COLLECTOR_DATA_DIR: dataDir(),
      WECHAT_PARENT_PID: String(process.pid),  // 看门狗: 主程序退出则后端自杀
    },
    windowsHide: true,
    // 后端 stdout/stderr 也写入日志文件, 便于排查
    stdio: ['ignore', fs.openSync(logFile(), 'a'), fs.openSync(logFile(), 'a')],
  })
  backendProc.on('error', (err) => log(`后端启动失败: ${err.message}`))
  backendProc.on('exit', (code, signal) =>
    log(`后端进程退出 code=${code} signal=${signal}`)
  )
  log(`后端已拉起, pid = ${backendProc.pid}`)
}

// 轮询等待后端 /api/health 就绪(OCR引擎后台线程加载, health 秒回)
function waitForBackend(timeoutMs = 30000) {
  const start = Date.now()
  return new Promise((resolve) => {
    const tick = async () => {
      if (Date.now() - start > timeoutMs) return resolve(false)
      try {
        const resp = await fetch(`http://127.0.0.1:${BACKEND_PORT}/api/health`)
        if (resp.ok) return resolve(true)
      } catch (e) { /* 端口未开, 继续等 */ }
      setTimeout(tick, 500)
    }
    tick()
  })
}

// 退出时清理后端进程树(防残留占 8000 端口)
function killBackend() {
  if (!backendProc || backendProc.killed) return
  try {
    execFileSync('taskkill', ['/pid', String(backendProc.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' })
  } catch (e) { /* 已退出则忽略 */ }
  backendProc = null
}

app.on('before-quit', killBackend)

function createIcon() {
  try {
    const img = nativeImage.createFromPath(path.join(__dirname, 'icon.png'))
    return img.isEmpty() ? undefined : img
  } catch (e) {
    return undefined
  }
}

// ---------- 窗口状态记忆: 记住上次窗口大小/位置 ----------
function windowStateFile() {
  return path.join(app.getPath('userData'), 'window-state.json')
}
function loadWindowState() {
  try {
    const s = JSON.parse(fs.readFileSync(windowStateFile(), 'utf8'))
    // 校验: 窗口需落在屏幕可视区域(防显示器分辨率变化后丢窗口)
    const { screen } = require('electron')
    const wa = screen.getPrimaryDisplay().workArea
    if (s.x !== undefined && s.width && s.width <= wa.width && s.height <= wa.height) {
      return { width: s.width, height: s.height, x: s.x, y: s.y }
    }
  } catch (e) { /* 无记录/损坏 -> 默认 */ }
  return { width: 1180, height: 760 }
}
function saveWindowState(win) {
  try {
    fs.writeFileSync(windowStateFile(), JSON.stringify(win.getNormalBounds()))
  } catch (e) { /* 忽略 */ }
}

function createWindow() {
  const icon = createIcon()
  const state = loadWindowState()
  const win = new BrowserWindow({
    ...state,
    autoHideMenuBar: true,
    icon,
    webContents: { contextIsolation: true, nodeIntegration: false },
  })
  mainWindow = win

  // 窗口关闭时记忆大小/位置
  win.on('close', () => saveWindowState(win))

  // 渲染进程崩溃: 提示 + 自动恢复
  win.webContents.on('render-process-gone', (e, details) => {
    log(`渲染进程崩溃: reason=${details.reason} exitCode=${details.exitCode}`)
    dialog.showMessageBox(win, {
      type: 'error', title: '页面异常',
      message: '页面进程崩溃，正在尝试恢复…',
      buttons: ['重新加载'],
    }).then(() => { try { win.reload() } catch (e2) {} })
  })
  // 加载失败(含后端未起动 served 页面 404): 日志 + 提示
  win.webContents.on('did-fail-load', (e, code, desc, url) => {
    log(`页面加载失败 code=${code} desc=${desc} url=${url}`)
  })
  // 渲染进程 console 统一透传到主日志(排查前端问题)
  win.webContents.on('console-message', (e, level, message) => {
    if (level >= 2) log(`渲染[${['log','warn','error'][level] || level}]: ${message.slice(0, 300)}`)
  })

  // 打包版禁止开发者工具(F12/Ctrl+Shift+I/Ctrl+U), dev 模式放行
  if (!isDev) {
    win.webContents.on('before-input-event', (event, input) => {
      if (input.type !== 'keyDown') return
      const k = input.key
      const blocked =
        k === 'F12' ||
        (input.control && input.shift && /^[ijIJ]$/.test(k)) ||   // Ctrl+Shift+I/J
        ((input.control || input.meta) && /^[uU]$/.test(k))      // Ctrl+U 查看源码
      if (blocked) event.preventDefault()
    })
    // 兜底: 若被 API 强行打开则立即关闭
    win.webContents.on('devtools-opened', () => {
      try { win.webContents.closeDevTools() } catch (e2) {}
    })
  }

  // 拦截导航：外部 http(s) 链接用系统默认浏览器打开，不在应用内跳转
  win.webContents.on('will-navigate', (event, urlStr) => {
    // 本地(http://localhost) 放行
    if (urlStr.startsWith('http://localhost') || urlStr.startsWith('http://127.0.0.1')) {
      return
    }
    // file:// 协议: Next 静态导出的客户端导航(router.push('/articles'))会变成
    // 指向盘根的绝对路径(file:///C:/articles), 在 file:// 下不存在 -> 重写到 out/ 下对应 html
    if (urlStr.startsWith('file:')) {
      try {
        const u = new URL(urlStr)
        let page = u.pathname.replace(/^\//, '')
        // 情形A: Next 客户端导航产物 file:///C:/articles(带盘符无扩展名) -> out/articles.html
        let m = page.match(/^[a-zA-Z]:\/([a-z0-9_-]+)$/)
        // 情形B: out 目录内完整路径 file:///C:/.../out/articles.html -> 取文件名重载
        if (!m) m = page.match(/[\/]([a-z0-9_-]+\.html?)$/i)
        if (m) {
          const base = /^[a-z0-9_-]+\.html?$/i.test(m[1]) ? m[1] : m[1] + '.html'
          event.preventDefault()
          win.loadFile(path.join(__dirname, 'out', base), { search: u.search.slice(1) })
          return
        }
        if (page === 'index.html' || page === '') {
          event.preventDefault()
          win.loadFile(path.join(__dirname, 'out', 'index.html'), { search: u.search.slice(1) })
          return
        }
        // 其他未知 file 路径: 阻止, 忽略
        event.preventDefault()
        return
      } catch (e) {}
    }
    event.preventDefault()
    shell.openExternal(urlStr)
  })
  // 拦截 target=_blank 新窗口
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://localhost') || url.startsWith('http://127.0.0.1')) {
      return { action: 'allow' }
    }
    shell.openExternal(url)
    return { action: 'deny' }
  })

  if (isDev) {
    win.loadURL('http://localhost:3000')
  } else {
    win.loadFile(path.join(__dirname, 'out', 'index.html'))
  }
}

app.whenReady().then(async () => {
  if (!isDev) {
    await startBackend()
    const ok = await waitForBackend()
    log(ok ? '后端就绪' : '警告: 等待后端超时 (30s)')
  }
  createWindow()
  log('主窗口已创建')
  setupAutoUpdater(mainWindow)   // 窗口创建后检查更新 (生产)
})
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})