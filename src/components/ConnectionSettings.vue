<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Check, LoaderCircle, Plug, RefreshCw } from 'lucide-vue-next'
import { api } from '../lib/api'
import type { Capabilities } from '../lib/contracts'
import { deepseekPreset, guideLinks, voicePresets } from '../lib/presets'

type Provider = 'openai' | 'responses' | 'anthropic'
type Chat = { base_url: string; model: string; api_key?: string; api_key_set?: boolean; require_api_key: boolean; max_tokens: number; clear_key?: boolean }
type Voice = Record<string, string | boolean | null>
type Settings = { revision: number; chat_provider: Provider; chats: Record<Provider, Chat>; voice: Voice }
type Result = { settings: Settings; capabilities: Capabilities }
const props = defineProps<{ beforeSave: () => Promise<unknown> }>()
const emit = defineEmits<{ saved: [capabilities: Capabilities] }>()
const settings = ref<Settings>()
const busy = ref(false)
const testing = ref(false)
const message = ref('')
const failure = ref('')
const current = computed(() => settings.value?.chats[settings.value.chat_provider])
const customVoice = ref(false)
const selectedVoice = computed(() => voicePresets.find(item => item.id === settings.value?.voice.volcengine_tts_speaker))
function chooseVoice(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  customVoice.value = value === 'custom'
  if (!customVoice.value && settings.value) {
    settings.value.voice.volcengine_tts_speaker = value
    settings.value.voice.volcengine_tts_resource_id = 'seed-tts-2.0'
  }
}
function useDeepSeek(): void {
  if (!settings.value) return
  const chat = settings.value.chats.openai
  // Existing keys must not silently travel to a new endpoint.
  if (chat.base_url !== deepseekPreset.base_url) { chat.api_key = ''; chat.clear_key = true }
  settings.value.chat_provider = 'openai'
  Object.assign(chat, deepseekPreset)
  message.value = '已填入 DeepSeek 地址与模型，请填写对应密钥并保存。'
}
async function openGuide(event: MouseEvent, url: string): Promise<void> {
  if (!window.qibanDesktop) return
  event.preventDefault()
  try { if (!await window.qibanDesktop.openGuide(url)) throw new Error('无法打开指引链接，请复制链接到浏览器。') }
  catch (cause) { failure.value = cause instanceof Error ? cause.message : '打开链接失败。' }
}
const defaults: Record<Provider, string> = {openai: 'https://api.openai.com/v1', responses: 'https://api.openai.com/v1', anthropic: 'https://api.anthropic.com/v1'}
const voiceKeys = ['volcengine_tts_api_key', 'tts_api_key', 'stt_api_key', 'livekit_api_key', 'livekit_api_secret', 'worker_secret']

function accept(result: Result): void {
  for (const chat of Object.values(result.settings.chats)) { chat.api_key = ''; chat.clear_key = false }
  for (const key of voiceKeys) { result.settings.voice[key] = ''; result.settings.voice[`${key}_clear`] = false }
  settings.value = result.settings
  customVoice.value = !voicePresets.some(item => item.id === result.settings.voice.volcengine_tts_speaker)
  emit('saved', result.capabilities)
}
async function load(): Promise<void> {
  failure.value = ''
  try { accept(await api<Result>('/settings')) }
  catch (cause) { failure.value = cause instanceof Error ? cause.message : '设置加载失败。' }
}
function payload(): unknown {
  const data = structuredClone(JSON.parse(JSON.stringify(settings.value))) as Settings
  for (const chat of Object.values(data.chats)) {
    const key = chat.clear_key ? '' : chat.api_key?.trim() || null
    delete chat.api_key_set; delete chat.clear_key
    Object.assign(chat, { api_key: key })
  }
  for (const key of voiceKeys) {
    data.voice[key] = data.voice[`${key}_clear`] ? '' : String(data.voice[key] || '').trim() || null
    delete data.voice[`${key}_clear`]; delete data.voice[`${key}_set`]
  }
  return data
}
async function save(): Promise<void> {
  busy.value = true; failure.value = ''; message.value = ''
  try {
    await props.beforeSave()
    accept(await api<Result>('/settings', { method: 'PUT', body: JSON.stringify(payload()) }))
    message.value = '设置已保存，下一次聊天和朗读立即生效。'
  } catch (cause) { failure.value = cause instanceof Error ? cause.message : '保存未完成。' }
  finally { busy.value = false }
}
async function test(): Promise<void> {
  testing.value = true; failure.value = ''; message.value = ''
  try {
    const result = await api<{message:string}>('/settings/test', {method:'POST',body:JSON.stringify(payload())})
    message.value = `${result.message} 尚未保存的修改，请点击保存。`
  } catch (cause) { failure.value = cause instanceof Error ? cause.message : '连接测试失败。' }
  finally { testing.value = false }
}
onMounted(load)
</script>

<template>
  <section class="connection-settings" aria-label="模型与语音连接设置">
    <div class="connections-heading"><h2 class="setting-title">聊天模型</h2><button class="icon-button" title="重新载入设置" aria-label="重新载入连接设置" :disabled="busy || testing" @click="load"><RefreshCw :size="15" /></button></div>
    <p class="field-help">选择接口，填写模型和密钥。每种接口的配置分别保留。</p>
    <form v-if="settings && current" @submit.prevent="save">
      <fieldset :disabled="busy || testing" class="connection-fields">
        <details class="setup-guide" :open="!current.api_key_set">
          <summary>第一次使用？查看模型与密钥获取指引</summary>
          <p>日常聊天推荐 DeepSeek。地址和模型可一键填入，你只需要准备自己的 API Key。</p>
          <ol><li>打开 <a :href="guideLinks.deepseekKeys" target="_blank" rel="noopener noreferrer" @click="openGuide($event, guideLinks.deepseekKeys)">DeepSeek 密钥管理 ↗</a>，登录并创建 API Key。</li><li>按平台提示开通 API 用量，复制密钥并粘贴到下方。API 服务的额度与网页聊天账号权益分开。</li><li>点击「测试聊天连接」，成功后保存。</li></ol>
          <button type="button" class="outline-button" aria-label="填入 DeepSeek 推荐配置" @click="useDeepSeek">填入 DeepSeek 推荐配置</button>
          <p class="guide-value">地址 {{ deepseekPreset.base_url }}<br>模型 {{ deepseekPreset.model }}</p>
          <a :href="guideLinks.deepseekDocs" target="_blank" rel="noopener noreferrer" @click="openGuide($event, guideLinks.deepseekDocs)">DeepSeek 官方接入说明 ↗</a>
          <details class="other-providers"><summary>我使用 OpenAI、Anthropic 或其他服务</summary><p><a :href="guideLinks.openaiKeys" target="_blank" rel="noopener noreferrer" @click="openGuide($event, guideLinks.openaiKeys)">OpenAI 密钥管理 ↗</a> · <a :href="guideLinks.anthropicKeys" target="_blank" rel="noopener noreferrer" @click="openGuide($event, guideLinks.anthropicKeys)">Anthropic 密钥管理 ↗</a></p><p>选择对应接口后点击「填入官方地址」。使用代理或兼容服务时，URL、模型名称和密钥都由该服务提供方获取，不要混用不同平台的密钥。</p></details>
        </details>
        <label>接口类型<select v-model="settings.chat_provider" aria-label="聊天接口类型"><option value="openai">OpenAI / 兼容接口</option><option value="responses">OpenAI Responses</option><option value="anthropic">Anthropic Messages</option></select></label>
        <label>服务地址<input v-model="current.base_url" aria-label="聊天服务地址" type="url" :placeholder="defaults[settings.chat_provider]" maxlength="2048" autocomplete="off"></label>
        <button class="text-button official-address" type="button" @click="current.base_url = defaults[settings.chat_provider]">填入官方地址</button>
        <label>模型名称<input v-model="current.model" aria-label="聊天模型名称" placeholder="填写服务提供的模型名称" maxlength="200" autocomplete="off"></label>
        <label>API Key <span class="key-status">{{ current.api_key_set ? '已保存 · 留空保留' : '尚未设置' }}</span><input v-model="current.api_key" @input="current.clear_key = false" aria-label="聊天 API Key" type="password" :placeholder="current.api_key_set ? '输入新密钥以替换' : '粘贴 API Key'" autocomplete="new-password" spellcheck="false" maxlength="4096"></label>
        <label v-if="current.api_key_set" class="inline-option"><input v-model="current.clear_key" type="checkbox" aria-label="清除当前接口密钥">清除已保存的密钥</label>
        <details class="connection-advanced"><summary>聊天高级选项</summary><label>回复 Token 上限<input v-model.number="current.max_tokens" type="number" min="0" max="128000" step="1"></label><p class="field-help">0：OpenAI 使用服务默认值；Anthropic 使用 4096。</p><label class="inline-option"><input v-model="current.require_api_key" type="checkbox">该服务需要 API Key</label></details>
        <div class="connection-divider" />
        <h2 class="setting-title">语音合成</h2>
        <details class="setup-guide"><summary>推荐豆包语音 · 如何获取语音密钥？</summary>
          <ol><li>登录火山引擎，打开 <a :href="guideLinks.volcActivate" target="_blank" rel="noopener noreferrer" @click="openGuide($event, guideLinks.volcActivate)">豆包语音服务开通页面 ↗</a>，在所选项目下开通「豆包语音合成模型 2.0」。</li><li>在同一项目的 <a :href="guideLinks.volcKeys" target="_blank" rel="noopener noreferrer" @click="openGuide($event, guideLinks.volcKeys)">API Key 管理 ↗</a> 创建密钥，粘贴到下方「火山引擎 API Key」。此处填写语音 API Key，无需填写旧版 App ID 或 Access Token。</li><li>选择喜欢的声音并保存，然后开启「回复朗读」。</li></ol>
          <p>接口地址和资源 ID 已预填，通常无需修改：<br><span class="guide-value">https://openspeech.bytedance.com/api/v3/tts/unidirectional<br>seed-tts-2.0</span></p>
          <a :href="guideLinks.volcDocs" target="_blank" rel="noopener noreferrer" @click="openGuide($event, guideLinks.volcDocs)">查看官方控制台指引 ↗</a>
        </details>
        <label>朗读声音<select v-model="settings.voice.tts_provider" aria-label="语音提供方"><option value="system">系统本地朗读</option><option value="volcengine">火山引擎 · 指定音色</option><option value="openai">OpenAI / 兼容语音服务</option></select></label>
        <template v-if="settings.voice.tts_provider === 'volcengine'">
          <label>火山引擎 API Key <span class="key-status">{{ settings.voice.volcengine_tts_api_key_set ? '已保存 · 留空保留' : '尚未设置' }}</span><input v-model="settings.voice.volcengine_tts_api_key" type="password" aria-label="火山引擎 API Key" autocomplete="new-password" maxlength="4096" placeholder="填写 X-Api-Key"></label>
          <label v-if="settings.voice.volcengine_tts_api_key_set" class="inline-option"><input v-model="settings.voice.volcengine_tts_api_key_clear" type="checkbox">清除火山引擎密钥</label>
          <label>选择配音风格<select :value="customVoice ? 'custom' : settings.voice.volcengine_tts_speaker" aria-label="配音风格" @change="chooseVoice"><optgroup v-for="gender in ['女声','男声']" :key="gender" :label="gender"><option v-for="voice in voicePresets.filter(item => item.gender === gender)" :key="voice.id" :value="voice.id">{{ voice.name }} · {{ voice.style }}</option></optgroup><option value="custom">自定义音色 ID</option></select></label>
          <p class="field-help">{{ selectedVoice && !customVoice ? `${selectedVoice.name} · 中文及英文能力，以服务实际效果为准。` : '填写你在火山引擎音色库获取的 Speaker ID。' }} <a :href="guideLinks.volcVoices" target="_blank" rel="noopener noreferrer" @click="openGuide($event, guideLinks.volcVoices)">官方音色库 ↗</a></p>
          <label v-if="customVoice">音色 ID<input v-model="settings.voice.volcengine_tts_speaker" aria-label="火山引擎音色 ID" maxlength="200"></label>
          <details class="connection-advanced"><summary>火山引擎高级选项</summary><label>接口地址<input v-model="settings.voice.volcengine_tts_url" type="url" maxlength="2048"></label><label>资源 ID<input v-model="settings.voice.volcengine_tts_resource_id" maxlength="200"></label></details>
        </template>
        <template v-else-if="settings.voice.tts_provider === 'openai'">
          <label>语音服务地址<input v-model="settings.voice.tts_base_url" type="url" placeholder="https://服务地址/v1" maxlength="2048"></label><label>语音模型<input v-model="settings.voice.tts_model" maxlength="200"></label><label>音色名称<input v-model="settings.voice.tts_voice" maxlength="200"></label><label>语音 API Key <span class="key-status">{{ settings.voice.tts_api_key_set ? '已保存 · 留空保留' : '尚未设置' }}</span><input v-model="settings.voice.tts_api_key" type="password" autocomplete="new-password" maxlength="4096"></label><label v-if="settings.voice.tts_api_key_set" class="inline-option"><input v-model="settings.voice.tts_api_key_clear" type="checkbox">清除语音服务密钥</label>
        </template>
        <p v-else class="field-help">使用电脑已安装的声音，中英支持取决于系统语音包。</p>
        <details class="connection-advanced"><summary>语音识别与实时通话</summary>
          <label>识别服务地址<input v-model="settings.voice.stt_base_url" type="url" maxlength="2048" placeholder="https://服务地址/v1"></label><label>识别模型<input v-model="settings.voice.stt_model" maxlength="200"></label>
          <label>识别 API Key <span class="key-status">{{ settings.voice.stt_api_key_set ? '已保存 · 留空保留' : '尚未设置' }}</span><input v-model="settings.voice.stt_api_key" type="password" autocomplete="new-password" maxlength="4096"></label><label v-if="settings.voice.stt_api_key_set" class="inline-option"><input v-model="settings.voice.stt_api_key_clear" type="checkbox">清除识别密钥</label>
          <label>LiveKit 地址<input v-model="settings.voice.livekit_url" placeholder="wss://房间服务" maxlength="2048"></label>
          <template v-for="field in [{key:'livekit_api_key',label:'LiveKit API Key'},{key:'livekit_api_secret',label:'LiveKit API Secret'},{key:'worker_secret',label:'语音进程共享密钥'}]" :key="field.key"><label>{{ field.label }} <span class="key-status">{{ settings.voice[`${field.key}_set`] ? '已保存 · 留空保留' : '尚未设置' }}</span><input v-model="settings.voice[field.key]" type="password" autocomplete="new-password" maxlength="4096"></label><label v-if="settings.voice[`${field.key}_set`]" class="inline-option"><input v-model="settings.voice[`${field.key}_clear`]" type="checkbox">清除{{ field.label }}</label></template>
          <p class="field-help">实时通话还需要已运行的房间服务与语音进程。修改配置后请重启语音进程。</p>
        </details>
      </fieldset>
      <p v-if="failure" class="connection-error" role="alert">{{ failure }}</p><p v-if="message" class="connection-success" role="status">{{ message }}</p>
      <div class="connection-actions"><button class="primary-button" :disabled="busy || testing"><LoaderCircle v-if="busy" :size="16" class="spin"/><Check v-else :size="16"/>{{ busy ? '保存中…' : '保存连接设置' }}</button><button type="button" class="outline-button" :disabled="busy || testing" @click="test"><LoaderCircle v-if="testing" :size="15" class="spin"/><Plug v-else :size="15"/>{{ testing ? '测试中…' : '测试聊天连接' }}</button></div>
      <p class="field-help">连接测试会向所填服务发送一条短测试消息，不发送聊天记录。密钥仅保存在本机应用文件夹，设置页不会回显已存密钥；复制已配置的文件夹会携带这些密钥。</p>
    </form>
    <div v-else><p v-if="failure" class="connection-error">{{ failure }}</p><button class="text-button" @click="load">{{ failure ? '重新加载设置' : '正在加载连接设置…' }}</button></div>
  </section>
</template>

<style scoped>
.connections-heading { display:flex; align-items:center; justify-content:space-between; }
.connections-heading .setting-title { margin:0; }
.connection-fields { border:0; padding:0; margin:18px 0 0; min-width:0; }
.key-status { font-size:10px; font-weight:400; color:#74897c; margin-left:5px; }
.inline-option { display:flex; flex-direction:row; align-items:center; gap:8px; font-size:11px; margin:10px 0 17px; }
.inline-option input { width:14px; height:14px; padding:0; margin:0; accent-color:#477562; }
.official-address { margin-top:-9px; margin-bottom:16px; }
.connection-advanced { margin:18px 0; padding:13px 15px; background:#f4f8f5; border-radius:10px; }
.connection-advanced summary { font-size:12px; cursor:pointer; color:#567463; }
.connection-advanced[open] summary { margin-bottom:16px; }
.connection-divider { border-top:1px solid #e1ebe3; margin:25px 0; }
.connection-actions { display:flex; gap:10px; flex-wrap:wrap; margin:20px 0 12px; }
.connection-error,.connection-success { font-size:12px; line-height:1.7; padding:10px 13px; border-radius:8px; }
.connection-error { color:#954741; background:#fff1ef; }
.connection-success { color:#426c58; background:#edf6ef; }
.setup-guide { margin:0 0 20px; padding:15px 17px; background:#edf5ef; border:1px solid #d5e5da; border-radius:12px; font-size:12px; line-height:1.8; }
.setup-guide summary { cursor:pointer; color:#416b57; font-weight:600; }
.setup-guide p { margin:12px 0; }
.setup-guide ol { padding-left:20px; }
.setup-guide li { margin:8px 0; }
.setup-guide a,.field-help a { color:#376b55; text-decoration:underline; text-underline-offset:3px; }
.guide-value { overflow-wrap:anywhere; font-size:11px; color:#6b8074; }
.other-providers { margin-top:15px; border-top:1px solid #d5e5da; padding-top:12px; }
</style>
