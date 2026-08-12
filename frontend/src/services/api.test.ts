import { beforeEach, describe, expect, it, vi } from 'vitest'
import { buildTripPlanRequest, generateTripPlan } from './api'

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
  get: vi.fn()
}))

vi.mock('axios', () => ({
  default: {
    create: () => ({
      post: mocks.post,
      get: mocks.get,
      interceptors: {
        request: { use: vi.fn() },
        response: { use: vi.fn() }
      }
    }),
    isAxiosError: (error: unknown) => Boolean(error && typeof error === 'object' && 'isAxiosError' in error)
  }
}))

describe('buildTripPlanRequest', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('maps form choices to backend TripPlanRequest enum indexes', () => {
    const request = buildTripPlanRequest({
      user_id: 'frontend-user',
      city: 'Beijing',
      start_date: '2026-06-20',
      end_date: '2026-06-21',
      transport_preference: 1,
      accommodation_preference: [0],
      attraction_preference: [0, 4],
      budget: 1200,
      extra_requirements: 'relaxed pace'
    })

    expect(request).toEqual({
      user_id: 'frontend-user',
      cities: ['Beijing'],
      start_date: '2026-06-20',
      end_date: '2026-06-21',
      preferences: {
        transport_preference: 1,
        accommodation_preference: [0],
        attraction_preference: [0, 4]
      },
      budget: 1200,
      extra_requirements: 'relaxed pace',
      session_id: undefined
    })
  })

  it('reuses saved session_id when creating later planning requests', () => {
    sessionStorage.setItem('zoey_session_id', 'session-123')

    const request = buildTripPlanRequest({
      user_id: 'frontend-user',
      city: 'Shanghai',
      start_date: '2026-07-01',
      end_date: '2026-07-01',
      transport_preference: 0,
      accommodation_preference: [],
      attraction_preference: [],
      budget: null,
      extra_requirements: ''
    })

    expect(request.session_id).toBe('session-123')
  })
})

describe('generateTripPlan', () => {
  beforeEach(() => {
    sessionStorage.clear()
    mocks.post.mockReset()
  })

  it('stores the returned TripPlan and resolved session_id', async () => {
    mocks.post.mockResolvedValue({
      data: {
        session_id: 'resolved-456',
        cities: ['Beijing'],
        start_date: '2026-06-20',
        end_date: '2026-06-20',
        days: [],
        weather_info: [],
        overall_suggestions: 'ok',
        generated_at: null
      }
    })

    const plan = await generateTripPlan({
      user_id: 'frontend-user',
      city: 'Beijing',
      start_date: '2026-06-20',
      end_date: '2026-06-20',
      transport_preference: 0,
      accommodation_preference: [0],
      attraction_preference: [0],
      budget: null,
      extra_requirements: ''
    })

    expect(plan.session_id).toBe('resolved-456')
    expect(sessionStorage.getItem('zoey_session_id')).toBe('resolved-456')
    expect(JSON.parse(sessionStorage.getItem('tripPlan') || '{}').cities).toEqual(['Beijing'])
  })
})
