import { vi } from 'vitest'

export type Call = { method: string; path: string; body?: unknown }

/** wait가 있으면 그 약속이 풀릴 때까지 답을 미룬다(연타·진행 중 시험용) */
type Reply = { status?: number; json?: unknown; wait?: Promise<void> } | Error

/** fetch를 가짜로 바꾼다. 길(method+경로)마다 답을 정하고, 부른 기록을 남긴다. */
export function fakeServer(given: Record<string, Reply | (() => Reply)>) {
  const routes: Record<string, Reply | (() => Reply)> = { 'GET /api/cases': { json: [] }, ...given } // 일정 이름용 건 목록은 비어 있어도 되는 길
  const calls: Call[] = []
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? 'GET').toUpperCase()
    const path = String(input)
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ method, path, body })
    const entry = routes[`${method} ${path}`] ?? routes[Object.keys(routes).find((k) => k.endsWith('*') && `${method} ${path}`.startsWith(k.slice(0, -1))) ?? '']
    if (entry === undefined) return new Response(JSON.stringify({ detail: '없는 길이에요' }), { status: 404 })
    const reply = typeof entry === 'function' ? entry() : entry
    if (reply instanceof Error) throw reply
    if (reply.wait) await reply.wait
    return new Response(JSON.stringify(reply.json ?? {}), { status: reply.status ?? 200 })
  })
  vi.stubGlobal('fetch', fn)
  return { calls }
}

const ALLOWED = { allowed: true, reason: null }
/** 관리 권한 응답(GET /api/permissions?person=). 막을 항목은 이유 문장과 함께 넘긴다 */
export function permissionsReply(blocked: Partial<Record<'registry' | 'policy' | 'mode' | 'review' | 'return', string>> = {}) {
  const admin = Object.fromEntries(
    (['registry', 'policy', 'mode', 'review', 'return'] as const).map((k) => [k, blocked[k] ? { allowed: false, reason: blocked[k] } : ALLOWED]),
  )
  return { json: [{ name: '누구', role: '역할', admin }] }
}
/** 길 이름 앞부분만 맞으면 되는 권한 길(사람 이름이 붙으므로) */
export const PERMISSIONS_ROUTE = 'GET /api/permissions*'
