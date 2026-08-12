import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Result from './Result'
import type { TripPlan } from '../types'

const plan: TripPlan = {
  session_id: 'session-1',
  cities: ['北京'],
  start_date: '2026-06-20',
  end_date: '2026-06-20',
  days: [
    {
      date: '2026-06-20',
      day_index: 0,
      city: '北京',
      description: '轻松游览历史文化景点',
      transportation: 'public_transport',
      accommodation: 'budget_hotel',
      hotel: null,
      attractions: [],
      meals: [],
      map_points: [
        {
          name: '故宫博物院',
          city: '北京市',
          location: { longitude: 116.397029, latitude: 39.917839 },
          day_index: 0,
          order_index: 0,
          point_type: 'attraction'
        }
      ],
      total_price: 60,
      route_distance_km: 5.2,
      route_duration_minutes: 40,
      transit_method: 'public_transport'
    }
  ],
  weather_info: [],
  overall_suggestions: '建议提前预约热门景点。',
  generated_at: null
}

describe('Result page', () => {
  it('renders the backend TripPlan contract directly', () => {
    sessionStorage.setItem('tripPlan', JSON.stringify(plan))

    render(
      <MemoryRouter>
        <Result />
      </MemoryRouter>
    )

    expect(screen.getByText('北京旅行计划')).toBeInTheDocument()
    expect(screen.getByText('当前会话已连接')).toBeInTheDocument()
    expect(screen.queryByText(/session-1/)).not.toBeInTheDocument()
    expect(screen.getByText('轻松游览历史文化景点')).toBeInTheDocument()
    expect(screen.getByText('故宫博物院')).toBeInTheDocument()
    expect(screen.getByText('¥60')).toBeInTheDocument()
  })
})
