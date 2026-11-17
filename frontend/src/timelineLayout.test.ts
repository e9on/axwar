import { describe, it, expect } from 'vitest'
import { bandSpan, monthRange, monthsIn, packRows, pct, placeLeft, estimateWidth } from './timelineLayout'

describe('일정 띠 위치 계산', () => {
  it('범위는_월_단위이고_해가_바뀌어도_맞다', () => {
    expect(monthRange(['2026-12-20', '2027-01-05'])).toEqual({ start: '2026-12-01', end: '2027-02-01' })
    expect(monthRange(['2026-02-10'])).toEqual({ start: '2026-02-01', end: '2026-03-01' })
    expect(monthsIn('2026-12-01', '2027-02-01').map((m) => m.label)).toEqual(['2026년 12월', '2027년 1월'])
  })

  it('월_첫날은_0이고_마지막날은_100을_넘지_않는다', () => {
    expect(pct('2026-07-01', '2026-07-01', '2026-08-01')).toBe(0)
    const last = pct('2026-07-31', '2026-07-01', '2026-08-01')
    expect(last).toBeCloseTo((30 / 31) * 100, 6)
    expect(last).toBeLessThan(100)
  })

  it('윤년_2월도_일수가_맞다', () => {
    expect(pct('2028-02-29', '2028-02-01', '2028-03-01')).toBeCloseTo((28 / 29) * 100, 6)
  })

  it('하회_띠는_끝날을_포함해_그린다', () => {
    const span = bandSpan('2026-07-20', '2026-08-10', '2026-07-01', '2026-09-01')
    expect(span.left).toBeCloseTo((19 / 62) * 100, 6)
    expect(span.width).toBeCloseTo((22 / 62) * 100, 6) // 7/20~8/10은 22일
  })

  it('끝날이_범위_마지막_날이면_띠가_100에서_끝난다', () => {
    const span = bandSpan('2026-07-20', '2026-07-31', '2026-07-01', '2026-08-01')
    expect(span.left + span.width).toBeCloseTo(100, 6)
  })

  it('표시_왼쪽_끝은_날짜_위치이고_오른쪽_끝에서만_안쪽으로_민다', () => {
    expect(placeLeft(100, 50, 1000)).toBe(100)
    expect(placeLeft(990, 50, 1000)).toBe(950)
    expect(placeLeft(-5, 50, 1000)).toBe(0)
  })

  it('줄_나누기는_간격까지_겹치면_다음_줄', () => {
    expect(packRows([{ left: 0, width: 50 }, { left: 54, width: 50 }, { left: 56, width: 50 }], 6)).toEqual([0, 1, 0])
  })

  it('폭_추정은_여백을_포함하고_상한으로_자른다', () => {
    expect(estimateWidth('가나', 12, 20, 190)).toBe(44)
    expect(estimateWidth('가'.repeat(50), 12, 20, 190)).toBe(190)
  })
})
