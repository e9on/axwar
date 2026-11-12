export default function LoadFailed({ retry }: { retry: () => void }) {
  return (
    <div className="load-failed" role="group" aria-label="불러오기 실패">
      <span>불러오지 못했어요</span>
      <button type="button" onClick={retry}>다시 시도</button>
    </div>
  )
}
