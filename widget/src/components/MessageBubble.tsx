// Owner: Charbel

import React from 'react'
import { ChatMessage } from '../api'

interface Props {
  message: ChatMessage
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function MessageBubble({ message }: Props) {
  const isError = message.role === 'assistant' && message.content.startsWith('__error__')
  const content = isError ? message.content.replace('__error__', '') : message.content

  return (
    <div>
      <div className={`message ${isError ? 'error' : message.role}`}>
        {content}
      </div>
      <div className="message-time" style={{ textAlign: message.role === 'user' ? 'right' : 'left' }}>
        {formatTime(message.timestamp)}
      </div>
    </div>
  )
}
