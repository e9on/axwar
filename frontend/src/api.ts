/** 서버와 말하는 얇은 층. 실패하면 한국어 문장이 든 ApiError를 던지고, 듣는 쪽(알림 줄)에도 알린다. */

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const NETWORK_FAILURE = '서버에 연결하지 못했어요'
const UNKNOWN_FAILURE = '요청을 처리하지 못했어요'

type Listener = (error: ApiError) => void
const listeners = new Set<Listener>()

/** 모든 API 실패를 받는다(전역 알림 줄이 쓴다). 해제 함수를 돌려준다. */
export function onApiError(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function fail(error: ApiError): ApiError {
  listeners.forEach((listener) => listener(error))
  return error
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw fail(new ApiError(0, NETWORK_FAILURE))
  }
  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }
  if (!response.ok) {
    const detail = (payload as { detail?: unknown } | null)?.detail
    throw fail(new ApiError(response.status, typeof detail === 'string' && detail ? detail : UNKNOWN_FAILURE))
  }
  return payload as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
}
