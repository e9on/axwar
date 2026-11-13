import './Home.css'
import TodoList from '../components/TodoList'
import Timeline from '../components/Timeline'

export default function Home() {
  return (
    <main className="home">
      <h1 className="sr-only">메인 화면</h1>
      <Timeline />
      <TodoList />
    </main>
  )
}
