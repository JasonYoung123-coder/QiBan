const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('qibanDesktop', Object.freeze({
  minimize: () => ipcRenderer.send('qiban:minimize'),
  close: () => ipcRenderer.send('qiban:close'),
  setPetMode: enabled => ipcRenderer.invoke('qiban:pet', Boolean(enabled)),
  setAlwaysOnTop: enabled => ipcRenderer.invoke('qiban:top', Boolean(enabled)),
  setClickThrough: enabled => ipcRenderer.send('qiban:passthrough', Boolean(enabled)),
  openGuide: url => ipcRenderer.invoke('qiban:open-guide', url),
  onPetMode(callback) {
    const listener = (_event, enabled) => callback(Boolean(enabled))
    ipcRenderer.on('qiban:pet-state', listener)
    return () => ipcRenderer.removeListener('qiban:pet-state', listener)
  },
}))
