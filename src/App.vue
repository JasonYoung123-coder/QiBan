<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { ArrowUp, AudioLines, BookHeart, Check, ChevronRight, Heart, Leaf, LoaderCircle, MessageCircle,
  Mic, Minus, Monitor, Plus, Settings2, Sparkles, Square, Trash2, Upload, UserRound, Volume2, VolumeX, X } from 'lucide-vue-next'
import { Room, RoomEvent, Track } from 'livekit-client'
import Live2DStage from './components/Live2DStage.vue'
import ConnectionSettings from './components/ConnectionSettings.vue'
import ConversationHistory from './components/ConversationHistory.vue'
import { api, consumeEvents } from './lib/api'
import { SpeechPlayer } from './lib/audio'
import { TurnGate } from './lib/turn-gate'
import { importModelFiles } from './lib/model-files'
import { characterFor, characterPresets } from './lib/presets'
import type { ModelDefinition } from './lib/model-files'
import type { AvatarState, Bootstrap, Capabilities, ConversationSummary, Language, Memory, Message, Mood, Profile, StreamEvent } from './lib/contracts'

const profile = ref<Profile>({ id: '', revision: 1, name: '栖栖', user_name: '', persona: '', language: 'auto', character_id: 'hiyori' })
const draft = ref({ ...profile.value })
const capabilities = ref<Capabilities>({ chat: 'demo', stt: false, tts: false, realtime: false, model: '' })
const conversation = ref('')
const conversations = ref<ConversationSummary[]>([])
const historyLoading = ref(false)
const historyError = ref('')
const switchingConversation = ref(false)
const conversationDrafts = new Map<string, string>()
let historyRequest = 0
const messages = ref<Message[]>([])
const memories = ref<Memory[]>([])
const input = ref('')
const memoryInput = ref('')
const editingMemory = ref('')
const tab = ref<'chat' | 'persona' | 'memory' | 'settings'>('chat')
const ready = ref(false)
const busy = ref(false)
const saving = ref(false)
const speaking = ref(false)
const mouth = ref(0)
const mood = ref<Mood>('warm')
const audioSource = ref<'system' | 'audio' | ''>('')
const readAloud = ref(localStorage.getItem('qiban.readAloud') === 'true')
const lowMotion = ref(localStorage.getItem('qiban.lowMotion') === 'true')
const petMode = ref(false)
const topmost = ref(false)
const error = ref('')
const toast = ref('')
const modelName = ref('Live2D')
const modelReady = ref(false)
const customModel = shallowRef<ModelDefinition>()
const character = computed(() => characterFor(profile.value.character_id))
function chooseCharacter(preset: typeof characterPresets[number]): void {
  Object.assign(draft.value, { character_id: preset.id, name: preset.name, persona: preset.persona })
}
watch(() => profile.value.character_id, () => {
  customModel.value = undefined
  importedDispose?.(); importedDispose = undefined
  modelReady.value = false
})
const chatScroll = ref<HTMLDivElement>()
const inputElement = ref<HTMLTextAreaElement>()
const fileInput = ref<HTMLInputElement>()
const recording = ref(false)
const microphonePending = ref(false)
const room = shallowRef<Room>()
const connecting = ref(false)
const liveState = ref<AvatarState>('listening')
const liveCaption = ref('')
const desktop = window.qibanDesktop
const gate = new TurnGate()
let controller: AbortController | undefined
let currentGeneration = ''
let actionEpoch = 0
let currentAssistant: Message | undefined
let toastTimer: ReturnType<typeof setTimeout>
let recorder: MediaRecorder | undefined
let microphone: MediaStream | undefined
let recordTimer: ReturnType<typeof setTimeout>
let captureEpoch = 0
let inputRevision = 0
watch(input, () => { inputRevision += 1 }, { flush: 'sync' })
let importedDispose: (() => void) | undefined
let removeDesktopListener: (() => void) | undefined
const player = new SpeechPlayer({
  speaking: value => { speaking.value = value },
  level: value => { mouth.value = value },
  source: value => { audioSource.value = value },
})
const state = computed<AvatarState>(() => room.value ? liveState.value : recording.value ? 'listening' : speaking.value ? 'speaking' : busy.value ? 'thinking' : 'idle')
const stateText = computed(() => ({ idle: '在这里，陪着你', listening: '我在听', thinking: '正在回应', speaking: '正在说话' })[state.value])
const lastAssistant = computed(() => [...messages.value].reverse().find(message => message.role === 'assistant' && message.text))
const voiceLabel = computed(() => capabilities.value.tts_provider === 'volcengine' ? '火山引擎语音'
  : capabilities.value.tts_provider === 'windows' ? 'Windows 本地朗读' : capabilities.value.tts ? '已配置的语音服务' : '浏览器系统朗读')

function notify(message: string): void {
  toast.value = message
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 4200)
}

async function load(): Promise<void> {
  try {
    const data = await api<Bootstrap>('/bootstrap', { method: 'POST' })
    profile.value = data.profile
    draft.value = { ...data.profile }
    capabilities.value = data.capabilities
    conversation.value = data.conversation_id
    await refreshConversations()
    try {
      const last = localStorage.getItem(`qiban.conversation.${profile.value.id}`)
      if (last && conversations.value.some(item => item.id === last)) conversation.value = last
    } catch { /* Local history remains available if browser storage is disabled. */ }
    const [history, facts] = await Promise.all([
      api<Message[]>(`/conversations/${conversation.value}/messages`), api<Memory[]>('/memories'),
    ])
    messages.value = history
    rememberConversation()
    memories.value = facts
    ready.value = true
    error.value = ''
    await scrollDown()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '本地服务尚未启动。' }
}

function rememberConversation(): void {
  try { localStorage.setItem(`qiban.conversation.${profile.value.id}`, conversation.value) }
  catch { /* Selection persistence is optional; the database retains every conversation. */ }
}

async function refreshConversations(): Promise<void> {
  const request = ++historyRequest
  historyLoading.value = true
  try {
    const list = await api<ConversationSummary[]>('/conversations')
    if (request !== historyRequest) return
    conversations.value = list
    historyError.value = ''
  } catch {
    if (request === historyRequest) historyError.value = '历史列表暂时未能加载。'
  } finally {
    if (request === historyRequest) historyLoading.value = false
  }
}

async function scrollDown(): Promise<void> {
  await nextTick()
  chatScroll.value?.scrollTo({ top: chatScroll.value.scrollHeight, behavior: 'smooth' })
}

async function stop(): Promise<number> {
  if (room.value) await leaveCall()
  const epoch = ++actionEpoch
  const oldGeneration = currentGeneration
  const oldAssistant = currentAssistant
  const oldConversation = conversation.value
  currentGeneration = ''
  currentAssistant = undefined
  gate.invalidate()
  player.stop()
  controller?.abort()
  controller = undefined
  busy.value = false
  if (oldGeneration) {
    await api(`/conversations/${oldConversation}/interrupt`, {
      method: 'POST', body: JSON.stringify({ generation_id: oldGeneration, displayed_text: oldAssistant?.text ?? '' }),
    }).catch(() => { /* The server may already have invalidated this generation after a profile/memory edit. */ })
  }
  return epoch
}

async function send(preset?: string): Promise<void> {
  const text = (preset ?? input.value).trim()
  if (!text || !ready.value || switchingConversation.value || connecting.value || room.value || recording.value || microphonePending.value) return
  const attempt = await stop()
  if (attempt !== actionEpoch) return
  if (readAloud.value && capabilities.value.tts) void player.arm()
  error.value = ''
  input.value = ''
  tab.value = 'chat'
  busy.value = true
  mood.value = /累|难过|烦|tired|sad|stress/i.test(text) ? 'concerned' : 'warm'
  const ticket = gate.begin(conversation.value)
  const clientTurnId = crypto.randomUUID()
  messages.value.push({ id: clientTurnId, role: 'user', text, generation_id: '', delivery_state: 'delivered' })
  messages.value.push({ id: `pending-${clientTurnId}`, role: 'assistant', text: '', generation_id: '', delivery_state: 'pending' })
  const answer = messages.value[messages.value.length - 1]
  currentAssistant = answer
  controller = new AbortController()
  let generated = false
  let answerLanguage: Language = profile.value.language
  try {
    const response = await fetch(`/api/conversations/${conversation.value}/turns`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, client_turn_id: clientTurnId }), signal: controller.signal,
    })
    await consumeEvents(response, (raw) => {
      const event = raw as StreamEvent
      if (!gate.accept(ticket, event)) return
      if (event.type === 'assistant.started') {
        currentGeneration = event.generation_id
        answer.generation_id = event.generation_id
        answer.id = event.payload.message_id ?? answer.id
        answerLanguage = event.payload.language ?? answerLanguage
      } else if (event.type === 'assistant.delta') {
        answer.text += event.payload.text ?? ''
        void scrollDown()
      } else if (event.type === 'assistant.generated') {
        generated = true
        answer.delivery_state = 'delivered'
      } else if (event.type === 'assistant.error') {
        error.value = event.payload.message ?? '回复未完成，请重试。'
        answer.delivery_state = 'failed'
      } else if (event.type === 'assistant.interrupted') {
        answer.delivery_state = 'interrupted'
      }
    })
    if (gate.current(ticket) && currentGeneration && answer.text) {
      await api(`/conversations/${conversation.value}/delivery`, {
        method: 'POST', body: JSON.stringify({ generation_id: currentGeneration, displayed_text: answer.text }),
      })
    }
    if (gate.current(ticket) && generated && readAloud.value) {
      busy.value = false
      void player.play(answer.text, answerLanguage, capabilities.value.tts).catch(cause => {
        if (gate.current(ticket)) notify(cause instanceof Error ? cause.message : '朗读未能开始。')
      })
    }
  } catch (cause) {
    if (gate.current(ticket) && !(cause instanceof DOMException && cause.name === 'AbortError')) {
      error.value = cause instanceof Error ? cause.message : '连接中断，请重试。'
      answer.delivery_state = 'failed'
    }
  } finally {
    if (gate.current(ticket)) busy.value = false
    void refreshConversations()
    await scrollDown()
  }
}

async function freshConversation(): Promise<void> {
  await openConversation()
}

async function openConversation(id?: string): Promise<void> {
  if (!ready.value || switchingConversation.value || connecting.value || saving.value || id === conversation.value) return
  // Lock before awaiting cancellation so rapid clicks cannot start overlapping transitions.
  switchingConversation.value = true
  try {
    stopRecording(false)
    const attempt = await stop()
    if (attempt !== actionEpoch) return
    const target = id ?? (await api<{ id: string }>('/conversations', { method: 'POST' })).id
    const history = id ? await api<Message[]>(`/conversations/${target}/messages`) : []
    if (attempt !== actionEpoch) return
    // Commit selection only after loading succeeds; keep each conversation's unsent draft.
    conversationDrafts.set(conversation.value, input.value)
    conversation.value = target
    messages.value = history
    input.value = conversationDrafts.get(target) ?? ''
    rememberConversation()
    tab.value = 'chat'
    error.value = ''
    if (!id) notify('已开启新聊天，之前的内容可在「历史聊天」中找回。')
    await scrollDown()
  } catch (cause) { notify(cause instanceof Error ? cause.message : '未能打开聊天，请重试。') }
  finally {
    switchingConversation.value = false
    void refreshConversations()
  }
}

async function saveProfile(): Promise<void> {
  saving.value = true
  try {
    await stop()
    profile.value = await api<Profile>('/profile', { method: 'PUT', body: JSON.stringify(draft.value) })
    draft.value = { ...profile.value }
    notify('人设已保存，从下一条回复开始生效。')
  } catch (cause) { notify(cause instanceof Error ? cause.message : '人设保存失败。') }
  finally { saving.value = false }
}

async function saveMemory(): Promise<void> {
  if (!memoryInput.value.trim()) return
  saving.value = true
  try {
    await stop()
    await api(editingMemory.value ? `/memories/${editingMemory.value}` : '/memories', {
      method: editingMemory.value ? 'PUT' : 'POST', body: JSON.stringify({ text: memoryInput.value }),
    })
    memoryInput.value = ''
    editingMemory.value = ''
    memories.value = await api<Memory[]>('/memories')
    notify('记忆已保存，后续聊天会使用更新后的内容。')
  } catch (cause) { notify(cause instanceof Error ? cause.message : '记忆保存失败。') }
  finally { saving.value = false }
}

async function forget(memory: Memory): Promise<void> {
  try {
    await stop()
    await api(`/memories/${memory.id}`, { method: 'DELETE' })
    memories.value = memories.value.filter(item => item.id !== memory.id)
    if (editingMemory.value === memory.id) { editingMemory.value = ''; memoryInput.value = '' }
    notify('已忘记这条保存的记忆。历史聊天仍可查看，旧上下文不再参与新回复。')
  } catch (cause) { notify(cause instanceof Error ? cause.message : '删除未完成。') }
}

function toggleReadAloud(): void {
  readAloud.value = !readAloud.value
  localStorage.setItem('qiban.readAloud', String(readAloud.value))
  if (!readAloud.value) player.stop()
  else { speechSynthesis.getVoices(); notify(capabilities.value.tts ? '已开启回复朗读。' : '已开启系统朗读；声音取决于电脑安装的语音包。') }
}

function toggleLowMotion(): void {
  lowMotion.value = !lowMotion.value
  localStorage.setItem('qiban.lowMotion', String(lowMotion.value))
}

async function replay(message: Message): Promise<void> {
  if (busy.value || room.value || switchingConversation.value || connecting.value) return
  try { await player.play(message.text, profile.value.language, capabilities.value.tts) }
  catch (cause) { notify(cause instanceof Error ? cause.message : '朗读未完成。') }
}

async function selectModel(event: Event): Promise<void> {
  const files = Array.from((event.target as HTMLInputElement).files ?? [])
  if (!files.length) return
  await stop()
  try {
    const imported = await importModelFiles(files)
    const previousDispose = importedDispose
    customModel.value = imported.definition
    importedDispose = imported.dispose
    // Existing textures may finish a frame after the model prop changes.
    setTimeout(() => previousDispose?.(), 1000)
    notify('角色正在加载。自定义模型暂仅保留在本次启动中。')
  } catch (cause) { notify(cause instanceof Error ? cause.message : '角色包读取失败。') }
  if (fileInput.value) fileInput.value.value = ''
}

function stopRecording(submit: boolean): void {
  if (!submit) captureEpoch += 1
  clearTimeout(recordTimer)
  if (recorder && recorder.state !== 'inactive') {
    if (!submit) recorder.onstop = null
    recorder.stop()
  }
  microphone?.getTracks().forEach(track => track.stop())
  microphone = undefined
  recording.value = false
  microphonePending.value = false
}

async function toggleRecording(): Promise<void> {
  if (switchingConversation.value || connecting.value) return
  if (!capabilities.value.stt) { tab.value = 'settings'; notify('录音识别需要先接入语音服务，现在可用文字聊天和系统朗读。'); return }
  if (recording.value) { stopRecording(true); return }
  if (microphonePending.value) { stopRecording(false); return }
  const attempt = await stop()
  if (attempt !== actionEpoch || switchingConversation.value) return
  const capture = ++captureEpoch
  microphonePending.value = true
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
    if (capture !== captureEpoch) { stream.getTracks().forEach(track => track.stop()); return }
    microphone = stream
    microphonePending.value = false
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : ''
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {})
    const chunks: BlobPart[] = []
    const actualType = recorder.mimeType
    const targetConversation = conversation.value
    const originalInputRevision = inputRevision
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
    recorder.onstop = async () => {
      stream.getTracks().forEach(track => track.stop())
      if (capture !== captureEpoch) return
      recording.value = false
      const data = new FormData()
      data.append('audio', new Blob(chunks, { type: actualType }), 'recording.webm')
      data.append('language', profile.value.language)
      try {
        const result = await api<{ text: string }>('/audio/transcribe', { method: 'POST', body: data })
        if (capture === captureEpoch && targetConversation === conversation.value && originalInputRevision === inputRevision) {
          input.value = result.text; notify('已识别，请确认文字后发送。'); inputElement.value?.focus()
        }
      } catch (cause) { if (capture === captureEpoch) notify(cause instanceof Error ? cause.message : '录音识别未完成。') }
    }
    recorder.start()
    recording.value = true
    recordTimer = setTimeout(() => stopRecording(true), 55000)
  } catch (cause) {
    microphonePending.value = false
    stopRecording(false)
    notify(cause instanceof Error ? `无法使用麦克风：${cause.message}` : '请检查麦克风权限。')
  }
}

async function leaveCall(): Promise<void> {
  const existing = room.value
  const callConversation = conversation.value
  const epoch = actionEpoch
  room.value = undefined
  player.stop()
  liveCaption.value = ''
  await existing?.disconnect()
  if (existing) await api(`/conversations/${callConversation}/voice-end`, { method: 'POST' }).catch(() => {})
  if (ready.value) {
    const history = await api<Message[]>(`/conversations/${callConversation}/messages`)
    if (conversation.value === callConversation && actionEpoch === epoch) messages.value = history
    void refreshConversations()
  }
}

async function toggleCall(): Promise<void> {
  if (connecting.value || switchingConversation.value) return
  if (room.value) { await leaveCall(); return }
  if (!capabilities.value.realtime) { tab.value = 'settings'; notify('实时通话需要配置 LiveKit 与语音服务。'); return }
  connecting.value = true
  try {
    stopRecording(false)
    await stop()
    await player.arm()
    const connection = await api<{ url: string; token: string }>(`/conversations/${conversation.value}/voice-token`, { method: 'POST' })
    const next = new Room({ audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
    room.value = next
    next.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Audio) void player.playTrack(track.mediaStreamTrack).catch(cause => notify(String(cause)))
    })
    next.on(RoomEvent.ParticipantAttributesChanged, (attributes) => {
      const agent = attributes['lk.agent.state']
      if (agent === 'speaking' || agent === 'listening') liveState.value = agent
      else if (agent === 'thinking') liveState.value = 'thinking'
    })
    next.on(RoomEvent.TranscriptionReceived, segments => { liveCaption.value = segments.map(segment => segment.text).join(' ') })
    const callConversation = conversation.value
    next.on(RoomEvent.Disconnected, () => {
      if (room.value === next) {
        room.value = undefined; player.stop(); liveCaption.value = ''
        void api(`/conversations/${callConversation}/voice-end`, { method: 'POST' }).catch(() => {})
        void api<Message[]>(`/conversations/${callConversation}/messages`).then(history => {
          if (conversation.value === callConversation) messages.value = history
        }).catch(() => {})
      }
    })
    await next.connect(connection.url, connection.token)
    await next.localParticipant.setMicrophoneEnabled(true)
    notify('已接入实时通话，点击结束按钮可关闭麦克风。')
  } catch (cause) { await leaveCall(); notify(cause instanceof Error ? cause.message : '通话连接失败。') }
  finally { connecting.value = false }
}

async function togglePet(): Promise<void> {
  if (!desktop) { notify('请使用桌面启动脚本打开常驻桌宠模式。'); return }
  petMode.value = await desktop.setPetMode(!petMode.value)
}

async function prepareSettingsSave(): Promise<void> {
  stopRecording(false)
  await stop()
}

async function changeLanguage(event: Event): Promise<void> {
  const language = (event.target as HTMLSelectElement).value as Language
  await stop()
  try {
    profile.value = await api<Profile>('/profile', { method: 'PUT', body: JSON.stringify({ ...profile.value, language }) })
    draft.value.language = profile.value.language
  } catch (cause) { notify(cause instanceof Error ? cause.message : '语言设置未能保存。') }
}

onMounted(() => {
  void load()
  speechSynthesis.getVoices()
  removeDesktopListener = desktop?.onPetMode(value => { petMode.value = value })
})
onBeforeUnmount(() => {
  gate.invalidate()
  controller?.abort()
  stopRecording(false)
  void room.value?.disconnect()
  if (room.value) void fetch(`/api/conversations/${conversation.value}/voice-end`, { method: 'POST', keepalive: true })
  void player.dispose()
  clearTimeout(toastTimer)
  importedDispose?.()
  removeDesktopListener?.()
})
</script>

<template>
  <div class="app-shell" :class="{ 'pet-mode': petMode }">
    <aside class="rail" aria-label="主导航">
      <div class="brand-symbol" title="栖伴"><Leaf :size="24" /></div>
      <nav>
        <button :class="{ active: tab === 'chat' }" aria-label="聊天" @click="tab = 'chat'"><MessageCircle :size="21" /><span>聊天</span></button>
        <button :class="{ active: tab === 'persona' }" aria-label="人设" @click="tab = 'persona'; draft = { ...profile }"><UserRound :size="21" /><span>人设</span></button>
        <button :class="{ active: tab === 'memory' }" aria-label="记忆" @click="tab = 'memory'"><BookHeart :size="21" /><span>记忆</span></button>
      </nav>
      <button class="rail-settings" :class="{ active: tab === 'settings' }" aria-label="设置" @click="tab = 'settings'"><Settings2 :size="21" /><span>设置</span></button>
      <span class="rail-edition">PREVIEW</span>
    </aside>

    <main class="companion-space">
      <header class="space-header">
        <div class="brand-type">栖伴<span>QIBAN</span></div>
        <div class="header-actions">
          <button class="icon-button" aria-label="切换桌宠模式" title="切换桌宠模式" @click="togglePet"><Monitor :size="18" /></button>
          <button v-if="desktop" class="icon-button" aria-label="最小化" @click="desktop.minimize()"><Minus :size="18" /></button>
        </div>
      </header>
      <div class="space-caption"><span class="caption-line" /> 给日常留一点柔软</div>
      <div class="avatar-scene">
        <div class="scene-glow" /><div class="scene-floor" />
        <Live2DStage :mouth="mouth" :state="state" :mood="mood" :low-motion="lowMotion" :pet-mode="petMode" :custom-model="customModel" :model-url="character.url" :model-label="character.model"
          @ready="name => { modelName = name; modelReady = true }" @error="value => { modelReady = false; notify(value) }"
          @interact="() => { if (!busy) { mood = 'happy'; notify(`${profile.name} 看向了你。`) } }" />
      </div>
      <div v-if="petMode" class="pet-controls">
        <button aria-label="返回聊天窗口" @click="togglePet"><MessageCircle :size="18" /> 聊聊天</button>
        <button aria-label="停止说话" @click="stop"><Square :size="16" /></button>
      </div>
      <div v-if="petMode && lastAssistant" class="pet-bubble">{{ lastAssistant.text.slice(0, 90) }}</div>
      <footer class="companion-footer">
        <div class="companion-name">{{ profile.name }}<span class="state-dot" :class="state" /></div>
        <p aria-live="polite">{{ stateText }}</p>
        <div class="presence-tools">
          <button :class="{ selected: readAloud }" :aria-pressed="readAloud" title="回复朗读" @click="toggleReadAloud"><Volume2 v-if="readAloud" :size="16" /><VolumeX v-else :size="16" />{{ readAloud ? '回复朗读' : '安静陪伴' }}</button>
          <button :aria-pressed="lowMotion" @click="toggleLowMotion"><Leaf :size="15" />{{ lowMotion ? '低动态' : '自然动作' }}</button>
        </div>
        <small class="model-credit">{{ customModel ? '自定义模型 · 本次启动有效' : `示例形象 ${character.model} © Live2D Inc.` }}<span v-if="!modelReady"> · 加载中</span></small>
      </footer>
    </main>

    <section class="conversation-panel">
      <header class="panel-header">
        <div><span class="eyebrow">{{ tab === 'chat' ? 'OUR LITTLE SPACE' : 'MAKE IT YOURS' }}</span><h1>{{ { chat: '此刻，想聊点什么？', persona: '让陪伴有自己的性格', memory: '值得记住的小事', settings: '按你的节奏相处' }[tab] }}</h1></div>
        <button v-if="tab === 'chat'" class="icon-button" aria-label="新聊天" title="开启新聊天" :disabled="!ready || switchingConversation || connecting || saving" @click="freshConversation"><LoaderCircle v-if="switchingConversation" :size="20" class="spin" /><Plus v-else :size="20" /></button>
        <button v-if="desktop" class="icon-button close-window" aria-label="关闭窗口" @click="desktop.close()"><X :size="18" /></button>
      </header>

      <template v-if="tab === 'chat'">
        <ConversationHistory :conversations="conversations" :active="conversation" :loading="historyLoading" :error="historyError" :disabled="!ready || switchingConversation || connecting || saving" @refresh="refreshConversations" @select="openConversation" />
        <div class="connection-strip" :class="{ connected: capabilities.chat === 'connected' }">
          <span class="connection-dot" />{{ capabilities.chat === 'connected' ? '聊天模型已配置' : '示范模式 · 在设置中连接你的模型' }}
          <button aria-label="查看连接设置" @click="tab = 'settings'"><ChevronRight :size="15" /></button>
        </div>
        <div ref="chatScroll" class="chat-history" aria-live="polite" aria-relevant="additions text">
          <div v-if="!messages.length" class="welcome-message">
            <span class="welcome-icon"><Sparkles :size="22" /></span>
            <h2>不用想好开场白。</h2>
            <p>开心的小事，没理清的思绪，<br>或者只是想找个地方待一会儿。</p>
            <span class="welcome-signature">{{ profile.name }} 在这里</span>
            <div class="conversation-starters">
              <button @click="send('今天有点累，想随便聊聊。')">今天有点累</button>
              <button @click="send('Can we chat in English for a bit?')">Let's talk in English</button>
              <button @click="send('你还记得我保存的偏好吗？')">聊聊你记得的小事</button>
            </div>
          </div>
          <article v-for="message in messages" :key="message.id" class="message" :class="message.role">
            <span class="message-author">{{ message.role === 'assistant' ? profile.name : profile.user_name || '你' }}</span>
            <div class="message-body"><span v-if="message.text">{{ message.text }}</span><span v-else-if="busy" class="typing-dots"><i /><i /><i /></span><span v-else class="message-unfinished">{{ message.delivery_state === 'failed' ? '这次回复未完成。' : '回复已停止。' }}</span></div>
            <button v-if="message.role === 'assistant' && message.text" class="message-play" aria-label="朗读这条回复" :disabled="busy || !!room || switchingConversation || connecting" @click="replay(message)"><Volume2 :size="13" /></button>
          </article>
          <div v-if="room" class="call-caption"><AudioLines :size="20" /><p>{{ liveCaption || '通话已连接，开始说话吧。' }}</p><button @click="leaveCall">结束通话</button></div>
        </div>
        <div v-if="error" class="error-banner" role="alert">{{ error }}<button v-if="!ready" @click="load">重新连接</button><button v-else aria-label="关闭错误提示" @click="error = ''"><X :size="14" /></button></div>
        <div class="composer-area">
          <div class="composer" :class="{ recording }">
            <textarea ref="inputElement" v-model="input" :disabled="!ready || !!room || recording || switchingConversation || connecting" :placeholder="recording ? '正在录音，再点一次麦克风结束…' : '慢慢说，我在听…'" aria-label="聊天输入" rows="2" maxlength="6000" @keydown.enter.exact.prevent="event => { if (!event.isComposing) send() }" />
            <div class="composer-bottom">
              <div class="composer-options">
                <button class="icon-button" :class="{ recording }" :disabled="!ready || !!room || switchingConversation || connecting" :aria-label="recording ? '结束录音' : '录音输入'" @click="toggleRecording"><Square v-if="recording" :size="18" /><LoaderCircle v-else-if="microphonePending" :size="18" class="spin" /><Mic v-else :size="18" /></button>
                <select :value="profile.language" aria-label="回复语言" :disabled="!ready || !!room || saving || switchingConversation || connecting" @change="changeLanguage"><option value="auto">自动跟随语言</option><option value="zh-CN">中文</option><option value="en-US">English</option></select>
              </div>
              <button v-if="busy || speaking" class="stop-button" aria-label="停止回复" @click="stop"><Square :size="15" />停止</button>
              <button v-else class="send-button" aria-label="发送消息" :disabled="!input.trim() || !ready || !!room || recording || switchingConversation || connecting" @click="send()"><ArrowUp :size="21" /></button>
            </div>
          </div>
          <div class="composer-footnote"><span>{{ audioSource === 'system' ? '系统朗读 · 基础口型动画' : voiceLabel }}</span><button :class="{ 'in-call': room }" :disabled="connecting || !ready || switchingConversation" @click="toggleCall"><AudioLines :size="14" />{{ connecting ? '连接中' : room ? '结束通话' : '实时通话' }}</button></div>
        </div>
      </template>

      <div v-else-if="tab === 'persona'" class="settings-body">
        <p class="section-intro">定义性格和表达习惯。换一种语言，仍然是同一个伙伴。</p>
        <form @submit.prevent="saveProfile">
          <div class="character-choices" aria-label="预设角色">
            <button v-for="preset in characterPresets" :key="preset.id" type="button" class="character-choice" :class="{ selected: draft.character_id === preset.id }" :aria-label="`选择${preset.name}`" :aria-pressed="draft.character_id === preset.id" @click="chooseCharacter(preset)">
              <span class="character-seal">{{ preset.name.slice(0,1) }}</span><span><strong>{{ preset.name }} · {{ preset.gender }}</strong><small>{{ preset.style }}</small></span><Check v-if="draft.character_id === preset.id" :size="16" />
            </button>
          </div>
          <p class="field-help">预设会填入形象、名字与人设，可继续调整后保存。声音可在设置中独立选择。</p>
          <div class="field-pair"><label>伙伴的名字<input v-model="draft.name" maxlength="40" required></label><label>怎么称呼你<input v-model="draft.user_name" maxlength="40" placeholder="按你喜欢的来"></label></div>
          <label>性格与相处方式<textarea v-model="draft.persona" rows="8" minlength="10" maxlength="6000" required placeholder="例如：温柔但不一味附和，愿意认真听，也会分享不同看法。" /></label>
          <div class="persona-presets"><span>试试一种感觉</span><button type="button" @click="draft.persona = '温柔、坦诚，有一点幽默。先听懂感受，再决定是否给建议。回答简短自然，不机械追问，不一味附和。'">温柔倾听</button><button type="button" @click="draft.persona = '开朗、好奇、幽默但不过度热情。像熟悉的朋友一样聊天，短句为主。允许不同意见，不用夸张赞美，不给用户压力。'">轻松朋友</button><button type="button" @click="draft.persona = '平静、细腻、尊重边界。少一些追问，多留一些空间。需要时提供具体帮助，平时可以安静相伴，中文和英文都用自然短句。'">安静相伴</button></div>
          <label>默认回复语言<select v-model="draft.language"><option value="auto">跟随我的语言</option><option value="zh-CN">中文</option><option value="en-US">English</option></select></label>
          <button class="primary-button" :disabled="saving || !ready || !!room"><Check :size="17" />{{ saving ? '保存中…' : '保存人设' }}</button>
          <small class="field-help">从下一条回复开始生效。系统如实表明 AI 身份。</small>
        </form>
      </div>

      <div v-else-if="tab === 'memory'" class="settings-body">
        <p class="section-intro">由你决定记住什么。支持修改和忘记，新的聊天也能用到。<span class="count-label">{{ memories.length }}/20</span></p>
        <form class="memory-form" @submit.prevent="saveMemory"><label>{{ editingMemory ? '修改这条记忆' : '记下一件小事' }}<textarea v-model="memoryInput" rows="3" maxlength="1000" placeholder="例如：我不喜欢被叫老板，叫我阿凡就好。" required /></label><div class="form-actions"><button v-if="editingMemory" type="button" class="text-button" @click="editingMemory = ''; memoryInput = ''">取消修改</button><button class="primary-button" :disabled="saving || !memoryInput.trim() || !!room"><Plus :size="16" />{{ editingMemory ? '保存修改' : '记住这件事' }}</button></div></form>
        <div v-if="!memories.length" class="empty-memory"><BookHeart :size="34" /><p>还没有需要记住的事。</p><small>重要的小事，等你愿意时再告诉我。</small></div>
        <article v-for="memory in memories" :key="memory.id" class="memory-item"><span class="memory-marker"><Heart :size="15" /></span><div><p>{{ memory.text }}</p><button @click="editingMemory = memory.id; memoryInput = memory.text">修改</button></div><button class="icon-button" :disabled="!!room" :aria-label="`忘记：${memory.text}`" @click="forget(memory)"><Trash2 :size="16" /></button></article>
      </div>

      <div v-else class="settings-body">
        <ConnectionSettings v-if="ready" :before-save="prepareSettingsSave" @saved="value => { capabilities = value }" />
        <h2 class="setting-title">陪伴方式</h2>
        <div class="setting-row"><div><strong>回复朗读</strong><small>{{ voiceLabel }} · 中英声音取决于语音包或服务</small></div><button class="switch" :class="{ on: readAloud }" role="switch" :aria-checked="readAloud" aria-label="回复朗读开关" @click="toggleReadAloud"><span /></button></div>
        <div class="setting-row"><div><strong>低动态模式</strong><small>减少身体动作，保留基本口型</small></div><button class="switch" :class="{ on: lowMotion }" role="switch" :aria-checked="lowMotion" aria-label="低动态模式开关" @click="toggleLowMotion"><span /></button></div>
        <div v-if="desktop" class="setting-row"><div><strong>窗口置顶</strong><small>聊天窗口保持在其他应用上方</small></div><button class="switch" :class="{ on: topmost }" role="switch" :aria-checked="topmost" aria-label="窗口置顶开关" @click="async () => { topmost = await desktop!.setAlwaysOnTop(!topmost) }"><span /></button></div>
        <h2 class="setting-title">角色形象</h2>
        <div class="model-summary"><span class="model-monogram">L2D</span><div><strong>{{ modelName }}</strong><small>{{ modelReady ? '角色已加载' : '正在准备角色' }}</small></div><button class="outline-button" @click="fileInput?.click()"><Upload :size="15" />导入文件夹</button></div>
        <input ref="fileInput" type="file" class="file-input" webkitdirectory multiple aria-label="导入 Live2D 角色文件夹" @change="selectModel">
        <p class="field-help">选择包含 .model3.json、模型和纹理的完整文件夹。仅在本次启动中使用，不上传；请使用你有权使用的素材。</p>
        <h2 class="setting-title">连接状态</h2>
        <div class="service-status"><span>聊天模型</span><strong :class="{ available: capabilities.chat === 'connected' }">{{ capabilities.chat === 'connected' ? capabilities.model : '等待填写 API Key' }}</strong></div>
        <div class="service-status"><span>语音识别 / 合成</span><strong>{{ capabilities.stt ? '识别已配置' : '识别待接入' }} · {{ voiceLabel }}</strong></div>
        <p v-if="capabilities.tts_pending" class="field-help">火山引擎音色待启用，请在上方语音设置中填写密钥并保存。当前使用系统声音。</p>
        <div class="service-status"><span>实时通话</span><strong>{{ capabilities.realtime ? '已配置，需语音进程在线' : '待接入 LiveKit 与语音服务' }}</strong></div>
        <p class="build-note">栖伴 0.3.1 · 本地陪伴<br>Windows 本地朗读与远程音频使用声音包络驱动口型；浏览器系统朗读使用基础开合动画。</p>
      </div>
    </section>
    <div v-if="toast" class="toast" role="status"><Leaf :size="17" />{{ toast }}</div>
  </div>
</template>
