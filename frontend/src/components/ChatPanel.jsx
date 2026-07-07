import { useState } from 'react'
import { API_BASE_URL } from '../api'

const initialForm = {
  query: '¿Qué aeropuertos tienen más retrasos?',
  optimization_criterion: 'min_passengers',
}

const OPTIMIZATION_CRITERIA = [
  { value: 'min_passengers', label: 'Minimizar pasajeros afectados' },
  { value: 'min_cost', label: 'Minimizar coste operativo' },
]

let messageIdCounter = 0
function nextMessageId() {
  messageIdCounter += 1
  return messageIdCounter
}

export function ChatPanel() {
  const [form, setForm] = useState(initialForm)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [messages, setMessages] = useState([])
  const [sendingNotificationId, setSendingNotificationId] = useState(null)

  async function handleSubmit(event) {
    event.preventDefault()
    setLoading(true)
    setError('')

    const userMessage = { id: nextMessageId(), role: 'user', content: form.query }
    setMessages((prev) => [...prev, userMessage])

    try {
      const response = await fetch(`${API_BASE_URL}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })

      if (!response.ok) {
        throw new Error('No se pudo completar la consulta')
      }

      const data = await response.json()

      const systemMessage = {
        id: nextMessageId(),
        role: 'system',
        content: data.final_response,
        draftNotifications: (data.draft_notifications || []).map((draft, index) => ({
          ...draft,
          localId: `draft-${nextMessageId()}-${index}`,
          status: 'draft',
        })),
      }
      setMessages((prev) => [...prev, systemMessage])
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleSendNotification(messageId, draft) {
    setSendingNotificationId(draft.localId)
    setError('')

    try {
      const response = await fetch(`${API_BASE_URL}/notifications/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          recipient_type: draft.recipient_type,
          message: draft.message,
          flight_reference: draft.flight_reference,
          channel: draft.channel,
        }),
      })

      if (!response.ok) {
        throw new Error('No se pudo enviar la notificación')
      }

      setMessages((prev) =>
        prev.map((message) =>
          message.id === messageId
            ? {
                ...message,
                draftNotifications: message.draftNotifications.map((candidate) =>
                  candidate.localId === draft.localId ? { ...candidate, status: 'sent' } : candidate
                ),
              }
            : message
        )
      )
    } catch (sendError) {
      setError(sendError.message)
    } finally {
      setSendingNotificationId(null)
    }
  }

  return (
    <section className="grid">
      <div className="card chat-panel">
        <h2>Conversación</h2>
        <div className="chat-history">
          {messages.length === 0 ? (
            <p className="chat-empty">Escribe una consulta para empezar.</p>
          ) : (
            messages.map((message) => (
              <div key={message.id} className={`chat-bubble chat-bubble--${message.role}`}>
                <p>{message.content}</p>
                {message.draftNotifications?.length > 0 && (
                  <div className="notification-drafts">
                    {message.draftNotifications.map((draft) => (
                      <div key={draft.localId} className="notification-draft">
                        <span className="notification-draft__recipient">
                          {draft.recipient_type === 'passenger' ? 'Borrador para pasajero' : 'Borrador para operador'}
                        </span>
                        <p>{draft.message}</p>
                        <button
                          type="button"
                          disabled={draft.status === 'sent' || sendingNotificationId === draft.localId}
                          onClick={() => handleSendNotification(message.id, draft)}
                        >
                          {draft.status === 'sent' ? 'Enviada' : 'Enviar'}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        <form onSubmit={handleSubmit}>
          <label htmlFor="query">Prompt</label>
          <textarea
            id="query"
            rows="4"
            value={form.query}
            onChange={(event) => setForm({ ...form, query: event.target.value })}
          />

          <label htmlFor="optimization_criterion">Criterio de optimización</label>
          <select
            id="optimization_criterion"
            value={form.optimization_criterion}
            onChange={(event) => setForm({ ...form, optimization_criterion: event.target.value })}
          >
            {OPTIMIZATION_CRITERIA.map((criterion) => (
              <option key={criterion.value} value={criterion.value}>
                {criterion.label}
              </option>
            ))}
          </select>

          <button type="submit" disabled={loading}>
            {loading ? 'Procesando...' : 'Ejecutar consulta'}
          </button>
          {error ? <p className="error">{error}</p> : null}
        </form>
      </div>
    </section>
  )
}
