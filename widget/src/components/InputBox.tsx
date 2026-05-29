// Owner: Charbel

import React, { useRef, KeyboardEvent } from 'react'

interface Props {
  value: string
  onChange: (val: string) => void
  onSend: () => void
  disabled: boolean
}

export function InputBox({ value, onChange, onSend, disabled }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!disabled && value.trim()) onSend()
    }
  }

  function handleInput() {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  }

  return (
    <div className="concierge-input-area">
      <textarea
        ref={textareaRef}
        className="concierge-input"
        placeholder="Type a message…"
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
        disabled={disabled}
        rows={1}
      />
      <button
        className="concierge-send"
        onClick={onSend}
        disabled={disabled || !value.trim()}
        aria-label="Send"
      >
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
        </svg>
      </button>
    </div>
  )
}
