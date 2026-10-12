// TEMP: dev-only accept button — remove after Sprint 8.5.
// Цель: проверить end-to-end accept_mission на телефоне без готового UI карты.
// В production-сборке не рендерится (import.meta.env.DEV === false).

import { useState } from 'react'
import { acceptEngineMission } from '../api/engineApi'

// Захардкоженный id миссии для теста. Поменять при необходимости.
const DEV_MISSION_ID = 'mission-d36d8f9130944783bce7dc1d4dcd15c3'

export function DevAcceptMissionButton() {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  async function handleAccept() {
    setLoading(true)
    setResult(null)
    try {
      const coords = await new Promise<GeolocationPosition>((resolve, reject) => {
        if (!navigator.geolocation) {
          reject(new Error('navigator.geolocation недоступен'))
          return
        }
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 15000,
        })
      })

      const response = await acceptEngineMission(DEV_MISSION_ID, {
        latitude: coords.coords.latitude,
        longitude: coords.coords.longitude,
        accuracy: coords.coords.accuracy,
      })

      const spawn = response.spawn
      setResult(
        `OK status=${response.status}\n` +
        `GPS: ${coords.coords.latitude.toFixed(5)}, ${coords.coords.longitude.toFixed(5)}\n` +
        `Spawn: ${spawn.latitude.toFixed(5)}, ${spawn.longitude.toFixed(5)}\n` +
        `searchR=${spawn.searchRadiusMeters}m zoneR=${spawn.zoneRadiusMeters}m\n` +
        `arObjectId=${spawn.arObjectId ?? '—'}`,
      )
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setResult(`ОШИБКА: ${message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 80,
        right: 12,
        zIndex: 9999,
        maxWidth: 'calc(100vw - 24px)',
        background: 'rgba(0, 0, 0, 0.85)',
        color: '#00ff88',
        padding: '12px',
        borderRadius: '8px',
        fontFamily: 'monospace',
        fontSize: '11px',
        lineHeight: 1.4,
      }}
    >
      <button
        onClick={handleAccept}
        disabled={loading}
        style={{
          background: loading ? '#555' : '#00ff88',
          color: '#000',
          border: 'none',
          padding: '8px 12px',
          fontWeight: 'bold',
          cursor: loading ? 'wait' : 'pointer',
          borderRadius: '4px',
          width: '100%',
        }}
      >
        {loading ? 'Отправка…' : '[DEV] Взять миссию'}
      </button>
      {result && (
        <pre style={{ marginTop: 8, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {result}
        </pre>
      )}
    </div>
  )
}
