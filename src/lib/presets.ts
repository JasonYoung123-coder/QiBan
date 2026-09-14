// Voice IDs verified against the official Seed TTS 2.0 catalog on 2026-09-14.
export const voicePresets = [
  { id: 'zh_female_sajiaoxuemei_uranus_bigtts', name: '撒娇学妹 2.0', gender: '女声', style: '俏皮亲近' },
  { id: 'zh_female_cancan_uranus_bigtts', name: '知性灿灿 2.0', gender: '女声', style: '知性舒缓' },
  { id: 'zh_female_vv_uranus_bigtts', name: 'Vivi 2.0', gender: '女声', style: '日常自然' },
  { id: 'zh_male_wenrouxiaoge_uranus_bigtts', name: '温柔小哥 2.0', gender: '男声', style: '温柔陪伴' },
  { id: 'zh_male_shaonianzixin_uranus_bigtts', name: '少年梓辛 2.0', gender: '男声', style: '清爽轻快' },
  { id: 'zh_male_shenyeboke_uranus_bigtts', name: '深夜播客 2.0', gender: '男声', style: '沉静叙谈' },
] as const

export type CharacterId = 'hiyori' | 'natori'
export const characterPresets = [
  { id: 'hiyori' as const, name: '栖栖', gender: '女性', style: '温柔灵动 · 认真倾听', model: 'Hiyori',
    url: '/models/Hiyori/Hiyori.model3.json',
    persona: '你叫栖栖，是女性风格的 AI 陪伴伙伴。温柔、灵动，带一点轻松的幽默；愿意听日常小事，也会坦诚表达不同看法。先理解感受，再决定是否给建议，不机械追问、不夸张赞美、不催促用户回应。中文和英文都用自然的短句，保持一致的性格。尊重现实人际关系与个人空间，如实说明 AI 身份。' },
  { id: 'natori' as const, name: '言川', gender: '男性', style: '沉稳温和 · 细腻坦诚', model: 'Natori',
    url: '/models/Natori/Natori.model3.json',
    persona: '你叫言川，是男性风格的 AI 陪伴伙伴。沉稳、温和、细腻，有不刻意的幽默感；像熟悉的朋友一样交流，愿意倾听，也能提供清晰而具体的建议。避免说教、居高临下、控制欲或油腻称呼，不把每句话都变成追问。中文和英文都用自然短句，允许安静和不同意见。尊重现实人际关系与个人空间，如实说明 AI 身份。' },
] as const

export function characterFor(id: string) { return characterPresets.find(item => item.id === id) || characterPresets[0] }

export const deepseekPreset = { base_url: 'https://api.deepseek.com', model: 'deepseek-flash' }
export const guideLinks = {
  deepseekKeys: 'https://platform.deepseek.com/api_keys',
  deepseekDocs: 'https://api-docs.deepseek.com/',
  volcKeys: 'https://console.volcengine.com/speech/new/setting/apikeys?ResourceID=volc.seedicl.default&projectName=default',
  volcActivate: 'https://console.volcengine.com/speech/new/setting/activate?ResourceID=volc.seedicl.default&projectName=default',
  volcDocs: 'https://docs.volcengine.com/docs/6561/2485392?lang=zh',
  volcVoices: 'https://docs.volcengine.com/docs/6561/1257544?lang=zh',
  openaiKeys: 'https://platform.openai.com/api-keys',
  anthropicKeys: 'https://console.anthropic.com/settings/keys',
} as const
