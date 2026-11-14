import { useClock } from './clock'
import { useViewer } from './viewer'
import { useLoad } from './useLoad'
import type { AdminKey, Permission, PersonPermissions } from '../adminTypes'

/** 보는 사람의 관리 권한(GET /api/permissions?person=). 읽기 전에는 어떤 동작도 해도 된다고 보지 않는다. */
export function usePermissions() {
  const { person } = useViewer()
  const { version } = useClock()
  const load = useLoad<PersonPermissions[]>(person ? `/api/permissions?person=${encodeURIComponent(person.name)}` : null, [version])
  const admin = load.data?.[0]?.admin ?? null
  return {
    ready: !!admin,
    failed: !!load.error,
    /** 해당 동작의 권한. 아직 못 읽었으면 null */
    of: (key: AdminKey): Permission | null => admin?.[key] ?? null,
  }
}
