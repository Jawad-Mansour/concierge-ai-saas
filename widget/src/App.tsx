// Owner: Charbel

import React, { useState, useEffect } from 'react'
import { ChatMessage, sendMessage as apiSendMessage } from './api'
import { exchangeToken } from './auth'
import { ChatWindow } from './components/ChatWindow'

// TODO: once the backend wires widget token → tenant_id claim, remove this
// admin JWT fallback and rely solely on exchangeToken(). Currently widget
// tokens are short-lived (15 min) and don't carry tenant_id in the JWT
// claim that the /chat endpoint reads from claims.tenant_id. Until that
// mapping is implemented, the widget falls back to the token from
// exchangeToken (which will 401 on /chat). The demo uses an admin JWT
// obtained via POST /auth/login instead.
const API_URL = 'http://localhost:8000'
const widgetId = new URLSearchParams(window.location.search).get('widget_id')
const GREETING = 'Hi! How can I help you today?'

function generateId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}

export default function App() {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [token, setToken] = useState<string | null>(null)
  const [conversationId] = useState(() => generateId())
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!widgetId) {
      setError('Widget not configured')
      return
    }
    exchangeToken(widgetId, window.location.origin)
      .then(t => setToken(t))
      .catch(err => {
        console.warn('[Concierge] Token exchange failed:', err)
        setError('Could not connect to Concierge service.')
      })
  }, [])

  async function handleSend() {
    const text = input.trim()
    if (!text || isLoading || !token) return

    const userMsg: ChatMessage = { role: 'user', content: text, timestamp: Date.now() }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setIsLoading(true)

    try {
      const resp = await apiSendMessage(text, conversationId, token)
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: resp.message,
        timestamp: Date.now(),
      }
      setMessages(prev => [...prev, assistantMsg])
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        role: 'assistant',
        content: `__error__${err?.message || 'Something went wrong.'}`,
        timestamp: Date.now(),
      }
      setMessages(prev => [...prev, errorMsg])
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <>
      {isOpen && (
        <ChatWindow
          messages={messages}
          input={input}
          isLoading={isLoading}
          disabled={isLoading || !token}
          greeting={error ?? GREETING}
          onClose={() => setIsOpen(false)}
          onInputChange={setInput}
          onSend={handleSend}
        />
      )}

      <button
        className="concierge-bubble"
        onClick={() => setIsOpen(o => !o)}
        aria-label={isOpen ? 'Close chat' : 'Open chat'}
      >
        {isOpen ? (
          <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z" />
          </svg>
        )}
      </button>
    </>
  )
}
