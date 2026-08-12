export interface Location {
  longitude: number
  latitude: number
}

export interface Attraction {
  name: string
  city?: string | null
  address: string
  location?: Location | null
  visit_duration: number
  description: string
  category: string
  rating?: number | null
  image_url?: string | null
  ticket_price: number
  poi_id?: string | null
  order_index?: number | null
  source?: string | null
}

export interface Hotel {
  name: string
  city?: string | null
  address: string
  location?: Location | null
  price_range: string
  rating?: number | null
  distance: string
  type: string
  estimated_cost: number
  poi_id?: string | null
  distance_to_main_area_km?: number | null
  estimated_travel_time_minutes?: number | null
  transit_method?: string | null
  source?: string | null
}

export type MealType = 'breakfast' | 'lunch' | 'dinner'

export interface Meal {
  type: MealType
  name: string
  city?: string | null
  address?: string | null
  location?: Location | null
  description?: string | null
  estimated_cost: number
}

export interface MapPoint {
  name: string
  city?: string | null
  location: Location
  day_index?: number | null
  order_index?: number | null
  point_type: string
}

export interface DayPlan {
  date: string
  day_index: number
  city: string
  description: string
  transportation: string
  accommodation: string
  hotel?: Hotel | null
  attractions: Attraction[]
  meals: Meal[]
  map_points: MapPoint[]
  total_price: number
  route_distance_km?: number | null
  route_duration_minutes?: number | null
  transit_method?: string | null
}

export interface WeatherInfo {
  city: string
  date: string
  day_weather: string
  night_weather: string
  day_temp: number
  night_temp: number
  wind_direction: string
  wind_power: string
}

export interface TripPlan {
  session_id: string
  cities: string[]
  start_date: string
  end_date: string
  days: DayPlan[]
  weather_info: WeatherInfo[]
  overall_suggestions: string
  generated_at?: string | null
}

export interface TripPreferencesInput {
  transport_preference: number
  accommodation_preference: number[]
  attraction_preference: number[]
}

export interface TripPlanRequest {
  user_id: string
  cities: string[]
  start_date: string
  end_date: string
  preferences: TripPreferencesInput
  budget?: number | null
  extra_requirements: string
  session_id?: string
}

export interface TripFormData {
  user_id: string
  city: string
  start_date: string
  end_date: string
  transport_preference: number
  accommodation_preference: number[]
  attraction_preference: number[]
  budget: number | null
  extra_requirements: string
}
