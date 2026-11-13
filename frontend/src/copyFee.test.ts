import { describe, it, expect } from 'vitest'
import { findForbidden } from './copy'

describe('피 대신 값', () => {
  it('수수료 뜻의 피는 금지어다', () => {
    for (const s of ['연 고정 피 28억', '성과 피 기준', '인플루언서 피', '피 뒤 공헌']) {
      expect(findForbidden(s).length).toBeGreaterThan(0)
    }
    expect(findForbidden('연 고정 값 28억')).toEqual([])
  })

})
