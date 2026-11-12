/** message: 무엇을 못 읽었는지(기본은 일반 문구), buttonName: 같은 화면에 여럿일 때 버튼을 구별하는 이름 */
export default function LoadFailed({ retry, message = '불러오지 못했어요', buttonName }: { retry: () => void; message?: string; buttonName?: string }) {
  return (
    <div className="load-failed" role="group" aria-label="불러오기 실패">
      <span>{message}</span>
      <button type="button" onClick={retry} aria-label={buttonName}>다시 시도</button>
    </div>
  )
}
