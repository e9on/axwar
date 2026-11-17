import { describe, it, expect } from 'vitest'
import { josa, unitValue } from './format'

describe('단위별 값 글자', () => {
  it.each([
    [0.12345, 'ratio', '12.35%'],
    [0, 'ratio', '0.00%'],
    [12.3456, 'percent', '12.35%'],
    [121676523.4, 'krw', '121,676,523원'],
    [-5000, 'krw', '-5,000원'],
    [3.7, 'multiple', '3.700'],
    [2461.7, 'multiple', '2,461.700'],
    [2461.7, 'score', '2,462'],
    [3, 'score', '3'],
    [0.1234, 'diff', '+0.123'],
    [-0.5, 'diff', '-0.500'],
    [0, 'diff', '0.000'],
    [12, 'count', '12'],
    [30, 'days', '30일'],
    [4.5, undefined, '4.5'],
    [4.5, null, '4.5'],
    [4.5, '새단위', '4.5'],
  ])('%s %s → %s', (v, unit, text) => {
    expect(unitValue(v as number, unit as string | null | undefined)).toBe(text)
  })
})

describe('조사 고르기', () => {
  it.each([
    ['2차 취소', '로', '2차 취소로'],
    ['예외 승인', '로', '예외 승인으로'],
    ['그룹', '로', '그룹으로'],
    ['마케팅팀', '로', '마케팅팀으로'],
    ['Masil 대표', '로', 'Masil 대표로'],
    ['2차 계속', '로', '2차 계속으로'],
    ['서울', '로', '서울로'],
  ])('%s + %s', (word, kind, out) => {
    expect(josa(word, kind as '로')).toBe(out)
  })
  it('을_를', () => {
    expect(josa('장면 1. 정상', '을')).toBe('장면 1. 정상을')
    expect(josa('장면 2. 분할', '을')).toBe('장면 2. 분할을')
    expect(josa('시나리오', '을')).toBe('시나리오를')
  })
  it('은_는', () => {
    expect(josa('승인', '은')).toBe('승인은')
    expect(josa('거절', '은')).toBe('거절은')
    expect(josa('분할', '은')).toBe('분할은')
    expect(josa('마케팅', '은')).toBe('마케팅은')
    expect(josa('위로 올리기', '은')).toBe('위로 올리기는')
  })
})
