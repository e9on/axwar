/** 지금 화면에 보이는 글만(접힌 칸·hidden 안의 글은 뺀다) */
export function visibleText(root: HTMLElement): string {
  const copy = root.cloneNode(true) as HTMLElement
  copy.querySelectorAll('[hidden], script, style').forEach((n) => n.remove())
  copy.querySelectorAll('details:not([open])').forEach((d) => Array.from(d.children).forEach((c) => c.tagName !== 'SUMMARY' && c.remove()))
  return copy.textContent ?? ''
}
