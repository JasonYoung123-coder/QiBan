export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    credentials: 'same-origin',
    headers: { ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: unknown }
    throw new Error(typeof payload.detail === 'string' ? payload.detail : `请求未完成（${response.status}）`)
  }
  return response.json() as Promise<T>
}

/** Consumes UTF-8 SSE across arbitrary network boundaries, including CRLF and split code points. */
export async function consumeEvents(response: Response, onEvent: (event: unknown) => void): Promise<void> {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: unknown }
    throw new Error(typeof payload.detail === 'string' ? payload.detail : `聊天请求失败（${response.status}）`)
  }
  if (!response.body) throw new Error('服务没有返回回复流。')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const dispatch = (block: string) => {
    const data = block.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
    if (data && data !== '[DONE]') onEvent(JSON.parse(data))
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      let match: RegExpMatchArray | null
      while ((match = buffer.match(/\r?\n\r?\n/))) {
        const index = match.index ?? 0
        dispatch(buffer.slice(0, index))
        buffer = buffer.slice(index + match[0].length)
      }
      if (done) break
    }
    if (buffer.trim()) dispatch(buffer)
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
