<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, ChevronDown, History, LoaderCircle } from 'lucide-vue-next'
import type { ConversationSummary } from '../lib/contracts'

const props = defineProps<{
  conversations: ConversationSummary[]
  active: string
  loading: boolean
  disabled: boolean
  error: string
}>()
const emit = defineEmits<{ refresh: []; select: [id: string] }>()
const expanded = ref(false)
const currentTitle = computed(() => props.conversations.find(item => item.id === props.active)?.title || '新的相伴')
function toggle(): void {
  expanded.value = !expanded.value
  if (expanded.value) emit('refresh')
}
function dateLabel(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const today = date.toDateString() === new Date().toDateString()
  return today ? `今天 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
    : date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric' })
}
</script>

<template>
  <section class="conversation-history" aria-label="历史聊天">
    <button class="history-toggle" aria-controls="conversation-list" :aria-expanded="expanded" @click="toggle">
      <History :size="15" /><span>历史聊天</span>
      <span class="history-current" :title="currentTitle">{{ currentTitle }}</span>
      <ChevronDown :size="14" :class="{ expanded }" />
    </button>
    <div v-if="expanded" id="conversation-list" class="history-drawer" :aria-busy="loading">
      <div class="history-heading"><span>最近聊过 · {{ conversations.length }} 段</span><span v-if="loading" role="status"><LoaderCircle :size="12" class="spin" />正在更新</span><span v-else>点击继续聊天</span></div>
      <div v-if="error" class="history-error" role="alert">{{ error }}<button :disabled="loading" @click="emit('refresh')">重试</button></div>
      <ul v-if="conversations.length" class="history-list">
        <li v-for="item in conversations" :key="item.id">
          <button class="history-item" :data-conversation-id="item.id" :class="{ active: item.id === active }" :aria-current="item.id === active ? 'true' : undefined" :disabled="disabled" @click="emit('select', item.id)">
            <span class="history-item-top"><strong :title="item.title">{{ item.title }}</strong><Check v-if="item.id === active" :size="13" /><time :datetime="item.updated_at">{{ dateLabel(item.updated_at) }}</time></span>
            <span class="history-preview">{{ item.preview || '还没开始聊天，随时可以回来。' }}</span>
          </button>
        </li>
      </ul>
      <p v-else-if="!loading && !error" class="history-empty">聊天记录会自动保存在这里。</p>
    </div>
  </section>
</template>
