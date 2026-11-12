import { describe, it, expect } from 'vitest'
import { unitValue } from './format'

describe('단위별 값 글자', () => {
  it.each([
    [0.12345, 'ratio', '12.35%'],
    [0, 'ratio', '0.00%'],
    [12.3456, 'percent', '12.35%'],
    [121676523.4, 'krw', '121,676,523원'],
    [-5000, 'krw', '-5,000원'],
    [3.7, 'multiple', '3.700'],
    [2461.7, 'multiple', '2,461.700'],
    [12, 'count', '12'],
    [30, 'days', '30일'],
    [4.5, undefined, '4.5'],
    [4.5, null, '4.5'],
    [4.5, '새단위', '4.5'],
  ])('%s %s → %s', (v, unit, text) => {
    expect(unitValue(v as number, unit as string | null | undefined)).toBe(text)
  })
})
