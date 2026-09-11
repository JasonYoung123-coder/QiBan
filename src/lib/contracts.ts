export type Language = 'auto' | 'zh-CN' | 'en-US'
export type AvatarState = 'idle' | 'listening' | 'thinking' | 'speaking'
export type Mood = 'neutral' | 'warm' | 'happy' | 'concerned'
export interface Profile {
  id: string
  revision: number
  name: string
  user_name: string
  persona: string
  language: Language
}
export interface Capabilities { chat: 'demo' | 'connected'; stt: boolean; tts: boolean; tts_provider?: 'windows' | 'remote' | 'browser' | 'volcengine'; tts_pending?: boolean; realtime: boolean; model: string }
export interface Message { id: string; role: 'user' | 'assistant'; text: string; generation_id: string; delivery_state: string }
export interface Memory { id: string; text: string; revision: number; created_at?: string }
export interface Bootstrap { profile: Profile; conversation_id: string; capabilities: Capabilities }
export interface StreamEvent {
  type: string
  generation_id: string
  conversation_id: string
  session_epoch: number
  sequence: number
  payload: { message_id?: string; text?: string; language?: Language; message?: string }
}

declare global {
  interface Window {
    qibanDesktop?: {
      minimize(): void
      close(): void
      setPetMode(enabled: boolean): Promise<boolean>
      setAlwaysOnTop(enabled: boolean): Promise<boolean>
      setClickThrough(enabled: boolean): void
      onPetMode(callback: (enabled: boolean) => void): () => void
    }
  }
}
