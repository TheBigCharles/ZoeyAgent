import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Collapse, Descriptions, Empty, List, Space, Statistic, Tag, Typography } from 'antd'
import AMapLoader from '@amap/amap-jsapi-loader'
import { ArrowLeft, Building2, CloudSun, Download, MapPin, Route, WalletCards } from 'lucide-react'
import html2canvas from 'html2canvas'
import jsPDF from 'jspdf'
import { TRIP_PLAN_STORAGE_KEY } from '../services/api'
import type { DayPlan, MapPoint, TripPlan } from '../types'

function formatCities(cities: string[]) {
  return cities.join('、')
}

function collectMapPoints(days: DayPlan[]): MapPoint[] {
  return days.flatMap((day) => day.map_points || [])
}

function formatRoute(day: DayPlan) {
  const parts = []
  if (day.route_distance_km != null) parts.push(`${day.route_distance_km} km`)
  if (day.route_duration_minutes != null) parts.push(`${day.route_duration_minutes} 分钟`)
  return parts.length ? parts.join(' / ') : '暂无路线摘要'
}

export default function Result() {
  const navigate = useNavigate()
  const [tripPlan, setTripPlan] = useState<TripPlan | null>(null)
  const [mapStatus, setMapStatus] = useState('地图未加载')
  const exportRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<HTMLDivElement>(null)
  const mapPoints = useMemo(() => collectMapPoints(tripPlan?.days || []), [tripPlan])
  const totalPrice = useMemo(() => (tripPlan?.days || []).reduce((sum, day) => sum + day.total_price, 0), [tripPlan])

  useEffect(() => {
    const saved = sessionStorage.getItem(TRIP_PLAN_STORAGE_KEY)
    if (saved) {
      setTripPlan(JSON.parse(saved) as TripPlan)
    }
  }, [])

  useEffect(() => {
    if (!tripPlan || !mapRef.current || mapPoints.length === 0) return
    const key = import.meta.env.VITE_AMAP_WEB_JS_KEY
    if (!key) {
      setMapStatus('未配置 VITE_AMAP_WEB_JS_KEY，已显示坐标列表')
      return
    }

    let mounted = true
    let map: any

    AMapLoader.load({
      key,
      version: '2.0',
      plugins: ['AMap.Marker', 'AMap.Polyline']
    })
      .then((AMap) => {
        if (!mounted || !mapRef.current) return
        const first = mapPoints[0].location
        map = new AMap.Map(mapRef.current, {
          zoom: 12,
          center: [first.longitude, first.latitude]
        })
        const markers = mapPoints.map((point, index) =>
          new AMap.Marker({
            position: [point.location.longitude, point.location.latitude],
            title: point.name,
            label: {
              content: `${index + 1}`,
              offset: new AMap.Pixel(0, -28)
            }
          })
        )
        map.add(markers)
        map.setFitView(markers)
        setMapStatus('地图已加载')
      })
      .catch(() => setMapStatus('地图加载失败，已显示坐标列表'))

    return () => {
      mounted = false
      if (map) map.destroy()
    }
  }, [mapPoints, tripPlan])

  const exportImage = async () => {
    if (!exportRef.current || !tripPlan) return
    const canvas = await html2canvas(exportRef.current, { backgroundColor: '#f6f8fb', scale: 2 })
    const link = document.createElement('a')
    link.download = `travel-plan-${formatCities(tripPlan.cities)}.png`
    link.href = canvas.toDataURL('image/png')
    link.click()
  }

  const exportPdf = async () => {
    if (!exportRef.current || !tripPlan) return
    const canvas = await html2canvas(exportRef.current, { backgroundColor: '#f6f8fb', scale: 2 })
    const pdf = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })
    const imgData = canvas.toDataURL('image/png')
    const imgWidth = 210
    const imgHeight = (canvas.height * imgWidth) / canvas.width
    pdf.addImage(imgData, 'PNG', 0, 0, imgWidth, imgHeight)
    pdf.save(`travel-plan-${formatCities(tripPlan.cities)}.pdf`)
  }

  if (!tripPlan) {
    return (
      <div className="empty-state">
        <Empty description="还没有旅行计划">
          <Button type="primary" onClick={() => navigate('/')}>返回创建计划</Button>
        </Empty>
      </div>
    )
  }

  return (
    <section className="result-page">
      <div className="result-toolbar">
        <Button icon={<ArrowLeft size={18} />} onClick={() => navigate('/')}>返回</Button>
        <Space>
          <Button icon={<Download size={18} />} onClick={exportImage}>导出图片</Button>
          <Button icon={<Download size={18} />} onClick={exportPdf}>导出 PDF</Button>
        </Space>
      </div>

      <div ref={exportRef} className="result-content">
        <div className="result-hero">
          <div>
            <Typography.Title level={1}>{formatCities(tripPlan.cities)}旅行计划</Typography.Title>
            <Typography.Text>当前会话已连接</Typography.Text>
          </div>
          <div className="hero-stats">
            <Statistic title="天数" value={tripPlan.days.length} />
            <Statistic title="预计总价" value={totalPrice} prefix="¥" />
          </div>
        </div>

        <Alert className="suggestion" type="success" showIcon message={tripPlan.overall_suggestions} />

        <div className="result-grid">
          <div className="map-panel">
            <div className="panel-title">
              <MapPin size={18} aria-hidden />
              地图点
            </div>
            <div ref={mapRef} className="map-canvas">
              <span>{mapStatus}</span>
            </div>
            <List
              size="small"
              dataSource={mapPoints}
              renderItem={(point, index) => (
                <List.Item>
                  <Space>
                    <Tag>{index + 1}</Tag>
                    <span>{point.name}</span>
                    <Typography.Text type="secondary">{point.point_type}</Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
          </div>

          <div className="day-panel">
            <Collapse
              defaultActiveKey={tripPlan.days.map((day) => String(day.day_index))}
              items={tripPlan.days.map((day) => ({
                key: String(day.day_index),
                label: `第 ${day.day_index + 1} 天 · ${day.city} · ${day.date}`,
                children: <DayCard day={day} />
              }))}
            />
          </div>
        </div>

        {tripPlan.weather_info.length ? (
          <div className="weather-grid">
            {tripPlan.weather_info.map((weather) => (
              <div className="weather-card" key={`${weather.city}-${weather.date}`}>
                <CloudSun size={20} aria-hidden />
                <strong>{weather.city} {weather.date}</strong>
                <span>白天 {weather.day_weather} {weather.day_temp}°C</span>
                <span>夜间 {weather.night_weather} {weather.night_temp}°C</span>
                <span>{weather.wind_direction}风 {weather.wind_power}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  )
}

function DayCard({ day }: { day: DayPlan }) {
  return (
    <div className="day-card">
      <Typography.Paragraph>{day.description}</Typography.Paragraph>
      <Space wrap>
        <Tag icon={<Route size={14} />}>{day.transportation}</Tag>
        <Tag icon={<Building2 size={14} />}>{day.accommodation}</Tag>
        <Tag icon={<WalletCards size={14} />}>¥{day.total_price}</Tag>
        <Tag>{formatRoute(day)}</Tag>
      </Space>

      {day.hotel ? (
        <Descriptions className="compact-descriptions" size="small" column={1} bordered>
          <Descriptions.Item label="住宿">{day.hotel.name}</Descriptions.Item>
          <Descriptions.Item label="地址">{day.hotel.address}</Descriptions.Item>
          <Descriptions.Item label="评分">{day.hotel.rating ?? '暂无'}</Descriptions.Item>
        </Descriptions>
      ) : null}

      <List
        header="景点"
        dataSource={day.attractions}
        renderItem={(attraction) => (
          <List.Item>
            <List.Item.Meta
              title={attraction.name}
              description={`${attraction.address || '暂无地址'} · ${attraction.visit_duration} 分钟 · ${attraction.category}`}
            />
          </List.Item>
        )}
      />

      {day.meals.length ? (
        <List
          header="餐食建议"
          dataSource={day.meals}
          renderItem={(meal) => (
            <List.Item>
              <List.Item.Meta title={`${meal.type}: ${meal.name}`} description={meal.description || meal.city || ''} />
            </List.Item>
          )}
        />
      ) : null}
    </div>
  )
}
