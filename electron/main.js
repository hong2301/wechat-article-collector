const { app, BrowserWindow, nativeImage } = require('electron')
const path = require('path')
const fs = require('fs')

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
    webPreferences: { contextIsolation: true, nodeIntegration: false }
  })
  if (isDev) {
    win.loadURL('http://localhost:3000')
  } else {
    win.loadFile(path.join(__dirname, '../frontend/out/index.html'))
  }
}

app.whenReady().then(() => {
  createWindow()
})
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
