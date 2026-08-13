# 示例工作流：杭州自驾旅行规划

这个示例用一条杭州自驾请求，串起当前 ZoeyAgent 的主 graph 流程。它展示每个节点负责什么、可能调用哪些工具、会把哪些结果写回 state，以及长期记忆在什么时候才会保存。

需要注意的是，这份文档描述的是当前实现和设计对齐后的工作流。景点和酒店搜索是 bounded ReAct 风格的 specialist 子图；主流程由 LangGraph 编排；Planner 生成的结果必须先通过 `ValidateTripPlanNode`，通过后才会进入 `SaveMemoryNode`。

## 用户请求

```text
目的地城市：杭州
开始日期：2026-07-05
结束日期：2026-07-08
交通偏好：自驾
住宿偏好：经济型酒店
景点偏好：自然风光、购物
额外要求：早上 11 点开始行程，晚上 10 点结束行程
```

对应的 HTTP 请求形状如下：

```json
{
  "user_id": "example-user-001",
  "cities": ["杭州"],
  "start_date": "2026-07-05",
  "end_date": "2026-07-08",
  "preferences": {
    "transport_preference": 1,
    "accommodation_preference": [0],
    "attraction_preference": [1, 3]
  },
  "budget": 3000,
  "extra_requirements": "早上11点开始行程，晚上10点结束行程"
}
```

第一次规划时，`session_id` 可以省略。后端会生成一个新的 `session_id`，并在最终的 `TripPlan.session_id` 中返回。后续如果前端继续同一个 planning session，就应该把这个 `session_id` 带回来，让 LangGraph 能用同一个 `thread_id` 恢复当前会话状态。

偏好枚举含义：

```text
transport_preference = 1 -> driving
accommodation_preference = 0 -> budget_hotel
attraction_preference = 1 -> nature
attraction_preference = 3 -> shopping
```

这条请求的预期旅行天数是 4 天。

## Step 1：InitializeWorkingState

这个节点负责创建一次 graph run 的初始运行现场。它会把当前请求放入 `TravelPlanState`，并准备 working memory、tool observations、trip draft 等字段。

它不会调用外部工具，也不会写长期记忆。此时只是在当前 session 的工作状态里记录“这次请求开始了”。

预期结果：

```text
TravelPlanState
- request 已写入
- working_messages 已初始化
- tool_observations 已初始化
- trip_plan 暂时为空
```

`session_id` 在进入 graph 前已经被解析完成，并作为 LangGraph 的 `thread_id` 使用。

## Step 2：LoadMemoryNode

这个节点负责在规划前召回长期记忆。它会根据 `user_id` 查询 semantic memories 和 episodic memories，寻找和当前旅行请求相关的偏好或历史决策。

例如，如果用户过去多次选择自驾、偏好经济型酒店、喜欢自然风光和购物区域，这些信息就可能被召回，写入 `TravelPlanState`。

可能使用的能力：

```text
PostgresStore.search(...)
pgvector 语义检索
Ollama bge-m3 embedding
```

预期结果：

```text
semantic_memories
episodic_memories
```

这个节点只读长期记忆，不写入新的长期记忆。

## Step 3：NormalizeRequestNode

前端提交的是用户表单，graph 节点需要的是更容易消费的内部结构。因此这个节点会把请求归一化。

它会做几件事：

- 校验日期范围和旅行天数。
- 把前端枚举索引转换成英文枚举值。
- 保留 provider-facing 城市名，例如 `杭州`。
- 保留 `budget` 和较长的 `extra_requirements`。
- 保证内部请求拥有非空 `session_id`。

预期归一化结果：

```text
cities = ["杭州"]
days_count = 4
transport_preference = "driving"
accommodation_preferences = ["budget_hotel"]
attraction_preferences = ["nature", "shopping"]
budget = 3000
extra_requirements = "早上11点开始行程，晚上10点结束行程"
session_id = resolved session id
```

这个节点不调用外部工具，也不写长期记忆。它只把 `normalized_request` 写入 graph state。

## Step 4：AttractionSearchSubgraph

景点搜索子图负责找到符合偏好的杭州景点候选。它不是最终 Planner，而是一个局部搜索专家：LLM 负责局部 plan/action 决策，Amap service 负责真实工具调用，规则 evaluator 负责质量判断、去重、排序和 retry。

对于这个请求，子图会围绕 `nature` 和 `shopping` 生成搜索意图，例如：

```text
杭州 自然风光
西湖
西溪湿地
杭州 购物中心
湖滨银泰
武林商圈
```

### 4.1 局部计划

子图首先让 LLM 生成局部搜索计划。这个计划只服务景点搜索，不读取完整 planner context，也不生成最终行程。

预期输出：

```text
AttractionSearchPlan
- steps
- keywords
- city
- rationale
```

如果 LLM 不可用或输出不符合 schema，子图不会让整个 graph 崩溃，而是记录 observation，并返回 best-effort 空结果或已有候选。

### 4.2 受限 action 和 Amap 工具调用

每轮搜索时，LLM 只能输出受限 action，例如：

```text
tool_name = "search_attractions"
city = "杭州"
keywords = "杭州 自然风光"
```

executor 不直接调用 raw MCP，而是调用项目内部的 `AmapMCPService.search_attractions()`。service 内部会根据需要调用真实 MCP 工具，并把 provider 响应归一化为 `Attraction`。

可能使用的 MCP 工具：

```text
maps_text_search
maps_search_detail
maps_geo
```

其中 `maps_text_search` 用于搜索 POI，`maps_search_detail` 用于按 POI ID 补全详情和坐标，`maps_geo` 用于在 detail 仍缺少坐标时按城市和地址兜底补坐标。

### 4.3 质量评估和 retry

每轮工具调用后，子图会评估候选质量。评估重点包括：

- 候选数量是否足够。
- 去重后是否仍有有效结果。
- 是否有经纬度。
- 地址和城市是否可信。
- 是否匹配自然风光、购物等偏好。

如果结果质量不足，并且还没有超过 retry 上限，子图会把 observation 和 quality warning 放回 local scratchpad，让 LLM 选择下一轮 action。这样可以避免“一次搜索结果不好就直接放弃”。

预期候选示例：

```text
西湖
西溪国家湿地公园
灵隐寺周边自然景区
湖滨银泰 in77
武林商圈
杭州大厦
```

### 4.4 写回主 state

景点子图不会把完整 ReAct scratchpad 写回主 graph。它只写回压缩后的结构化结果和简短 observation。

预期输出：

```text
AttractionSearchResult
- attractions
- search_keywords
- step_observations
- quality

TravelPlanState.attractions
TravelPlanState.tool_observations
```

记忆行为：

- 搜索摘要会进入 working memory 或 tool observations。
- 不直接写 semantic memory 或 episodic memory。
- 后续只有通过 `SaveMemoryNode`，长期有价值的信息才会保存。

## Step 5：HotelSearchSubgraph

酒店搜索子图负责找到适合这次行程的酒店候选。它会读取景点搜索结果，因为酒店位置应该靠近主要景点、购物区域或交通方便的区域。

对于这个请求，`transport_preference = driving`，因此酒店搜索会额外关注自驾便利性，例如距离主区域的车程、停车场线索或周边道路便利性。

可能搜索 anchor：

```text
西湖附近
湖滨银泰附近
武林商圈
西溪湿地附近
晚餐或购物区域附近
```

### 5.1 局部计划

LLM 会基于景点候选、预算、交通方式和住宿偏好生成酒店搜索计划。这个计划只服务酒店搜索，不生成最终 `TripPlan`。

预期输出：

```text
HotelSearchPlan
- steps
- search_areas
- keywords
- rationale
```

### 5.2 受限 action 和工具调用

LLM 每轮只能选择受限 action，例如搜索某个区域的经济型酒店、切换 anchor，或者请求路线摘要。

executor 通过 `AmapMCPService.search_hotels()` 和 route summary helper 调用真实工具。Planner 不直接接触 raw Amap response。

可能使用的 MCP 工具：

```text
maps_text_search
maps_search_detail
maps_geo
maps_direction_walking_by_address
maps_direction_driving_by_address
maps_direction_transit_integrated_by_address
```

路线工具只用于 summary signals：

```text
distance
estimated time
transport mode
```

不返回：

```text
完整驾车路线
逐步导航说明
公交站点数量
换乘细节
turn-by-turn instructions
```

### 5.3 质量评估和排序

酒店 evaluator 会检查候选是否足够好：

- 是否是住宿类 POI。
- 是否匹配 `budget_hotel`。
- 是否有坐标。
- 到主要景点或购物区域的距离/耗时是否可接受。
- 是否有评分或其他质量线索。
- 自驾场景下是否有停车便利性线索。

需要明确的是，Amap POI 只能提供酒店候选，不能确认真实房态，也不能保证实时价格。因此输出应该被理解为 `candidate_hotels`，不是可直接预订的库存。

预期输出：

```text
HotelSearchResult
- selected_hotel
- candidate_hotels
- search_areas
- ranking_reasons
- step_observations
- quality

TravelPlanState.hotels
TravelPlanState.tool_observations
```

记忆行为：

- selected hotel 和候选摘要可以进入 working memory 或 tool observations。
- 不直接把所有候选酒店写入长期记忆。
- 最终如果用户选择、拒绝或稳定偏好明确，才可能由 `SaveMemoryNode` 抽取成长期记忆。

## Step 6：WeatherQueryNode

天气节点负责查询杭州天气。它是确定性工具节点，不需要 LLM，也不使用主 graph 的 `ContextAssemblyNode`。

调用工具：

```text
maps_weather
```

预期输出：

```text
list[WeatherInfo]
```

每条天气记录应包含：

```text
city
date
day_weather
night_weather
day_temp
night_temp
wind_direction
wind_power
```

需要注意的是，高德天气通常只返回近期预报。如果用户请求远期日期，系统不应该伪造天气；只能返回 provider 当前可用的数据，或在前端/说明中表达天气不可用。

天气结果写入 graph state，不写长期记忆。天气工具失败时，节点应记录结构化 observation，并让后续规划继续执行。

## Step 7：WorkingMemoryMaintenanceNode

这个节点负责维护当前 session 的 working memory。它会检查 working memory 是否超过容量上限，例如 50 条消息。

如果没有超限，就只保留当前 working memory。  
如果发生 overflow，会先把即将裁掉的旧内容交给 `MemoryExtractionService`，尝试抽取长期记忆候选，再保留最新的工作上下文。

预期输出：

```text
WorkingMemoryMaintenanceResult
- retained_messages
- extracted_candidates
- dropped_count
```

记忆行为：

- 稳定偏好可能成为 semantic memory candidate。
- 具体历史决策可能成为 episodic memory candidate。
- 临时工具噪声会被 discard。

在这条示例请求中，通常不会触发 overflow。

## Step 8：ContextAssemblyNode

搜索和天气结果写回 state 后，主 graph 会进入上下文组装阶段。这个节点的职责不是调用工具，也不是生成行程，而是为 Planner 准备高质量上下文。

它会执行 GSSC：

```text
Gather    收集候选上下文
Select    按相关性、重要性和预算筛选
Structure 组织成稳定 prompt sections
Compress  超出 token budget 时压缩
```

输入来源包括：

- 原始请求
- 归一化请求
- semantic memories
- episodic memories
- attraction search result
- hotel search result
- weather info
- tool observations
- extra requirements
- validation errors，如果这是 repair 轮次

对于 Planner 来说，这条请求的重要上下文包括：

```text
城市：杭州
天数：4 天
交通方式：driving
住宿偏好：budget_hotel
景点偏好：nature + shopping
时间窗口：11:00 到 22:00
只能使用 route summary，不输出完整路线说明
图片 enrichment 暂时 deferred
餐食规划暂时 deferred，不要为了凑三餐编造真实餐厅
```

预期输出：

```text
planner_context
context_packets
```

## Step 9：PlannerNode

PlannerNode 是主 LLM 规划节点。它根据 `planner_context` 生成完整 `TripPlan` 草稿。

它会综合：

- 用户请求
- 长期记忆召回
- 景点候选
- 酒店候选
- 天气信息
- 预算和偏好
- 地图点和路线摘要
- extra requirements

预期输出结构：

```text
TripPlan
- session_id
- cities = ["杭州"]
- start_date = 2026-07-05
- end_date = 2026-07-08
- days = 4 个 DayPlan
- weather_info
- overall_suggestions
```

每个 `DayPlan` 应包含：

```text
date
day_index
city = 杭州
description
transportation = driving
accommodation = budget_hotel
hotel
attractions
meals
map_points
total_price
route_distance_km
route_duration_minutes
transit_method = driving
```

当前 meal 能力仍是 deferred。也就是说，`meals` 可以为空，也可以只包含 Planner 或 fallback 给出的简单建议；系统不应该为了凑三餐而编造真实餐厅。

不应输出：

```text
完整路线说明
公交线路细节
站点数量
换乘细节
逐步导航说明
raw Amap response
```

`image_url` 可以是 `null`。

## Step 10：ValidateTripPlanNode

这个节点负责在结果出 API 前做业务校验。LLM 生成的是草稿，只有通过校验后才可以返回给前端。

当前校验重点包括：

- 响应可以被解析为合法 `TripPlan`。
- 天数和请求日期范围一致。
- 每天的 `day_index` 正确。
- 每天 `total_price >= 0`。
- 每天拥有自己的 `map_points`，或至少能通过酒店/景点/餐食坐标生成地图点。
- `map_points.day_index` 和所属 `DayPlan.day_index` 不冲突。
- 不出现 top-level `budget`。
- 不出现 top-level `map_points`。
- 不输出完整路线说明。
- provider text，例如 `杭州`、地址和 POI 名称，保持原样。

当前不强制校验每日三餐。餐食能力还没有接入真实 meal search，因此不能把“每天必须有 breakfast/lunch/dinner”作为出 API 的硬要求。

如果校验失败，graph 会把 validation errors 写回 state，并路由回 `ContextAssemblyNode` 和 `PlannerNode` 做 repair。超过 retry 上限后，进入 `FallbackNode`。

记忆行为：

- 这里不写长期记忆。
- 失败计划不会进入 long-term memory。

## Step 11：SaveMemoryNode

`SaveMemoryNode` 只在最终 `TripPlan` 校验成功后运行。它会从本轮 working memory、tool observations 和最终有效计划中抽取有长期价值的记忆候选。

可能抽取的 semantic memory：

```text
用户偏好自驾。
用户偏好经济型酒店。
用户喜欢自然风光和购物主题。
用户偏好 11 点左右开始行程。
自驾场景下，用户关注停车便利性。
```

可能抽取的 episodic memory：

```text
用户规划过一次 2026-07-05 到 2026-07-08 的杭州旅行。
这次行程主题是自然风光和购物。
这次行程选择了某个酒店作为推荐住宿。
这次行程保留了一些酒店候选作为备选。
```

不会保存：

```text
完整临时 POI 搜索结果
每一个酒店候选
raw Amap response
失败的 TripPlan 草稿
临时工具错误噪声
```

如果长期记忆未开启，`SaveMemoryNode` 可以跳过 store 写入，但仍应保持 graph 输出稳定。

## Step 12：FallbackNode

如果 Planner 多次 repair 仍然失败，graph 会进入 `FallbackNode`。它不会再依赖 LLM 生成自然规划，而是根据已有 state 里的景点、酒店、天气候选拼出一个保守可用的 `TripPlan`。

Fallback 的目标不是生成最漂亮的文案，而是保证 API 有可控输出：

- 使用已有 `attractions`。
- 使用已有 selected hotel。
- 使用已有 weather_info。
- 生成 day-centric `DayPlan`。
- 生成可渲染 map points。
- 不输出 raw provider response。
- 不进入无限 retry。

Fallback 输出仍然应该满足 `TripPlan` 合同。

## 最终输出形状

实际内容取决于 Amap 工具结果和 PlannerNode 生成。结构上应类似：

```json
{
  "session_id": "backend_or_frontend_resolved_session_id",
  "cities": ["杭州"],
  "start_date": "2026-07-05",
  "end_date": "2026-07-08",
  "days": [
    {
      "date": "2026-07-05",
      "day_index": 0,
      "city": "杭州",
      "description": "第 1 天在杭州安排自然风光和购物相关行程。",
      "transportation": "driving",
      "accommodation": "budget_hotel",
      "hotel": {
        "name": "示例酒店",
        "city": "杭州市",
        "address": "示例地址",
        "location": {
          "longitude": 120.0,
          "latitude": 30.0
        },
        "estimated_cost": 0,
        "source": "amap"
      },
      "attractions": [],
      "meals": [],
      "map_points": [],
      "total_price": 0,
      "route_distance_km": null,
      "route_duration_minutes": null,
      "transit_method": "driving"
    }
  ],
  "weather_info": [],
  "overall_suggestions": "...",
  "generated_at": null
}
```

前端只需要消费 `TripPlan`。它不需要知道 ReAct 子图的完整 scratchpad，也不需要理解 Amap raw response。后端的职责就是把工具、记忆和 LLM 生成过程整理成稳定、可验证、可渲染的响应合同。
