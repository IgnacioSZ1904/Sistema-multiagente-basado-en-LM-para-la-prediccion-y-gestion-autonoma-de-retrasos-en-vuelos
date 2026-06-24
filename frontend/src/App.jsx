import { useEffect, useMemo, useState } from 'react'

const API_BASE_URL = 'http://127.0.0.1:8000/api'

const initialForm = {
  query: '¿Qué aeropuertos tienen más retrasos?',
}

export function App() {
  const [form, setForm] = useState(initialForm)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [health, setHealth] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    fetch(`${API_BASE_URL}/health`)
      .then((response) => response.json())
      .then((data) => setHealth(data))
      .catch(() => {
        setHealth({ status: 'unavailable' })
      })
  }, [])

  const metrics = useMemo(() => {
    if (!result) {
      return []
    }

    return [
      {
        label: 'Iteraciones',
        value: result.iteration,
      },
      {
        label: 'Siguiente nodo',
        value: result.next_agent,
      },
      {
        label: 'Disrupción',
        value: result.delay_prediction?.is_disruption ? 'Sí' : 'No',
      },
    ]
  }, [result])

  async function handleSubmit(event) {
    event.preventDefault()
    setLoading(true)
    setError('')

    try {
      const response = await fetch(`${API_BASE_URL}/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(form),
      })

      if (!response.ok) {
        throw new Error('No se pudo completar la consulta')
      }

      const data = await response.json()
      setResult(data)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

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

      <section className="grid">
        <form className="card" onSubmit={handleSubmit}>
          <h2>Consulta operacional</h2>
          <label htmlFor="query">Prompt</label>
          <textarea
            id="query"
            rows="6"
            value={form.query}
            onChange={(event) => setForm({ query: event.target.value })}
          />
          <button type="submit" disabled={loading}>
            {loading ? 'Procesando...' : 'Ejecutar consulta'}
          </button>
          {error ? <p className="error">{error}</p> : null}
        </form>

        <div className="card">
          <h2>Métricas</h2>
          <div className="metrics">
            {metrics.map((metric) => (
              <article key={metric.label} className="metric">
                <span>{metric.label}</span>
                <strong>{metric.value ?? 'N/A'}</strong>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="card output">
        <h2>Respuesta del sistema</h2>
        <pre>{result?.final_response ?? 'Sin respuesta todavía.'}</pre>
      </section>
    </main>
  )
}
