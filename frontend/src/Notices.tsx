import { useEffect, useState } from 'react'
import { onApiError } from './api'

type Notice = { id: number; message: string }

/** 화면 위쪽 알림 줄. API 오류를 한국어로 보여 주고 닫을 수 있다. */
export default function Notices() {
  const [notices, setNotices] = useState<Notice[]>([])

  useEffect(() => {
    let next = 0
    return onApiError((error) => {
      setNotices((list) => [...list, { id: next++, message: error.message }])
    })
  }, [])

  if (notices.length === 0) return null
  return (
    <div className="notices">
      {notices.map((n) => (
        <div key={n.id} role="alert" className="notice">
          <span>{n.message}</span>
          <button type="button" aria-label="알림 닫기" onClick={() => setNotices((l) => l.filter((x) => x.id !== n.id))}>
            닫기
          </button>
        </div>
      ))}
    </div>
  )
}
