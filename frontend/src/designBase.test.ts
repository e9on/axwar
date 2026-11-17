import { describe, it, expect } from 'vitest'
import base from './design/base.css?raw'
import tokens from './design/tokens.css?raw'

describe('어두운 화면에서도 입력 글자가 보인다', () => {
  it('여러_줄_입력칸도_글자색과_글꼴을_물려받는다', () => {
    const rule = base.match(/([^{}]+)\{\s*font:\s*inherit;\s*color:\s*inherit;/)
    expect(rule?.[1]).toMatch(/textarea/)
  })

  it('어두운_화면에서는_브라우저_기본_부품도_어두운_색을_쓴다', () => {
    expect(tokens).toMatch(/:root:not\(\[data-theme="light"\]\)\s*\{[^}]*color-scheme:\s*dark/)
    expect(tokens).toMatch(/:root\[data-theme="dark"\]\s*\{[^}]*color-scheme:\s*dark/)
  })
})
