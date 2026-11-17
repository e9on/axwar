import { describe, it, expect } from 'vitest'
import { modelLabel, noArrow } from './copy'

describe('보이는 말 다듬기', () => {
  it('시연용_해석기_이름은_쉬운_말로', () => {
    expect(modelLabel('fake')).toBe('시연용 해석')
    expect(modelLabel('fake(대본)')).toBe('시연용 해석')
    expect(modelLabel('claude-haiku-5-5')).toBe('claude-haiku-5-5')
  })

  it('화살표는_에서_로로_바꾼다', () => {
    expect(noArrow('2차 6,000→4,700개, 금액 773,982→606,285원')).toBe('2차 6,000개에서 4,700개로, 금액 773,982원에서 606,285원으로')
    expect(noArrow('마케팅팀→Masil 대표')).toBe('마케팅팀에서 Masil 대표로')
    expect(noArrow('화살표 없음')).toBe('화살표 없음')
  })
})
