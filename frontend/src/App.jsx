import { useState } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { DashboardPanel } from './components/DashboardPanel'
import { RouteExplorer } from './components/RouteExplorer'

const TABS = [
  { id: 'chat', label: 'Chat' },
  { id: 'dashboard', label: 'Panel de estado' },
]

export function App() {
  const [activeTab, setActiveTab] = useState('chat')

  return (
    <main className="layout">
      <div className="main-column">
        <section className="hero">
          <p className="eyebrow">SGIDA</p>
          <h1>Gestión autónoma de retrasos aéreos</h1>
          <p className="description">
            Backend multiagente con Ollama local y panel React para operadores.
          </p>
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

        <div className="panel-area">
          {activeTab === 'chat' ? <ChatPanel /> : <DashboardPanel />}
        </div>
      </div>

      {activeTab === 'chat' ? <RouteExplorer /> : null}
    </main>
  )
}
