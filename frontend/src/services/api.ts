import axios from 'axios'
import type { TripFormData, TripPlan, TripPlanRequest } from '../types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''
const SESSION_STORAGE_KEY = 'zoey_session_id'
const TRIP_PLAN_STORAGE_KEY = 'tripPlan'

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 180000,
  headers: {
    'Content-Type': 'application/json'
  }
})

export function buildTripPlanRequest(formData: TripFormData): TripPlanRequest {
  const savedSessionId = sessionStorage.getItem(SESSION_STORAGE_KEY) || undefined

  return {
    user_id: formData.user_id,
    cities: [formData.city.trim()],
    start_date: formData.start_date,
    end_date: formData.end_date,
    preferences: {
      transport_preference: formData.transport_preference,
      accommodation_preference: formData.accommodation_preference,
      attraction_preference: formData.attraction_preference
    },
    budget: formData.budget,
    extra_requirements: formData.extra_requirements.trim(),
    session_id: savedSessionId
  }
}

export async function generateTripPlan(formData: TripFormData): Promise<TripPlan> {
  try {
    const request = buildTripPlanRequest(formData)
    const response = await apiClient.post<TripPlan>('/api/trip/plan', request)
    const tripPlan = response.data

    sessionStorage.setItem(SESSION_STORAGE_KEY, tripPlan.session_id)
    sessionStorage.setItem(TRIP_PLAN_STORAGE_KEY, JSON.stringify(tripPlan))

    return tripPlan
  } catch (error: unknown) {
    if (axios.isAxiosError(error)) {
      const payload = error.response?.data
      const message =
        payload?.error?.message ||
        payload?.detail?.[0]?.msg ||
        payload?.detail ||
        error.message
      throw new Error(message)
    }
    throw error
  }
}

export async function healthCheck(): Promise<{ status: string }> {
  const response = await apiClient.get<{ status: string }>('/health')
  return response.data
}

export { SESSION_STORAGE_KEY, TRIP_PLAN_STORAGE_KEY }
export default apiClient
