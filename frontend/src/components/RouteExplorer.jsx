import { useEffect, useMemo, useState } from 'react'
import { API_BASE_URL } from '../api'

export function RouteExplorer() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [filterText, setFilterText] = useState('')
  const [selectedOrigin, setSelectedOrigin] = useState(null)

  useEffect(() => {
    fetch(`${API_BASE_URL}/routes`)
      .then((response) => {
        if (!response.ok) {
          throw new Error('No se pudieron cargar las rutas')
        }
        return response.json()
      })
      .then((payload) => {
        setData(payload)
        setSelectedOrigin(payload.origins?.[0] ?? null)
      })
      .catch((requestError) => setError(requestError.message))
      .finally(() => setLoading(false))
  }, [])

  const origins = data?.origins ?? []
  const filteredOrigins = useMemo(() => {
    const needle = filterText.trim().toLowerCase()
    if (!needle) return origins
    return origins.filter((origin) => origin.toLowerCase().includes(needle))
  }, [origins, filterText])

  const destinations = selectedOrigin ? data?.routes[selectedOrigin] ?? [] : []

  return (
    <div className="card route-explorer">
      <h2>Rutas disponibles</h2>
      <small>Aeropuertos de origen y destinos según los datos históricos de vuelos.</small>

      {error ? <p className="error">{error}</p> : null}
      {loading ? <p>Cargando...</p> : null}

      {!loading && !error ? (
        <>
          <input
            type="text"
            className="route-explorer__search"
            placeholder="Buscar ciudad de origen..."
            value={filterText}
            onChange={(event) => setFilterText(event.target.value)}
          />

          <div className="route-lists">
            <ul className="route-origin-list">
              {filteredOrigins.map((origin) => (
                <li key={origin}>
                  <button
                    type="button"
                    className={
                      origin === selectedOrigin ? 'route-origin route-origin--active' : 'route-origin'
                    }
                    onClick={() => setSelectedOrigin(origin)}
                  >
                    {origin}
                  </button>
                </li>
              ))}
              {filteredOrigins.length === 0 ? <li className="route-origin-list__empty">Sin resultados.</li> : null}
            </ul>

            {selectedOrigin ? (
              <div className="route-destinations">
                <h3>Destinos desde {selectedOrigin}</h3>
                <ul>
                  {destinations.map((destination) => (
                    <li key={destination}>{destination}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  )
}
