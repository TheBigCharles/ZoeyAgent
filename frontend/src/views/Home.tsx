import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, DatePicker, Form, Input, InputNumber, Select, Space, Typography, message } from 'antd'
import { CalendarDays, Hotel, MapPinned, Route, SendHorizontal, Sparkles } from 'lucide-react'
import dayjs from 'dayjs'
import { generateTripPlan, SESSION_STORAGE_KEY } from '../services/api'
import type { TripFormData } from '../types'

const { RangePicker } = DatePicker

const transportOptions = [
  { label: '公共交通', value: 0 },
  { label: '自驾', value: 1 }
]

const accommodationOptions = [
  { label: '经济型酒店', value: 0 },
  { label: '中档酒店', value: 1 },
  { label: '五星级酒店', value: 2 }
]

const attractionOptions = [
  { label: '历史文化', value: 0 },
  { label: '自然风光', value: 1 },
  { label: '美食', value: 2 },
  { label: '购物', value: 3 },
  { label: '艺术', value: 4 },
  { label: '休闲', value: 5 }
]

interface HomeFormValues {
  user_id: string
  city: string
  dates: [dayjs.Dayjs, dayjs.Dayjs]
  transport_preference: number
  accommodation_preference: number[]
  attraction_preference: number[]
  budget?: number | null
  extra_requirements?: string
}

export default function Home() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm<HomeFormValues>()
  const savedSessionId = sessionStorage.getItem(SESSION_STORAGE_KEY)

  const handleFinish = async (values: HomeFormValues) => {
    const [startDate, endDate] = values.dates
    const request: TripFormData = {
      user_id: values.user_id || 'frontend_user',
      city: values.city.trim(),
      start_date: startDate.format('YYYY-MM-DD'),
      end_date: endDate.format('YYYY-MM-DD'),
      transport_preference: values.transport_preference,
      accommodation_preference: values.accommodation_preference || [],
      attraction_preference: values.attraction_preference || [],
      budget: values.budget ?? null,
      extra_requirements: values.extra_requirements || ''
    }

    setLoading(true)
    try {
      await generateTripPlan(request)
      message.success('旅行计划已生成')
      navigate('/result')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '生成失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="page-grid">
      <div className="intro-panel">
        <div className="section-label">
          <Sparkles size={16} aria-hidden />
          AI travel planner
        </div>
        <Typography.Title level={1}>生成结构化旅行计划</Typography.Title>
        <Typography.Paragraph>
          输入城市、日期、预算和偏好，后端会用真实地图、天气、酒店候选和记忆召回生成可渲染的 TripPlan。
        </Typography.Paragraph>
        {savedSessionId ? (
          <Alert
            type="info"
            showIcon
            message="已找到当前 planning session"
            description="后续请求会继续使用当前会话。"
          />
        ) : null}
      </div>

      <div className="form-surface">
        <Form<HomeFormValues>
          form={form}
          layout="vertical"
          onFinish={handleFinish}
          initialValues={{
            user_id: 'frontend-user',
            city: '北京',
            dates: [dayjs('2026-12-25'), dayjs('2026-12-25')],
            transport_preference: 0,
            accommodation_preference: [0],
            attraction_preference: [0],
            budget: 1200,
            extra_requirements: '中文输出；一天轻松行程；优先历史文化景点。'
          }}
        >
          <div className="form-section-title">
            <MapPinned size={18} aria-hidden />
            行程基础
          </div>
          <Form.Item name="user_id" label="用户 ID" rules={[{ required: true, message: '请输入用户 ID' }]}>
            <Input placeholder="frontend-user" />
          </Form.Item>
          <Form.Item name="city" label="目的地城市" rules={[{ required: true, message: '请输入中文城市名，例如 北京' }]}>
            <Input placeholder="北京" />
          </Form.Item>
          <Form.Item name="dates" label="出行日期" rules={[{ required: true, message: '请选择日期范围' }]}>
            <RangePicker className="full-width" />
          </Form.Item>

          <div className="form-section-title">
            <Route size={18} aria-hidden />
            偏好设置
          </div>
          <Form.Item name="transport_preference" label="交通方式">
            <Select options={transportOptions} />
          </Form.Item>
          <Form.Item name="accommodation_preference" label="住宿偏好">
            <Select mode="multiple" options={accommodationOptions} />
          </Form.Item>
          <Form.Item name="attraction_preference" label="景点偏好">
            <Select mode="multiple" options={attractionOptions} />
          </Form.Item>
          <Form.Item name="budget" label="预算">
            <InputNumber className="full-width" min={0} placeholder="可选，例如 1200" />
          </Form.Item>

          <div className="form-section-title">
            <Hotel size={18} aria-hidden />
            额外要求
          </div>
          <Form.Item name="extra_requirements" label="补充说明">
            <Input.TextArea rows={4} placeholder="例如：不要太赶，优先历史文化景点。" />
          </Form.Item>

          <Space className="form-actions">
            <Button htmlType="submit" type="primary" size="large" loading={loading} icon={<SendHorizontal size={18} />}>
              生成旅行计划
            </Button>
            <Button
              size="large"
              icon={<CalendarDays size={18} />}
              onClick={() => navigate('/result')}
            >
              查看上次结果
            </Button>
          </Space>
        </Form>
      </div>
    </section>
  )
}
