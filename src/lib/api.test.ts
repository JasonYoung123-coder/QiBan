import { expect, it } from 'vitest'
import { consumeEvents } from './api'

it('decodes split UTF-8 and CRLF frames without losing Chinese text', async () => {
  const bytes = new TextEncoder().encode('data: {"text":"你好"}\r\n\r\ndata: {"text":"English"}\n\n')
  const stream = new ReadableStream({ start(controller) {
    for (let i = 0; i < bytes.length; i += 2) controller.enqueue(bytes.slice(i, i + 2))
    controller.close()
  } })
  const result: unknown[] = []
  await consumeEvents(new Response(stream), value => result.push(value))
  expect(result).toEqual([{ text: '你好' }, { text: 'English' }])
})

it('surfaces failed requests instead of treating an error as an empty success', async () => {
  const response = new Response(JSON.stringify({ detail: '服务未配置' }), { status: 503 })
  await expect(consumeEvents(response, () => {})).rejects.toThrow('服务未配置')
})
