import { Outlet } from 'react-router-dom'
import { Compass } from 'lucide-react'

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <Compass size={24} aria-hidden />
          <div>
            <strong>ZoeyAgent</strong>
            <span>智能旅行规划</span>
          </div>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
