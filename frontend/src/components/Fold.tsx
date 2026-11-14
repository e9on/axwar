import { useId, useState, type ReactNode } from 'react'
import './Fold.css'

type Props = { title: string; summary?: string; children: ReactNode; defaultOpen?: boolean }

/** 접힌 칸: 제목 + 한 줄 요약. 누르면 펼친다(펼침 상태는 칸마다) */
export default function Fold({ title, summary, children, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()
  return (
    <section className="fold" data-open={open}>
      <h3>
        <button type="button" data-fold data-line={!summary} aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
          <span className="ft">{title}</span>
          {summary && <span className="fs">{summary}</span>}
          <span className="chev" aria-hidden="true">
            {open ? '▾' : '▸'}
          </span>
        </button>
      </h3>
      {open && (
        <div id={id} className="fbody">
          {children}
        </div>
      )}
    </section>
  )
}
