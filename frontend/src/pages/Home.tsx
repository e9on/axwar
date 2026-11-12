import './Home.css'
import TodoList from '../components/TodoList'
import Timeline from '../components/Timeline'

export default function Home() {
  return (
    <main className="home">
      <Timeline />
      <TodoList />
    </main>
  )
}
