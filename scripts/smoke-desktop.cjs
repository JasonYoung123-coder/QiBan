// Exercises the actual installed Electron app, preload, CSP and renderer without opening a visible window.
const { app, BrowserWindow } = require('electron')
const { mkdirSync, writeFileSync } = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
process.env.QIBAN_TEST_HIDDEN = '1'
require('../desktop/main.cjs')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
async function run() {
  await app.whenReady()
  let win
  for (let i = 0; i < 160; i++) {
    win = BrowserWindow.getAllWindows()[0]
    win?.webContents.setBackgroundThrottling(false)
    if (win && !win.webContents.isLoading()) {
      const ready = await win.webContents.executeJavaScript("Boolean(document.querySelector('canvas') && !document.querySelector('.avatar-status') && !document.querySelector('[aria-label=\"聊天输入\"]').disabled)").catch(() => false)
      if (ready) break
    }
    await sleep(250)
  }
  assert.ok(win, 'native window created')
  const state = await win.webContents.executeJavaScript(`({
    canvas: !!document.querySelector('canvas'), status: document.querySelector('.avatar-status')?.textContent,
    node: typeof require, bridge: typeof window.qibanDesktop?.setPetMode,
    voices: speechSynthesis.getVoices().map(v => ({name:v.name, lang:v.lang})),
    ready: !document.querySelector('[aria-label="聊天输入"]').disabled,
    csp: [...document.scripts].every(s => !s.src || s.src.startsWith(location.origin))
  })`)
  assert.equal(state.node, 'undefined')
  assert.equal(state.bridge, 'function')
  assert.equal(state.canvas, true)
  assert.equal(state.status, undefined)
  assert.equal(state.ready, true)
  assert.equal(win.webContents.getLastWebPreferences().sandbox, true)
  const speech = await win.webContents.executeJavaScript(`(async () => {
    const boot = await (await fetch('/api/bootstrap', {method:'POST'})).json()
    if (boot.capabilities.tts_provider !== 'windows') return {skipped:'No local Windows TTS'}
    const context = new AudioContext()
    const results = []
    try {
      for (const [language,text] of [['zh-CN','你好，我在这里。'],['en-US','Hello. I am here.']]) {
        const response = await fetch('/api/audio/speech', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text,language})})
        if (!response.ok) throw new Error('Local speech HTTP status: ' + response.status)
        const decoded = await context.decodeAudioData(await response.arrayBuffer())
        results.push({language, seconds:decoded.duration, sampleRate:decoded.sampleRate})
      }
      return results
    } finally { await context.close() }
  })()`)
  if (Array.isArray(speech)) assert.ok(speech.every(item => item.seconds > 1), 'HTTP audio decodes in Electron')
  const output = path.resolve(__dirname, '../output/qa')
  mkdirSync(output, {recursive:true})
  if (process.env.QIBAN_SMOKE_SHOW === '1') win.showInactive()
  await sleep(600)
  writeFileSync(path.join(output, 'desktop-chat.png'), (await win.webContents.capturePage()).toPNG())
  assert.equal(await win.webContents.executeJavaScript('window.qibanDesktop.setPetMode(true)'), true)
  await sleep(600)
  assert.ok(Math.abs(win.getBounds().width - 380) <= 2, 'pet width respects Windows DPI rounding')
  assert.equal(win.isAlwaysOnTop(), true)
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('.app-shell').classList.contains('pet-mode')"), true)
  writeFileSync(path.join(output, 'desktop-pet.png'), (await win.webContents.capturePage()).toPNG())
  await win.webContents.executeJavaScript('window.qibanDesktop.setPetMode(false)')
  assert.ok(Math.abs(win.getBounds().width - 1180) <= 2, 'restored normal bounds')
  await win.webContents.executeJavaScript('window.qibanDesktop.setAlwaysOnTop(true)')
  assert.equal(win.isAlwaysOnTop(), true)
  await win.webContents.executeJavaScript('window.qibanDesktop.setAlwaysOnTop(false)')
  assert.equal(win.isAlwaysOnTop(), false)
  writeFileSync(path.join(output, 'desktop-smoke.json'), JSON.stringify({passed:true, state, speech}, null, 2))
  console.log('DESKTOP_SMOKE_PASSED', JSON.stringify({state, speech}))
  app.quit()
}
run().catch(error => {
  const output = path.resolve(__dirname, '../output/qa')
  mkdirSync(output, {recursive:true})
  writeFileSync(path.join(output, 'desktop-smoke.json'), JSON.stringify({passed:false, error:String(error.stack)}, null, 2))
  console.error(error); process.exitCode = 1; app.quit()
})
