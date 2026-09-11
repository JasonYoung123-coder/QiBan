import { describe, expect, it } from 'vitest'
import { TurnGate } from './turn-gate'
import type { StreamEvent } from './contracts'

function event(type: string, generation = 'g1', sequence = 1, conversation = 'c1'): StreamEvent {
  return { type, generation_id: generation, sequence, conversation_id: conversation, session_epoch: 1, payload: {} }
}

describe('turn ownership', () => {
  it('rejects old generation events after interruption and a new request', () => {
    const gate = new TurnGate()
    const first = gate.begin('c1')
    expect(gate.accept(first, event('assistant.started'))).toBe(true)
    gate.invalidate()
    const second = gate.begin('c1')
    expect(gate.accept(first, event('assistant.delta', 'g1', 500))).toBe(false)
    expect(gate.accept(second, event('assistant.started', 'g2'))).toBe(true)
    expect(gate.accept(second, event('assistant.delta', 'g1', 900))).toBe(false)
    expect(gate.accept(second, event('assistant.delta', 'g2', 2))).toBe(true)
  })
  it('rejects out-of-order, duplicate and wrong-conversation events', () => {
    const gate = new TurnGate()
    const ticket = gate.begin('c1')
    expect(gate.accept(ticket, event('assistant.delta'))).toBe(false)
    expect(gate.accept(ticket, event('assistant.started', 'g1', 1, 'c2'))).toBe(false)
    expect(gate.accept(ticket, event('assistant.started'))).toBe(true)
    expect(gate.accept(ticket, event('assistant.delta', 'g1', 3))).toBe(true)
    expect(gate.accept(ticket, event('assistant.delta', 'g1', 2))).toBe(false)
    expect(gate.accept(ticket, event('assistant.delta', 'g1', 3))).toBe(false)
  })
})
