# Schemas 设计

这份文档定义 ZoeyAgent 的数据合同。旅行规划系统会在前端、FastAPI、LangGraph、Amap MCP、LLM 和长期记忆之间传递数据。如果这些地方都使用松散 dict，字段会很快失控。因此项目使用 Pydantic 模型来约束输入、输出和关键内部状态。

这份文档的目标不是罗列所有字段，而是解释每一层 schema 为什么存在、负责什么边界，以及当前 MVP 哪些字段是严格要求，哪些字段是为后续能力预留。

## 背景

前端提交的旅行规划输入包括：

- 目的地城市。
- 开始和结束日期。
- 前端枚举索引形式的偏好。
- 预算。
- 交通偏好。
- 住宿偏好。
- 额外要求。
- 可选 `session_id`。

后端接收 `TripPlanRequest`，运行 LangGraph agents workflow，最终返回 `TripPlan`。前端结果页需要用它展示：

- 行程概览。
- 每日行程。
- 每日地图点。
- 酒店推荐。
- 天气信息。
- 餐食建议。
- 每日价格。
- 可编辑景点卡片。

因此响应必须是 day-centric 的结构化数据，而不是一段自然语言。

## 设计原则

- 外部 API 模型和关键内部 graph 合同都使用 Pydantic。
- provider response 要尽早归一化，不把 raw Amap response 传给 Planner。
- 使用领域模型表达真实概念，例如 `Location`、`Attraction`、`Hotel`、`DayPlan`。
- 前端请求使用 enum index，后端内部使用英文 enum value。
- provider 返回的名称、地址、城市和描述尽量保持原样。
- `MapPoint.location` 必须有坐标；没有坐标的对象不能生成 map point。
- meal 能力当前 deferred，不把每日三餐作为最终 validation 的硬要求。
- 公共 API schema 和 graph/internal schema 分层管理。

## 模型分层

```text
API models:
  TripPlanRequest
  TripPlan
  TripRecalculateRequest

Domain models:
  Location
  Attraction
  Hotel
  Meal
  WeatherInfo
  MapPoint
  DayPlan

Graph/internal models:
  NormalizedTripRequest
  ContextPacket
  ContextConfig
  ContextProfile
  PromptTemplateSpec
  LLMNodeSpec
  SearchQuality
  AttractionSearchResult
  HotelSearchResult
  MemoryCandidate
  WorkingMemoryMaintenanceResult
  TravelPlanState
```

## API Models

### Preference Enums

前端偏好使用整数索引，后端在归一化阶段转换成英文值。

```text
transport_preference:
  0 = public_transport
  1 = driving

accommodation_preference:
  0 = budget_hotel
  1 = mid_level_hotel
  2 = five_star_hotel

attraction_preference:
  0 = history_culture
  1 = nature
  2 = food
  3 = shopping
  4 = art
  5 = leisure
```

这样做的原因是前端可以用整数绑定 UI 控件，而 LLM 和 graph 内部更适合使用语义明确的英文字符串。

### TripPreferencesInput

```python
class TripPreferencesInput(BaseModel):
    transport_preference: TransportPreference
    accommodation_preference: list[AccommodationPreference] = []
    attraction_preference: list[AttractionPreference] = []
```

设计说明：

- `transport_preference` 是单选。
- `accommodation_preference` 是多选。
- `attraction_preference` 是多选。
- 前端传 index。
- graph 内部使用英文值。

### TripPlanRequest

`TripPlanRequest` 是 `POST /api/trip/plan` 的公开输入模型，表示前端表单。

```python
class TripPlanRequest(BaseModel):
    user_id: str = "default_user"
    cities: list[str]
    start_date: date
    end_date: date
    preferences: TripPreferencesInput
    budget: int | None = None
    extra_requirements: str = ""
    session_id: str | None = None
```

设计说明：

- `cities` 必须是非空列表。
- 当前 Amap-backed 实现要求 provider-facing 城市使用中文名，例如 `["北京"]`。
- `start_date` 和 `end_date` 是真实日期，不是自由文本。
- `budget` 如果提供，必须非负。
- `session_id` 首次请求可省略；后端会生成 resolved session id。
- 后续同一 planning session 应复用前端保存的 `session_id`。
- `extra_requirements` 可能很长，进入 prompt 前需要由 ContextAssembler 做预算控制。

### TripPlan

`TripPlan` 是 `POST /api/trip/plan` 的公开响应模型。前端直接渲染它。

```python
class TripPlan(BaseModel):
    session_id: str
    cities: list[str]
    start_date: date
    end_date: date
    days: list[DayPlan]
    weather_info: list[WeatherInfo]
    overall_suggestions: str
    generated_at: str | None = None
```

设计说明：

- `TripPlan.session_id` 必须返回 resolved session id。
- `TripPlan` 不包含 top-level `budget`。
- `TripPlan` 不包含 top-level `map_points`。
- 每天自己的地图点放在 `DayPlan.map_points`。
- 前端总价通过求和 `days[*].total_price` 得到。
- 多城市场景下，`DayPlan`、`WeatherInfo` 和 POI-like records 都应带 `city`。

### TripRecalculateRequest

重算接口已经预留，但完整实现 deferred。

```python
class TripRecalculateRequest(BaseModel):
    user_id: str
    session_id: str | None = None
    trip_plan: TripPlan
    edit_reason: str | None = None
```

未来用途：

- 删除或重排景点后重新计算每日价格。
- 重新生成 map points。
- 重新计算 route summary。
- 触发局部 replanning。

## Domain Models

### Location

```python
class Location(BaseModel):
    longitude: float
    latitude: float
```

经度范围是 `-180` 到 `180`，纬度范围是 `-90` 到 `90`。

Amap 可能返回 `"116.397128,39.916527"` 这样的字符串，也可能在 detail/geocode 中返回不同字段。工具层必须统一归一化成 `Location(longitude=..., latitude=...)`。

### Attraction

```python
class Attraction(BaseModel):
    name: str
    city: str | None = None
    address: str = ""
    location: Location | None = None
    visit_duration: int = 90
    description: str = ""
    category: str = "attraction"
    rating: float | None = None
    image_url: str | None = None
    ticket_price: int = 0
    poi_id: str | None = None
    order_index: int | None = None
    source: str | None = None
```

设计说明：

- `location` 在模型层可选，因为 provider 可能返回不完整 POI。
- 如果景点进入可渲染行程，工具层应尽量通过 detail/geocode 补坐标。
- 只有带有效坐标的景点才能生成 `MapPoint`。
- `image_url` 是未来图片 enrichment 的预留字段，MVP 可以为 `null`。

### Hotel

```python
class Hotel(BaseModel):
    name: str
    city: str | None = None
    address: str = ""
    location: Location | None = None
    price_range: str = ""
    rating: float | None = None
    distance: str = ""
    type: str = ""
    estimated_cost: int = 0
    poi_id: str | None = None
    distance_to_main_area_km: float | None = None
    estimated_travel_time_minutes: int | None = None
    transit_method: str | None = None
    source: str | None = None
```

设计说明：

- Amap POI 只能提供候选酒店，不能确认真实房态。
- `estimated_cost` 是估算，不是真实可预订价格。
- 路线字段只保存 summary signals，例如距离、耗时和交通方式。
- 不保存完整导航步骤。

### Meal

```python
MealType = Literal["breakfast", "lunch", "dinner"]

class Meal(BaseModel):
    type: MealType
    name: str
    city: str | None = None
    address: str | None = None
    location: Location | None = None
    description: str | None = None
    estimated_cost: int = 0
```

设计说明：

- `Meal.type` 仍然限制为 `breakfast`、`lunch`、`dinner`。
- 但当前 MVP 没有真实 meal search。
- `DayPlan.meals` 可以为空，也可以包含简单建议。
- `ValidateTripPlanNode` 当前不强制每天必须有三餐。
- 不应为了凑三餐而编造真实餐厅。

### WeatherInfo

```python
class WeatherInfo(BaseModel):
    city: str
    date: date
    day_weather: str
    night_weather: str = ""
    day_temp: int
    night_temp: int
    wind_direction: str = ""
    wind_power: str = ""
```

设计说明：

- 天气记录必须带 `city`。
- provider 可能返回 `"28℃"`、`"18°C"` 或 `"30°"`，工具层或 validator 应转成整数。
- 如果 provider 只返回近期天气，不应伪造远期天气。

### MapPoint

```python
class MapPoint(BaseModel):
    name: str
    city: str | None = None
    location: Location
    day_index: int | None = None
    order_index: int | None = None
    point_type: str = "attraction"
```

`MapPoint.location` 是必填，因为这是前端地图渲染合同。没有坐标的景点、酒店或餐食可以保留在对应列表里，但不能生成 map point。

### DayPlan

```python
class DayPlan(BaseModel):
    date: date
    day_index: int
    city: str
    description: str
    transportation: str
    accommodation: str
    hotel: Hotel | None = None
    attractions: list[Attraction] = []
    meals: list[Meal] = []
    map_points: list[MapPoint] = []
    total_price: int = 0
    route_distance_km: float | None = None
    route_duration_minutes: int | None = None
    transit_method: str | None = None
```

设计说明：

- `DayPlan` 是前端渲染每日行程的基本单位。
- `map_points` 放在 day 内部。
- `total_price` 是每日价格汇总。
- route fields 是轻量路线摘要。
- 完整路线说明 deferred。

## Graph/Internal Models

### NormalizedTripRequest

`NormalizedTripRequest` 是 graph 内部使用的请求模型。

```python
class NormalizedTripRequest(BaseModel):
    user_id: str
    cities: list[str]
    start_date: date
    end_date: date
    days_count: int
    transport_preference: str
    accommodation_preferences: list[str]
    attraction_preferences: list[str]
    budget: int | None = None
    extra_requirements: str = ""
    session_id: str
```

和 `TripPlanRequest` 的区别是：

- `days_count` 已计算。
- enum index 已转英文值。
- `session_id` 已解析且非空。
- 城市名仍保留 provider-facing 原文。

### SearchQuality

```python
class SearchQuality(BaseModel):
    enough_results: bool
    result_count: int = 0
    reason: str = ""
    retry_suggested: bool = False
    next_keywords: list[str] = []
```

`SearchQuality` 用于 specialist 子图判断是否 retry。它让搜索质量成为结构化信号，而不是藏在自然语言日志里。

### AttractionSearchResult

```python
class AttractionSearchResult(BaseModel):
    attractions: list[Attraction] = []
    search_keywords: list[str] = []
    step_observations: list[str] = []
    quality: SearchQuality | None = None
```

### HotelSearchResult

```python
class HotelSearchResult(BaseModel):
    selected_hotel: Hotel | None = None
    candidate_hotels: list[Hotel] = []
    search_areas: list[str] = []
    ranking_reasons: list[str] = []
    step_observations: list[str] = []
    quality: SearchQuality | None = None
```

设计说明：

- `candidate_hotels` 是 POI 候选，不是真实库存。
- `selected_hotel` 是给 Planner 的首选推荐。
- 其他候选可以进入 working memory/tool observations。

### ContextPacket

```python
class ContextPacket(BaseModel):
    content: str
    timestamp: datetime
    token_count: int
    relevance_score: float = 0.5
    recency_score: float = 0.5
    importance: float = 0.5
    confidence: float = 0.5
    source: str
    metadata: dict = {}
```

`ContextPacket` 是 `ContextAssemblyNode` 的候选上下文单位。

### ContextConfig / ContextProfile

`ContextConfig` 控制 token budget、打分权重和压缩开关。  
`ContextProfile` 控制不同 LLM 节点允许接收哪些上下文来源。

常见 profile：

```text
global_planner
repair_replan
attraction_search_plan
attraction_search_action
hotel_search_plan
hotel_search_action
```

### PromptTemplateSpec / LLMNodeSpec

这些 schema 用来描述 LLM 节点的 prompt 配置：

```text
PromptTemplateSpec:
  template_name
  role
  task
  input_fields
  allowed_tools
  output_schema_name

LLMNodeSpec:
  node_name
  context_profile
  prompt_template
  output_schema_name
```

它们的价值是把 prompt 调用配置化，避免 prompt、输出 schema 和上下文选择逻辑散落在代码中。

### MemoryCandidate

```python
MemoryTarget = Literal["semantic", "episodic", "discard"]

class MemoryCandidate(BaseModel):
    target: MemoryTarget
    text: str
    reason: str
    confidence: float = 0.5
    metadata: dict = {}
```

`MemoryCandidate` 是 working memory overflow 和 final valid plan 抽取长期记忆时的中间模型。

### WorkingMemoryMaintenanceResult

```python
class WorkingMemoryMaintenanceResult(BaseModel):
    retained_messages: list = []
    extracted_candidates: list[MemoryCandidate] = []
    dropped_count: int = 0
```

## TravelPlanState

`TravelPlanState` 是 LangGraph 的共享状态。它可以是 TypedDict，但字段应尽量使用 Pydantic 模型。

```python
class TravelPlanState(TypedDict):
    request: TripPlanRequest
    normalized_request: NormalizedTripRequest
    working_messages: list
    trip_draft: dict
    tool_observations: list
    semantic_memories: list
    episodic_memories: list
    memory_candidates: list[MemoryCandidate]
    context_packets: list[ContextPacket]
    planner_context: str
    attraction_search_result: AttractionSearchResult
    attractions: list[Attraction]
    hotel_search_result: HotelSearchResult
    hotels: list[Hotel]
    weather_info: list[WeatherInfo]
    trip_plan: TripPlan | None
    validation_errors: list[str]
    retry_count: int
```

## Validation Strategy

系统在四个边界做校验：

1. API input：FastAPI 校验 `TripPlanRequest`。
2. Tool normalization：Amap response 转成 `Attraction`、`Hotel`、`WeatherInfo`。
3. LLM output：Planner 输出解析成 `TripPlan`。
4. Final response：`ValidateTripPlanNode` 做业务校验。

当前 `ValidateTripPlanNode` 应校验：

- `TripPlan.session_id` 非空。
- 日期数量和请求一致。
- 每天 `day_index` 正确。
- 每天 `total_price >= 0`。
- 每天的 map points 属于对应 day。
- 不需要 top-level `budget`。
- 不需要 top-level `map_points`。
- 不输出完整路线说明。
- provider text 保持原样。
- 不强制每日三餐。

如果校验失败，graph 会根据 retry 计数进入 repair 或 fallback。

## 小结

schema 设计遵循一条清晰链路：

```text
Location
  -> Attraction / Hotel / Meal
  -> DayPlan
  -> TripPlan
```

同时，它为 LangGraph 和记忆系统补充了内部合同：

```text
TripPlanRequest
  -> NormalizedTripRequest
  -> TravelPlanState
  -> SearchResult / ContextPacket / MemoryCandidate
  -> TripPlan
```

最终目标是：每个节点都知道自己接收什么、返回什么、何时校验，以及这些数据如何被前端使用。
