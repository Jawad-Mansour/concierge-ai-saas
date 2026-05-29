// Owner: Charbel

const API_URL = (window as any).__CONCIERGE_API_URL__ || 'http://localhost:8000'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
}

export interface ChatResponse {
  conversation_id: string
  decision: string
  message: string
  trace_id: string | null
}

export async function sendMessage(
  message: string,
  conversationId: string,
  token: string,
): Promise<ChatResponse> {
  const resp = await fetch(`${API_URL}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({
      conversation_id: conversationId,
      visitor_session_id: conversationId,
      message,
    }),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error((err as any).detail || `Chat failed: ${resp.status}`)
  }
  return resp.json()
}
