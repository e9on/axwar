import { useEffect, useState } from 'react'

/** 휴대폰 폭 경계(시안 B의 760px). CSS 미디어 쿼리와 같은 값이어야 한다. */
export const NARROW_QUERY = '(max-width: 760px)'

/** 좁은 화면인지. matchMedia가 없는 환경(시험 등)에서는 넓은 화면으로 본다. */
export function useNarrow(): boolean {
  const read = () => (typeof window.matchMedia === 'function' ? window.matchMedia(NARROW_QUERY).matches : false)
  const [narrow, setNarrow] = useState(read)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia(NARROW_QUERY)
    const on = () => setNarrow(mq.matches)
    mq.addEventListener('change', on)
    on()
    return () => mq.removeEventListener('change', on)
  }, [])
  return narrow
}
