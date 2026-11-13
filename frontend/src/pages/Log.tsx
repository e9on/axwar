import { fromTo } from '../copy'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useViewer } from '../state/viewer'
import { useClock } from '../state/clock'
import { usePreview } from '../state/preview'
import { useLoad } from '../state/useLoad'
import { anyValue, pct, num, usd } from '../format'
import { ASSUMPTION_PREFIX } from '../decisions'
import type { AiUsage, EventRow, PolicyItem } from '../adminTypes'
import Badge from '../components/Badge'
import LoadFailed from '../components/LoadFailed'
import './Admin.css'

const TABS = ['처리 기록', 'AI 호출 내역', '가정 목록'] as const
type Tab = (typeof TABS)[number]

function useCasePath() {
  const { person } = useViewer()
  const as = person ? `?as=${encodeURIComponent(person.name)}` : ''
  return (id: number) => `/cases/${id}${as}`
}

function timeText(ts: string): string {
  return ts.slice(0, 16).replace('T', ' ')
}

/** 이벤트 상세를 "이전에서 이후로"와 나머지 항목으로 */
function detailParts(detail: Record<string, unknown>): { change: string | null; rest: string } {
  const pair = 'from' in detail && 'to' in detail ? ['from', 'to'] : 'before' in detail && 'after' in detail ? ['before', 'after'] : null
  const change = pair ? fromTo(anyValue(detail[pair[0]]), anyValue(detail[pair[1]])) : null
  const rest = Object.entries(detail)
    .filter(([k]) => !pair?.includes(k))
    .map(([k, v]) => (k === 'note' ? String(v) : `${k}: ${anyValue(v)}`))
    .join(' · ')
  return { change, rest }
}

function Events() {
  const { version } = useClock()
  const casePath = useCasePath()
  const load = useLoad<EventRow[]>('/api/events', [version])
  const [kind, setKind] = useState('')
  const [caseId, setCaseId] = useState('')

  const rows = load.data ?? []
  const kinds = useMemo(() => Array.from(new Set(rows.map((r) => r.kind))), [rows])
  const cases = useMemo(() => Array.from(new Set(rows.map((r) => r.case_id).filter((c): c is number => c !== null))).sort((a, b) => a - b), [rows])
  const filtered = rows.filter((r) => (!kind || r.kind === kind) && (!caseId || String(r.case_id) === caseId)).reverse() // 최신이 위
  const preview = usePreview(filtered)

  if (load.error) return <LoadFailed retry={load.retry} message={`처리 기록을 불러오지 못했어요. ${load.error}`} />
  if (!load.data)
    return (
      <p role="status" className="muted">
        불러오는 중…
      </p>
    )
  return (
    <section aria-label="처리 기록 영역">
      <div className="bar-tools">
        <label>
          종류로 거르기
          <select value={kind} onChange={(e) => (setKind(e.target.value), preview.reset())}>
            <option value="">모든 종류</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <label>
          건으로 거르기
          <select value={caseId} onChange={(e) => (setCaseId(e.target.value), preview.reset())}>
            <option value="">모든 건</option>
            {cases.map((c) => (
              <option key={c} value={String(c)}>
                건 #{c}
              </option>
            ))}
          </select>
        </label>
        <span className="muted">{num(filtered.length)}건</span>
      </div>
      {filtered.length === 0 ? (
        <p className="muted">{rows.length === 0 ? '아직 처리 기록이 없어요' : '조건에 맞는 기록이 없어요'}</p>
      ) : (
        <>
          <ul className="ledger events" aria-label="처리 기록">
            {preview.visible.map((r) => {
              const { change, rest } = detailParts(r.detail)
              return (
                <li key={r.id}>
                  <span className="sub">
                    {timeText(r.ts)}
                    <br />
                    기준일 {r.sim_date}
                  </span>
                  <span>{r.actor}</span>
                  <div>
                    <span className="k">{r.kind}</span>
                    {r.case_id !== null && (
                      <>
                        {' '}
                        <Link to={casePath(r.case_id)}>건 #{r.case_id}</Link>
                      </>
                    )}
                    {change && <div>{change}</div>}
                    {rest && <div className="sub">{rest}</div>}
                  </div>
                </li>
              )
            })}
          </ul>
          {preview.hasMore && (
            <div className="bar-tools">
              <button type="button" className="btn" onClick={preview.more}>
                더 보기
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}

function AiCalls() {
  const casePath = useCasePath()
  const load = useLoad<AiUsage>('/api/ai/usage', [])
  const calls = usePreview([...(load.data?.calls ?? [])].reverse())
  if (load.error) return <LoadFailed retry={load.retry} message={`AI 호출 내역을 불러오지 못했어요. ${load.error}`} />
  const u = load.data
  if (!u)
    return (
      <p role="status" className="muted">
        불러오는 중…
      </p>
    )
  return (
    <section aria-label="AI 호출 영역">
      <p className="lead">
        AI 모드 {u.mode} · 지금까지 {usd(u.spent_usd)} (한도 {usd(u.total_cap_usd)}) · 오늘 {usd(u.spent_today_usd)} (하루 한도 {usd(u.daily_cap_usd)}) · 호출 {num(u.calls_total)}건
      </p>
      {u.calls.length === 0 ? (
        <p className="muted">AI를 부른 기록이 없어요</p>
      ) : (
        <>
        <ul className="ledger calls" aria-label="AI 호출 내역">
          {calls.visible.map((c) => (
            <li key={c.id}>
              <span className="sub">{timeText(c.ts)}</span>
              <div>
                <span className="k">
                  <Badge kind="AI" />
                  {c.kind}
                </span>{' '}
                · {c.model}
                {c.case_id !== null && (
                  <>
                    {' '}
                    · <Link to={casePath(c.case_id)}>건 #{c.case_id}</Link>
                  </>
                )}
                {c.summary && <div className="sub">{c.summary}</div>}
              </div>
              <span className="num">{c.confidence !== null ? `확신도 ${pct(c.confidence)}` : '확신도 없음'}</span>
              <span className="num">
                {num(c.in_tok)} / {num(c.out_tok)} 토큰
              </span>
              <span className="num">{usd(c.usd)}</span>
            </li>
          ))}
        </ul>
        {calls.hasMore && (
          <div className="bar-tools">
            <button type="button" className="btn" onClick={calls.more}>
              더 보기
            </button>
          </div>
        )}
        </>
      )}
    </section>
  )
}

function Assumptions() {
  const load = useLoad<PolicyItem[]>('/api/assumptions', [])
  const [q, setQ] = useState('')
  if (load.error) return <LoadFailed retry={load.retry} message={`가정 목록을 불러오지 못했어요. ${load.error}`} />
  if (!load.data)
    return (
      <p role="status" className="muted">
        불러오는 중…
      </p>
    )
  const needle = q.trim().toLowerCase()
  // 번호는 서버 목록 순서 그대로(검색해도 바뀌지 않는다)
  const numbered = load.data.map((r, i) => ({ r, no: i + 1 }))
  const found = numbered.filter(({ r }) => !needle || [r.key, r.description, r.source, anyValue(r.value)].join(' ').toLowerCase().includes(needle))
  return (
    <section aria-label="가정 영역">
      <p className="lead">원본에 없어 가정으로 정한 값이에요. 값은 정책 화면에서 고칠 수 있어요.</p>
      <div className="bar-tools">
        <label>
          가정 검색
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="항목·값·이유" />
        </label>
        <span className="muted">{num(found.length)}개</span>
      </div>
      {found.length === 0 ? (
        <p className="muted">찾는 가정이 없어요</p>
      ) : (
        <ul className="ledger assume" aria-label="가정 목록">
          {found.map(({ r, no }) => (
            <li key={r.key}>
              <span className="num">{no}</span>
              <div>
                <span className="k">{r.description}</span>
                <div className="sub">{r.key}</div>
              </div>
              <div>
                <span className="k">{anyValue(r.value)}</span>
                {r.overridden && <div className="sub">기본값 {anyValue(r.file_value)}에서 바뀜</div>}
              </div>
              <div>
                {r.source.startsWith(ASSUMPTION_PREFIX) && <Badge kind="가정" />}
                {r.source}
                {r.overridden && <div className="sub">{r.effective_source}</div>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default function Log() {
  const [tab, setTab] = useState<Tab>('처리 기록')
  return (
    <main className="admin">
      <h1>처리 기록·가정</h1>
      <p className="lead">지난 처리와 AI 호출, 가정을 확인하세요.</p>
      <div className="tabs" role="group" aria-label="기록 종류">
        {TABS.map((t) => (
          <button key={t} type="button" aria-pressed={tab === t} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      {tab === '처리 기록' && <Events />}
      {tab === 'AI 호출 내역' && <AiCalls />}
      {tab === '가정 목록' && <Assumptions />}
    </main>
  )
}
