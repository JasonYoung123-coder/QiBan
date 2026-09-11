import type { Language } from './contracts'

type AudioHooks = { speaking: (active: boolean) => void; level: (value: number) => void; source: (value: 'system' | 'audio' | '') => void }

/** Owns one playback path. Stop invalidates synthesis fetches, decoded buffers and late browser events. */
export class SpeechPlayer {
  private epoch = 0
  private context?: AudioContext
  private source?: AudioBufferSourceNode | MediaStreamAudioSourceNode
  private analyser?: AnalyserNode
  private frame = 0
  private controller?: AbortController

  constructor(private hooks: AudioHooks) {}

  async arm(): Promise<void> {
    this.context ??= new AudioContext()
    if (this.context.state === 'suspended') await this.context.resume()
  }

  stop(): void {
    this.epoch += 1
    this.controller?.abort()
    this.controller = undefined
    if (this.source instanceof AudioBufferSourceNode) {
      this.source.onended = null
      try { this.source.stop() } catch { /* Already ended. */ }
    }
    this.source?.disconnect()
    this.analyser?.disconnect()
    this.source = undefined
    this.analyser = undefined
    cancelAnimationFrame(this.frame)
    speechSynthesis.cancel()
    this.hooks.speaking(false)
    this.hooks.level(0)
    this.hooks.source('')
  }

  async play(text: string, language: Language, cloud: boolean): Promise<void> {
    this.stop()
    const epoch = this.epoch
    const selectedLanguage = language === 'auto' ? (/[\u4e00-\u9fff]/.test(text) ? 'zh-CN' : 'en-US') : language
    if (!cloud) {
      const voices = speechSynthesis.getVoices()
      const voice = voices.find(item => item.lang.toLowerCase().startsWith(selectedLanguage.slice(0, 2)))
      if (voices.length && !voice) throw new Error(`系统没有${selectedLanguage === 'zh-CN' ? '中文' : '英文'}朗读声音，请在系统中安装或接入语音服务。`)
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = selectedLanguage
      if (voice) utterance.voice = voice
      utterance.rate = 0.98
      utterance.onstart = () => {
        if (epoch !== this.epoch) return
        this.hooks.source('system')
        this.hooks.speaking(true)
        // Browser speech synthesis exposes no PCM. This is deliberately labelled as basic mouth animation.
        const animate = () => {
          if (epoch !== this.epoch) return
          this.hooks.level(0.12 + Math.abs(Math.sin(performance.now() / 115)) * 0.18)
          this.frame = requestAnimationFrame(animate)
        }
        animate()
      }
      const finish = () => { if (epoch === this.epoch) this.stop() }
      utterance.onend = finish
      utterance.onerror = finish
      speechSynthesis.speak(utterance)
      return
    }
    await this.arm()
    if (epoch !== this.epoch) return
    this.controller = new AbortController()
    let response: Response
    try { response = await fetch('/api/audio/speech', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, language }), signal: this.controller.signal,
    }) } catch (cause) { if (epoch !== this.epoch) return; throw cause }
    if (epoch !== this.epoch) return
    if (!response.ok) throw new Error('语音合成暂不可用，请检查服务或改用系统朗读。')
    const buffer = await this.context!.decodeAudioData(await response.arrayBuffer())
    if (epoch !== this.epoch) return
    const source = this.context!.createBufferSource()
    source.buffer = buffer
    this.connect(source, epoch)
    source.onended = () => { if (epoch === this.epoch) this.stop() }
    source.start()
  }

  async playTrack(track: MediaStreamTrack): Promise<void> {
    this.stop()
    const epoch = this.epoch
    await this.arm()
    if (epoch !== this.epoch) return
    this.connect(this.context!.createMediaStreamSource(new MediaStream([track])), epoch)
  }

  private connect(source: AudioBufferSourceNode | MediaStreamAudioSourceNode, epoch: number): void {
    this.source = source
    this.analyser = this.context!.createAnalyser()
    this.analyser.fftSize = 256
    source.connect(this.analyser)
    this.analyser.connect(this.context!.destination)
    const samples = new Float32Array(this.analyser.fftSize)
    let smoothed = 0
    this.hooks.source('audio')
    this.hooks.speaking(true)
    const sample = () => {
      if (epoch !== this.epoch || !this.analyser) return
      this.analyser.getFloatTimeDomainData(samples)
      const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length)
      const target = Math.min(1, Math.max(0, (rms - 0.012) * 8))
      smoothed += (target - smoothed) * (target > smoothed ? 0.55 : 0.3)
      this.hooks.level(smoothed)
      this.frame = requestAnimationFrame(sample)
    }
    sample()
  }

  async dispose(): Promise<void> { this.stop(); await this.context?.close() }
}
