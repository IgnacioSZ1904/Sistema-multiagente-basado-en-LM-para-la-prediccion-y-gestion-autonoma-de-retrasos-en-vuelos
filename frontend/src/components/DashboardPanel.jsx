import { useEffect, useState } from 'react'
import { API_BASE_URL } from '../api'

export function DashboardPanel() {
  const [dashboard, setDashboard] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function loadDashboard() {
    setLoading(true)
    setError('')
    try {
      const response = await fetch(`${API_BASE_URL}/dashboard`)
      if (!response.ok) {
        throw new Error('No se pudo cargar el panel de estado')
      }
      setDashboard(await response.json())
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadDashboard()
  }, [])

  const metrics = dashboard?.metrics
  const recentActivity = dashboard?.recent_activity ?? []
  const notifications = dashboard?.notifications ?? []
  const severityEntries = Object.entries(metrics?.severity_distribution ?? {})

  return (
    <section className="grid">
      <div className="card">
        <div className="dashboard-header">
          <h2>Métricas globales</h2>
          <button type="button" onClick={loadDashboard} disabled={loading}>
            {loading ? 'Actualizando...' : 'Actualizar'}
          </button>
        </div>
        {error ? <p className="error">{error}</p> : null}
        <div className="metrics">
          <article className="metric">
            <span>Consultas procesadas</span>
            <strong>{metrics?.total_queries ?? 0}</strong>
          </article>
          <article className="metric">
            <span>Disrupciones detectadas</span>
            <strong>{metrics?.total_disruptions ?? 0}</strong>
          </article>
          <article className="metric">
            <span>Notificaciones enviadas</span>
            <strong>{notifications.length}</strong>
          </article>
        </div>
        {severityEntries.length > 0 && (
          <div className="severity-distribution">
            <h3>Distribución de severidad</h3>
            <ul>
              {severityEntries.map(([severity, count]) => (
                <li key={severity}>
                  <span>{severity}</span>
                  <strong>{count}</strong>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="card">
        <h2>Actividad reciente</h2>
        <small>Historial en memoria de esta sesión del backend (se reinicia al reiniciar el servidor).</small>
        {recentActivity.length === 0 ? (
          <p>Todavía no se ha procesado ninguna consulta en esta sesión.</p>
        ) : (
          <ul className="activity-list">
            {recentActivity.map((entry, index) => (
              <li
                key={`${entry.timestamp}-${index}`}
                className={
                  entry.delay_prediction?.is_disruption ? 'activity-item activity-item--risk' : 'activity-item'
                }
              >
                <div className="activity-item__header">
                  <span>{entry.timestamp}</span>
                  {entry.delay_prediction?.is_disruption ? (
                    <span className="risk-badge">Vuelo en riesgo</span>
                  ) : null}
                </div>
                <p>{entry.query}</p>
                {entry.disruption_proposal ? (
                  <p className="activity-item__decision">
                    Severidad {entry.disruption_proposal.severity} — {entry.disruption_proposal.actions?.[0]}
                  </p>
                ) : null}
                {entry.error ? <p className="error">{entry.error}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
