// Owner: Charbel

const API_URL = (window as any).__CONCIERGE_API_URL__ || 'http://localhost:8000'

export interface TokenResponse {
  token: string
  expires_in: number
}

export async function exchangeToken(
  widgetId: string,
  origin: string
): Promise<string> {
  const resp = await fetch(`${API_URL}/widget/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ widget_id: widgetId, origin }),
  })
  if (!resp.ok) {
    throw new Error(`Token exchange failed: ${resp.status}`)
  }
  const data: TokenResponse = await resp.json()
  return data.token
}
