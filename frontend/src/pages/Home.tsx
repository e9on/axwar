import './Home.css'
import TodoList from '../components/TodoList'
import Timeline from '../components/Timeline'
import DemoBar from '../components/DemoBar'
import { useDemoScene } from '../state/demoScene'

export default function Home() {
  const demo = useDemoScene()
  return (
    <main className="home">
      <h1 className="sr-only">메인 화면</h1>
      <DemoBar demo={demo} />
      <TodoList highlightRef={demo.highlightRef} inScene={!!demo.scene} />
      <Timeline />
    </main>
  )
}
