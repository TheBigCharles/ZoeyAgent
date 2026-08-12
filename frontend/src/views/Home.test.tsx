import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Home from './Home'

describe('Home page', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('shows session continuity without exposing the exact session id', () => {
    sessionStorage.setItem('zoey_session_id', 'session-secret-123')

    render(
      <MemoryRouter>
        <Home />
      </MemoryRouter>
    )

    expect(screen.getByText('已找到当前 planning session')).toBeInTheDocument()
    expect(screen.getByText('后续请求会继续使用当前会话。')).toBeInTheDocument()
    expect(screen.queryByText(/session-secret-123/)).not.toBeInTheDocument()
  })
})
