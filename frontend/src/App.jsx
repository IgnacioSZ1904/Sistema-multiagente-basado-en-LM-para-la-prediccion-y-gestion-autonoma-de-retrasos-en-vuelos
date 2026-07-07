import { useEffect, useState } from 'react'
import { API_BASE_URL } from './api'
import { ChatPanel } from './components/ChatPanel'
import { DashboardPanel } from './components/DashboardPanel'

const TABS = [
  { id: 'chat', label: 'Chat' },
  { id: 'dashboard', label: 'Panel de estado' },
]

export function App() {
  const [health, setHealth] = useState(null)
  const [activeTab, setActiveTab] = useState('chat')

  useEffect(() => {
    fetch(`${API_BASE_URL}/health`)
      .then((response) => response.json())
      .then((data) => setHealth(data))
      .catch(() => {
        setHealth({ status: 'unavailable' })
      })
  }, [])

  return (
    <main className="layout">
      <section className="hero">
        <div>
          <p className="eyebrow">SGIDA</p>
          <h1>Gestión autónoma de retrasos aéreos</h1>
          <p className="description">
            Backend multiagente con Ollama local y panel React para operadores.
          </p>
        </div>
        <div className="status-card">
          <span>API</span>
          <strong>{health?.status ?? 'cargando'}</strong>
          <small>Modelo: {health?.model ?? 'no disponible'}</small>
        </div>
      </section>

      <nav className="tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={activeTab === tab.id ? 'tab tab--active' : 'tab'}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {activeTab === 'chat' ? <ChatPanel /> : <DashboardPanel />}
    </main>
  )
}
