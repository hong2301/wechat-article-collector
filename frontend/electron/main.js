const { app, BrowserWindow, nativeImage, shell } = require('electron')
const path = require('path')

const isDev = !app.isPackaged

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
  win.webContents.on('will-navigate', (event, url) => {
    if (url.startsWith('http://localhost') || url.startsWith('http://127.0.0.1')) {
      return   // 本地(Nex/后端) 放行
    }
    event.preventDefault()
    shell.openExternal(url)
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

app.whenReady().then(createWindow)
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
