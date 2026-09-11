const { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage, screen, globalShortcut, dialog } = require('electron')
const { spawn } = require('node:child_process')
const { existsSync, mkdirSync, openSync, closeSync } = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const serverUrl = 'http://127.0.0.1:18765'
let mainWindow
let backend
let tray
let petMode = false
let clickThrough = false
let normalBounds
let pinned = false

app.setPath('userData', path.join(root, '.data', 'desktop-profile'))
if (!app.requestSingleInstanceLock()) app.quit()
else {
  app.on('second-instance', () => { mainWindow?.show(); mainWindow?.focus() })
  app.whenReady().then(start).catch(error => {
    dialog.showErrorBox('栖伴未能启动', String(error.message || error))
    app.quit()
  })
}

async function health() {
  try {
    const result = await fetch(`${serverUrl}/api/health`, { signal: AbortSignal.timeout(1200) })
    const data = await result.json()
    if (data.service !== 'qiban-companion-core') throw new Error('端口 18765 已被其他程序使用。')
    return true
  } catch (error) {
    if (error.message === '端口 18765 已被其他程序使用。') throw error
    return false
  }
}

async function ensureBackend() {
  if (await health()) return
  const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
  if (!existsSync(python)) throw new Error('Python 环境尚未准备。请先运行 scripts/setup.ps1。')
  mkdirSync(path.join(root, '.data'), { recursive: true })
  const log = openSync(path.join(root, '.data', 'backend.log'), 'a')
  backend = spawn(python, ['-m', 'uvicorn', 'backend.api:create_app', '--factory', '--host', '127.0.0.1', '--port', '18765'], {
    cwd: root, windowsHide: true, stdio: ['ignore', log, log], env: { ...process.env, PYTHONUTF8: '1' },
  })
  closeSync(log)
  let spawnError
  backend.on('error', error => { spawnError = error })
  for (let attempt = 0; attempt < 60; attempt += 1) {
    if (spawnError) throw spawnError
    if (backend.exitCode !== null) throw new Error('本地服务启动失败，请查看 .data/backend.log。')
    if (await health()) return
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  throw new Error('本地服务启动超时，请查看 .data/backend.log。')
}

function togglePet(enabled) {
  if (!mainWindow || mainWindow.isDestroyed()) return false
  setClickThrough(false)
  if (enabled && !petMode) {
    normalBounds = mainWindow.getBounds()
    mainWindow.setMinimumSize(270, 380)
    const area = screen.getDisplayMatching(normalBounds).workArea
    mainWindow.setBounds({ x: area.x + area.width - 405, y: area.y + area.height - 630, width: 380, height: 610 })
    mainWindow.setAlwaysOnTop(true)
  } else if (!enabled && petMode) {
    mainWindow.setMinimumSize(820, 620)
    if (normalBounds) mainWindow.setBounds(normalBounds)
    mainWindow.setAlwaysOnTop(pinned)
  }
  petMode = enabled
  mainWindow.webContents.send('qiban:pet-state', petMode)
  updateMenu()
  return petMode
}

function setClickThrough(enabled) {
  clickThrough = Boolean(enabled && petMode)
  mainWindow?.setIgnoreMouseEvents(clickThrough, { forward: true })
  updateMenu()
}

function updateMenu() {
  tray?.setContextMenu(Menu.buildFromTemplate([
    { label: '显示聊天窗口', click: () => { togglePet(false); mainWindow.show(); mainWindow.focus() } },
    { label: '桌宠模式', type: 'checkbox', checked: petMode, click: () => togglePet(!petMode) },
    { label: '鼠标穿透（Ctrl+Alt+Q 恢复）', type: 'checkbox', checked: clickThrough, enabled: petMode,
      click: () => setClickThrough(!clickThrough) },
    { type: 'separator' },
    { label: '退出栖伴', click: () => app.quit() },
  ]))
}

async function start() {
  if (!existsSync(path.join(root, 'dist', 'index.html'))) throw new Error('界面尚未构建，请先运行 npm run build。')
  await ensureBackend()
  mainWindow = new BrowserWindow({
    width: 1180, height: 820, minWidth: 820, minHeight: 620,
    frame: false, transparent: true, backgroundColor: '#00000000',
    show: false, title: '栖伴 · Qiban',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true,
      nodeIntegration: false, sandbox: true, backgroundThrottling: true,
    },
  })
  const trusted = url => {
    try { return new URL(url).origin === serverUrl } catch { return false }
  }
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  mainWindow.webContents.on('will-navigate', (event, url) => { if (!trusted(url)) event.preventDefault() })
  mainWindow.webContents.session.setPermissionRequestHandler((contents, permission, callback, details) => {
    callback(contents === mainWindow.webContents && trusted(details.requestingUrl)
      && permission === 'media' && !details.mediaTypes?.includes('video'))
  })
  mainWindow.webContents.session.setPermissionCheckHandler((contents, permission, origin) =>
    contents === mainWindow.webContents && trusted(origin) && permission === 'media')
  mainWindow.webContents.session.webRequest.onHeadersReceived((details, callback) => {
    const headers = { ...details.responseHeaders }
    if (trusted(details.url)) headers['Content-Security-Policy'] = [
      "default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self' https: wss: ws:; worker-src 'self' blob:; object-src 'none'; frame-src 'none'",
    ]
    callback({ responseHeaders: headers })
  })
  const senderAllowed = event => event.sender === mainWindow.webContents && trusted(event.senderFrame.url)
  ipcMain.on('qiban:minimize', event => { if (senderAllowed(event)) mainWindow.minimize() })
  ipcMain.on('qiban:close', event => { if (senderAllowed(event)) app.quit() })
  ipcMain.handle('qiban:pet', (event, value) => senderAllowed(event) && typeof value === 'boolean' ? togglePet(value) : false)
  ipcMain.handle('qiban:top', (event, value) => {
    if (!senderAllowed(event) || typeof value !== 'boolean') return false
    pinned = value
    mainWindow.setAlwaysOnTop(petMode || pinned)
    return pinned
  })
  ipcMain.on('qiban:passthrough', (event, value) => { if (senderAllowed(event) && typeof value === 'boolean') setClickThrough(value) })
  const trayIcon = nativeImage.createFromPath(path.join(__dirname, 'icon.png'))
  tray = new Tray(trayIcon)
  tray.setToolTip('栖伴 · Qiban')
  tray.on('double-click', () => { togglePet(false); mainWindow.show(); mainWindow.focus() })
  updateMenu()
  globalShortcut.register('CommandOrControl+Alt+Q', () => { setClickThrough(false); mainWindow.show(); mainWindow.focus() })
  mainWindow.once('ready-to-show', () => { if (process.env.QIBAN_TEST_HIDDEN !== '1') mainWindow.show() })
  mainWindow.on('closed', () => { mainWindow = undefined; app.quit() })
  await mainWindow.loadURL(serverUrl)
}

app.on('before-quit', () => {
  globalShortcut.unregisterAll()
  tray?.destroy()
  // Only terminate the backend that this app started, never an unrelated process occupying the port.
  if (backend && backend.exitCode === null) backend.kill()
})
app.on('window-all-closed', () => app.quit())
