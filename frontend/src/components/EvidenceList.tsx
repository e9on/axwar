import { useId, useState, type ReactNode } from 'react'
import Badge from './Badge'
import Fold from './Fold'
import { anyValue, splitPath, unitValue } from '../format'
import type { Detail, EvidenceData, IndicatorLine, SignalLine } from '../caseTypes'
import './EvidenceList.css'

const LEVEL: Record<SignalLine['level'], { text: string; cls: string }> = {
  red: { text: '나쁨', cls: 'red' },
  yellow: { text: '주의', cls: 'yel' },
  green: { text: '좋음', cls: 'grn' },
  unmeasurable: { text: '측정 불가', cls: 'none' },
}

export function DetailPanel({ detail, note }: { detail: Detail | undefined; note?: string }) {
  const d = detail ?? { formula: '', inputs: [], sources: [], policies: [] }
  const empty = !d.formula && d.inputs.length === 0 && d.sources.length === 0 && d.policies.length === 0 && !note
  if (empty) return <p className="muted">자세한 근거가 아직 없어요</p>
  return (
    <div className="edetail">
      {d.formula && (
        <p>
          <span className="dh">계산식</span> {d.formula}
        </p>
      )}
      {note && (
        <p>
          <span className="dh">판정에서 뺀 이유</span> {note}
        </p>
      )}
      {d.inputs.length > 0 && (
        <>
          <p className="dh">입력값</p>
          <dl className="inputs">
            {d.inputs.map((i) => (
              <div key={i.label}>
                <dt>{i.label}</dt>
                <dd>{typeof i.value === 'number' && i.unit ? unitValue(i.value, i.unit) : anyValue(i.value)}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
      {d.sources.length > 0 && (
        <>
          <p className="dh">원본 파일</p>
          <ul className="sources">
            {d.sources.map((s, n) => {
              const { dir, file } = splitPath(s)
              return (
                <li key={`${n}-${s}`}>
                  <b>{file}</b> <span className="muted">{dir}</span>
                </li>
              )
            })}
          </ul>
        </>
      )}
      {d.policies.length > 0 && (
        <>
          <p className="dh">쓰인 정책 값</p>
          <ul className="policies">
            {d.policies.map((p) => {
              const assumed = !!p.source?.startsWith('가정')
              return (
                <li key={p.key} data-assumed={assumed}>
                  <p>
                    {assumed && <Badge kind="가정" />}
                    <code>{p.key}</code>
                    {p.missing ? <b> 없어진 정책 항목</b> : <> = <b>{anyValue(p.value)}</b></>}
                  </p>
                  {p.source && <p className="muted">출처: {p.source}</p>}
                  {p.description && <p>{p.description}</p>}
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}

type RowProps = {
  id: string
  open: boolean
  toggle: (id: string) => void
  detail: Detail | undefined
  note?: string
  kind: 'rule' | 'signal' | 'indicator' | 'cost'
  assumed?: boolean
  superseded?: boolean
  children: ReactNode
}

/** 줄 하나 = 펼침 버튼 + 펼쳐지는 칸. 누르면 아래가 열리고 다시 누르면 닫힌다. */
export function Row({ id, open, toggle, detail, note, kind, assumed, superseded, children }: RowProps) {
  const panel = `${id}-detail`
  return (
    <li className="erow" data-open={open} data-assumed={assumed ? 'true' : undefined} data-superseded={superseded ? 'true' : undefined}>
      <button type="button" className={`ebtn ${kind}`} aria-expanded={open} aria-controls={panel} onClick={() => toggle(id)}>
        {children}
        <span className="chev" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
      </button>
      <div id={panel} className="epanel" hidden={!open}>
        <DetailPanel detail={detail} note={note} />
      </div>
    </li>
  )
}

export function signalValue(s: SignalLine): string {
  return s.value === null || s.level === 'unmeasurable' ? '측정 불가' : unitValue(s.value, s.unit)
}

export function indicatorValue(i: IndicatorLine): string {
  if (i.value === null) return '측정 불가'
  const v = typeof i.value === 'boolean' ? (i.value ? '있음' : '없음') : unitValue(i.value, i.unit)
  return i.rank !== null && i.of !== null ? `${v} (${i.rank}위/${i.of})` : v
}

function signalSummary(signals: SignalLine[]): string {
  const n = (lv: SignalLine['level']) => signals.filter((s) => s.level === lv).length
  return `나쁨 ${n('red')}건 · 주의 ${n('yellow')}건 · 좋음 ${n('green')}건`
}

export default function EvidenceList({ data }: { data: EvidenceData }) {
  const uid = useId()
  const [open, setOpen] = useState<Set<string>>(new Set())
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const rid = (name: string) => `${uid}-${name}`.replace(/:/g, '')
  const props = (name: string) => ({ id: rid(name), open: open.has(rid(name)), toggle })

  // 상신 뒤 처음 판정(superseded)은 아래로: 지금 결재선을 만든 줄이 맨 위
  const approverHits = [...data.rule.approver_hits].sort((x, y) => Number(!!x.superseded) - Number(!!y.superseded))
  const ruleLines = [
    ...approverHits.map((h) => ({ ...h, group: 'a' })),
    ...data.rule.phase2_approver_hits.map((h) => ({ ...h, group: 'p2' })),
    ...data.rule.indicator_hits.map((h) => ({ ...h, group: 'i' })),
  ]

  return (
    <div className="evidence">
      <p className="muted asm-note">가정 = 원본에 없어 정한 값</p>
      <Fold title="결재 이유" summary={ruleLines.length === 0 ? '이유가 아직 없어요' : `${ruleLines.length}개`}>
        {ruleLines.length === 0 ? (
          <p className="muted">결재선 이유가 아직 없어요</p>
        ) : (
          <ul className="elist rule-box">
            {ruleLines.map((h, i) => (
              <Row key={`${h.group}${i}`} {...props(`rule-${h.group}${i}`)} detail={h.detail} kind="rule" assumed={h.badge === '가정'} superseded={h.superseded}>
                <span className="ecell text">
                  <Badge kind={h.badge} />
                  {h.superseded && <span className="stage">처음 판정 </span>}
                  {h.group === 'p2' && <span className="stage">2차 </span>}
                  {h.group === 'i' && <span className="stage">지표 </span>}
                  {h.text}
                </span>
                <span className="ecell src muted">{h.source}</span>
              </Row>
            ))}
          </ul>
        )}
      </Fold>

      {!data.available ? (
        <Fold title="지표 근거" summary="만들 수 없어요">
          <p className="muted">{data.reason ?? '이 건은 지표 근거를 만들 수 없어요'}</p>
        </Fold>
      ) : (
        <>
          <Fold title="위험 신호" summary={signalSummary(data.signals)}>
            <div className="ehead signal">
              <span>신호</span>
              <span>지표</span>
              <span className="n">값</span>
              <span>비교·근거</span>
              <span />
            </div>
            <ul className="elist">
              {data.signals.map((s) => {
                const lv = LEVEL[s.level] ?? LEVEL.unmeasurable
                const note = s.exclude_reason || (s.level === 'unmeasurable' ? s.compare : undefined)
                return (
                  <Row key={s.key} {...props(`sig-${s.key}`)} detail={s.detail} kind="signal" assumed={s.badge === '가정'} note={note}>
                    <span className={`ecell lv ${lv.cls}`}>{lv.text}</span>
                    <span className="ecell">{s.label}</span>
                    <span className="ecell n">{signalValue(s)}</span>
                    <span className="ecell cmp">
                      <Badge kind={s.badge} />
                      {s.compare}
                      {s.judgment === '참고' && <span className="muted"> · 참고용</span>}
                    </span>
                  </Row>
                )
              })}
            </ul>
          </Fold>

          <Fold title="핵심 지표" summary={`${data.key_indicators.length}개`}>
            <ul className="elist">
              {data.key_indicators.map((k) => (
                <Row key={k.key} {...props(`key-${k.key}`)} detail={k.detail} kind="indicator" assumed={k.badge === '가정'}>
                  <span className="ecell">{k.label}</span>
                  <span className="ecell n">{indicatorValue(k)}</span>
                  <span className="ecell cmp">
                    <Badge kind={k.badge} />
                    {k.compare_label && k.compare_value !== null && `${k.compare_label} ${unitValue(k.compare_value, k.compare_unit ?? k.unit)}`}
                  </span>
                </Row>
              ))}
            </ul>
          </Fold>

          <Fold title="비용 분해" summary={`${data.cost_breakdown.rows.length}개 항목`}>
            <p className="note">{data.cost_breakdown.note}</p>
            <ul className="elist">
              {data.cost_breakdown.rows.map((r) => (
                <Row key={r.key} {...props(`cost-${r.key}`)} detail={r.detail} kind="cost" assumed={r.badge === '가정'}>
                  <span className="ecell">{r.label}</span>
                  <span className="ecell n">{unitValue(r.amount, r.unit ?? 'krw')}</span>
                  <span className="ecell cmp">
                    <Badge kind={r.badge} />
                  </span>
                </Row>
              ))}
            </ul>
            {data.breakeven && (
              <>
                <p className="dh-line">본전 조건</p>
                <ul className="elist">
                <Row {...props('be')} detail={data.breakeven.detail} kind="indicator" assumed={data.breakeven.badge === '가정'}>
                  <span className="ecell">{data.breakeven.label}</span>
                  <span className="ecell n">{data.breakeven.value === null ? '측정 불가' : unitValue(data.breakeven.value, data.breakeven.unit ?? 'ratio')}</span>
                  <span className="ecell cmp">
                    <Badge kind={data.breakeven.badge} />
                    {data.breakeven.compare}
                  </span>
                </Row>
                </ul>
              </>
            )}
            {data.attribution_note && <p className="limit">측정 한계: {data.attribution_note}</p>}
          </Fold>
        </>
      )}
    </div>
  )
}
