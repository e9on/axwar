import { useNavigate } from 'react-router-dom'
import { useViewer } from './viewer'

/** 건 상세로 가는 함수. 보는 사람(?as=)을 그대로 들고 간다. */
export function useCaseLink(): (caseId: number) => void {
  const navigate = useNavigate()
  const { person } = useViewer()
  return (caseId) => navigate(`/cases/${caseId}` + (person ? `?as=${encodeURIComponent(person.name)}` : ''))
}
