// Owner: Charbel

import React, { useEffect, useRef } from 'react'
import { ChatMessage } from '../api'
import { MessageBubble } from './MessageBubble'
import { InputBox } from './InputBox'

interface Props {
  messages: ChatMessage[]
  input: string
  isLoading: boolean
  disabled: boolean
  greeting: string
  onClose: () => void
  onInputChange: (val: string) => void
  onSend: () => void
}

export function ChatWindow({
  messages,
  input,
  isLoading,
  disabled,
  greeting,
  onClose,
  onInputChange,
  onSend,
}: Props) {
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  return (
    <div className="concierge-panel">
      <div className="concierge-header">
        <div>
          <h3>Concierge</h3>
        </div>
        <div className="status">
          <span className="status-dot" />
          Online
        </div>
        <button className="concierge-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>

      <div className="concierge-messages">
        {messages.length === 0 && (
          <div className="greeting">{greeting}</div>
        )}
        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}
        {isLoading && (
          <div className="typing">
            <span /><span /><span />
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <InputBox
        value={input}
        onChange={onInputChange}
        onSend={onSend}
        disabled={disabled}
      />
    </div>
  )
}
