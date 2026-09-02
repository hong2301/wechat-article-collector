// 渲染进程桥: 暴露自动更新进度订阅(electron-updater 下载进度经 IPC 转发)
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('updateBridge', {
  onProgress: (cb) => {
    const handler = (_e, p) => cb(p)
    ipcRenderer.on('update-progress', handler)
    return () => ipcRenderer.removeListener('update-progress', handler)
  },
})