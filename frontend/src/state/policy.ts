import { useLoad } from './useLoad'
import type { PolicyRow } from '../replyTypes'

/** 정책 값 읽기(/api/policy). 못 읽으면 get은 undefined. */
export function usePolicy() {
  const { data, error, loading, retry } = useLoad<PolicyRow[]>('/api/policy', [])
  const rows = data ?? []
  return {
    ready: !!data,
    failed: !!error,
    loading,
    retry,
    row: (key: string) => rows.find((r) => r.key === key),
    /** 쉼표로 나열된 역할 목록 */
    roles: (key: string): string[] =>
      String(rows.find((r) => r.key === key)?.value ?? '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
    text: (key: string): string | undefined => {
      const v = rows.find((r) => r.key === key)?.value
      return v === undefined || v === null ? undefined : String(v)
    },
  }
}
