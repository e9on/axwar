import { vi } from 'vitest'

export type Call = { method: string; path: string; body?: unknown }

type Reply = { status?: number; json?: unknown } | Error

/** fetch를 가짜로 바꾼다. 길(method+경로)마다 답을 정하고, 부른 기록을 남긴다. */
export function fakeServer(routes: Record<string, Reply | (() => Reply)>) {
  const calls: Call[] = []
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? 'GET').toUpperCase()
    const path = String(input)
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ method, path, body })
    const entry = routes[`${method} ${path}`]
    if (entry === undefined) return new Response(JSON.stringify({ detail: '없는 길이에요' }), { status: 404 })
    const reply = typeof entry === 'function' ? entry() : entry
    if (reply instanceof Error) throw reply
    return new Response(JSON.stringify(reply.json ?? {}), { status: reply.status ?? 200 })
  })
  vi.stubGlobal('fetch', fn)
  return { calls }
}
