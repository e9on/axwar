import { useState } from 'react'

/** 긴 목록은 처음 이만큼만 보이고 "더 보기"를 누를 때마다 이만큼씩 늘린다(화면 전체가 한 값을 쓴다). */
export const PREVIEW_ROWS = 20

/** items 중 보일 만큼과 더 보기. 목록이 바뀌어도 이미 늘린 만큼은 유지하고, reset으로 처음 개수로 되돌린다. */
export function usePreview<T>(items: T[]) {
  const [shown, setShown] = useState(PREVIEW_ROWS)
  return {
    visible: items.slice(0, shown),
    hasMore: items.length > shown,
    more: () => setShown((n) => n + PREVIEW_ROWS),
    reset: () => setShown(PREVIEW_ROWS),
  }
}
