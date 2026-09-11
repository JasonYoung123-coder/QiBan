import type { StreamEvent } from './contracts'

/** Local ownership survives async callbacks; old requests cannot animate or overwrite a newer turn. */
export class TurnGate {
  private revision = 0
  private conversation = ''
  private generation = ''
  private sequence = 0

  begin(conversation: string): number {
    this.revision += 1
    this.conversation = conversation
    this.generation = ''
    this.sequence = 0
    return this.revision
  }

  invalidate(): void { this.revision += 1; this.generation = ''; this.sequence = 0 }
  current(ticket: number): boolean { return ticket === this.revision }

  accept(ticket: number, event: StreamEvent): boolean {
    if (!this.current(ticket) || event.conversation_id !== this.conversation) return false
    if (event.type === 'assistant.started' && !this.generation) this.generation = event.generation_id
    if (!this.generation || event.generation_id !== this.generation || event.sequence <= this.sequence) return false
    this.sequence = event.sequence
    return true
  }
}
