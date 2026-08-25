const { app, BrowserWindow, nativeImage, shell } = require('electron')
const path = require('path')
const fs = require('fs')
const { spawn, execFileSync } = require('child_process')

const isDev = !app.isPackaged
const BACKEND_PORT = 8000
let backendProc = null

// 日志落盘: %APPDATA%/WeChatCollector/main.log (便于排查双击启动问题)
function logFile() {
  const dir = app.getPath('userData')
  try { fs.mkdirSync(dir, { recursive: true }) } catch (e) {}
  return path.join(dir, 'main.log')
}
function log(msg) {
  try { fs.appendFileSync(logFile(), `[${new Date().toISOString()}] ${msg}\n`) } catch (e) {}
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

function createWindow() {
  const icon = createIcon()
  const win = new BrowserWindow({
    width: 1180,
    height: 760,
    autoHideMenuBar: true,
    icon,
    webContents: { contextIsolation: true, nodeIntegration: false },
  })

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
        if (page === 'index.html' || page === '') {
          event.preventDefault()
          win.loadFile(path.join(__dirname, 'out', 'index.html'), { search: u.search.slice(1) })
          return
        }
        if (/^[a-z0-9_-]+\.html?$/i.test(page)) {
          event.preventDefault()
          win.loadFile(path.join(__dirname, 'out', page), { search: u.search.slice(1) })
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
})
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})