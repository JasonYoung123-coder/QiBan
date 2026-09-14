import { createRequire } from 'node:module'
import { describe, expect, it } from 'vitest'
import { characterFor, characterPresets, guideLinks, voicePresets } from './presets'

const require = createRequire(import.meta.url)
const { allowedGuide } = require('../../desktop/guide-links.cjs')

describe('curated setup choices', () => {
  it('has three distinct voices per gender, all using the current TTS 2.0 family', () => {
    expect(voicePresets.filter(v => v.gender === '女声')).toHaveLength(3)
    expect(voicePresets.filter(v => v.gender === '男声')).toHaveLength(3)
    expect(new Set(voicePresets.map(v=>v.id)).size).toBe(6)
    expect(voicePresets.every(v=>v.id.endsWith('_uranus_bigtts'))).toBe(true)
  })
  it('maps both personas to local animated models and falls back safely', () => {
    expect(characterPresets.map(v=>v.gender)).toEqual(['女性','男性'])
    expect(characterFor('natori').url).toBe('/models/Natori/Natori.model3.json')
    expect(characterFor('missing').id).toBe('hiyori')
  })
  it('only opens the exact setup guide URLs, never arbitrary or credential-bearing links', () => {
    for (const url of Object.values(guideLinks)) expect(allowedGuide(url)).toBe(true)
    for (const url of ['file:///C:/secret','javascript:alert(1)','https://evil.example',
      'https://platform.deepseek.com/api_keys?key=secret',null,{}]) expect(allowedGuide(url)).toBe(false)
  })
})
