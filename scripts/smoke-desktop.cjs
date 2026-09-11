// Exercises the actual installed Electron app, preload, CSP and renderer without opening a visible window.
const { app, BrowserWindow } = require('electron')
const { mkdirSync, writeFileSync } = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const root = process.env.QIBAN_SMOKE_ROOT || path.resolve(__dirname, '..')
process.env.QIBAN_TEST_HIDDEN = '1'
require(path.join(root, 'desktop/main.cjs'))
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
  if (process.env.QIBAN_SMOKE_MIGRATION === '1') {
    const restored = await win.webContents.executeJavaScript(`(async () => {
      const boot = await (await fetch('/api/bootstrap', {method:'POST'})).json()
      const settings = await (await fetch('/api/settings')).json()
      const memories = await (await fetch('/api/memories')).json()
      return {name:boot.profile.name, provider:settings.settings.chat_provider,
        keySaved:settings.settings.chats.anthropic.api_key_set, memories:memories.map(m=>m.text)}
    })()`)
    assert.equal(restored.name, '迁移验证伙伴')
    assert.equal(restored.provider, 'anthropic')
    assert.equal(restored.keySaved, true)
    assert.ok(restored.memories.includes('迁移验证：喜欢乌龙茶'))
    console.log('MIGRATION_SMOKE_PASSED', JSON.stringify(restored))
    app.quit()
    return
  }
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
  const output = path.join(root, 'output/qa')
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
  const settings = process.env.QIBAN_SMOKE_SETTINGS === '1' ? await checkSettings(win, output) : 'skipped'
  writeFileSync(path.join(output, 'desktop-smoke.json'), JSON.stringify({passed:true, state, speech, settings}, null, 2))
  console.log('DESKTOP_SMOKE_PASSED', JSON.stringify({state, speech, settings}))
  app.quit()
}
run().catch(error => {
  const output = path.join(root, 'output/qa')
  mkdirSync(output, {recursive:true})
  writeFileSync(path.join(output, 'desktop-smoke.json'), JSON.stringify({passed:false, error:String(error.stack)}, null, 2))
  console.error(error); process.exitCode = 1; app.quit()
})

async function checkSettings(win, output) {
  const { createServer } = require('node:http')
  const requests = []
  const server = createServer(async (req, res) => {
    let text = ''
    for await (const chunk of req) text += chunk
    const body = JSON.parse(text)
    requests.push({path:req.url, model:body.model})
    const events = req.url.endsWith('/messages')
      ? [{type:'content_block_delta',delta:{type:'text_delta',text:'OK'}},{type:'message_stop'}]
      : req.url.endsWith('/responses')
        ? [{type:'response.output_text.delta',delta:'OK'},{type:'response.completed'}]
        : [{choices:[{delta:{content:'OK'}}]}, '[DONE]']
    res.writeHead(200, {'Content-Type':'text/event-stream'})
    res.end(events.map(event=>'data: '+(typeof event === 'string' ? event : JSON.stringify(event))+'\n\n').join(''))
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const url = `http://127.0.0.1:${server.address().port}/v1`
  const evaluate = script => win.webContents.executeJavaScript(script)
  const until = async expression => {
    for (let i=0; i<120; i++) {
      if (await evaluate(expression)) return
      await sleep(100)
    }
    throw new Error('UI condition timed out: ' + expression + ' / ' + await evaluate("document.querySelector('.connection-error')?.textContent"))
  }
  try {
    await evaluate(`document.querySelector('[aria-label="设置"]').click()`)
    await until(`!!document.querySelector('[aria-label="聊天接口类型"]')`)
    for (const provider of ['openai','responses','anthropic']) {
      await evaluate(`(() => { const el=document.querySelector('[aria-label="聊天接口类型"]'); el.value=${JSON.stringify(provider)}; el.dispatchEvent(new Event('change',{bubbles:true})); })()`)
      await sleep(100)
      await evaluate(`(() => {
        for (const [label,value] of ${JSON.stringify([['聊天服务地址',url],['聊天模型名称','mock-model'],['聊天 API Key','qiban-smoke-fake-key']])}) {
          const el=document.querySelector('[aria-label="'+label+'"]'); el.value=value; el.dispatchEvent(new Event('input',{bubbles:true}));
        }
      })()`)
      await sleep(100)
      await evaluate(`document.querySelector('.connection-actions .outline-button').click()`)
      await until(`document.querySelector('.connection-success')?.textContent.includes('连接成功')`)
      await evaluate(`document.querySelector('.connection-actions .primary-button').click()`)
      await until(`document.querySelector('.connection-success')?.textContent.includes('设置已保存')`)
      assert.equal(await evaluate(`document.querySelector('[aria-label="聊天 API Key"]').value`), '')
      assert.equal(await evaluate(`document.querySelector('[aria-label="聊天 API Key"]').type`), 'password')
    }
    assert.deepEqual(requests.map(r=>r.path), ['/v1/chat/completions','/v1/responses','/v1/messages'])
    await evaluate(`document.querySelector('.settings-body').scrollTop = 0`)
    await sleep(250)
    writeFileSync(path.join(output,'desktop-settings.png'), (await win.webContents.capturePage()).toPNG())
    await evaluate(`(async () => {
      const boot=await (await fetch('/api/bootstrap',{method:'POST'})).json()
      const profile=boot.profile; profile.name='迁移验证伙伴'
      const response=await fetch('/api/profile',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(profile)})
      if (!response.ok) throw new Error('Cannot seed migration profile')
      await fetch('/api/memories',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:'迁移验证：喜欢乌龙茶'})})
    })()`)
    return {providers:requests.map(r=>r.path),masked:true}
  } finally {
    await new Promise(resolve=>server.close(resolve))
  }
}
