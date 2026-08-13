# 后端设计

这份文档说明 ZoeyAgent 后端服务的设计。后端不是一个简单的 LLM 转发层，而是一个自托管的 FastAPI 应用：它接收结构化旅行请求，解析 `session_id`，运行 LangGraph 旅行规划流程，管理短期和长期记忆，调用 Amap MCP 与 LLM 服务，并返回经过 Pydantic 校验的 `TripPlan`。

当前项目已经包含 React 前端和 Docker 本地运行环境。不过这份文档只聚焦后端边界：API 如何进入 graph，依赖如何初始化，错误如何收口，记忆和外部工具如何接入。

## 背景

旅行规划请求从前端或终端进入后端。用户提供城市、日期、预算、交通偏好、住宿偏好、景点偏好和额外要求。后端需要做的事情并不只是把这些字段拼进 prompt，而是要完成以下工作：

- 用 Pydantic 校验输入。
- 为首次请求生成 `session_id`，为后续请求复用已有 `session_id`。
- 将 `session_id` 作为 LangGraph 的 `thread_id`，用于当前 session 的 checkpoint。
- 调用 LangGraph 的 `TravelPlannerGraph`。
- 通过 Amap MCP 获取真实景点、酒店、天气和路线摘要数据。
- 通过 LLMService 调用 Gemini 或其他 OpenAI-compatible 模型。
- 通过 PostgresStore + pgvector + bge-m3 召回和保存长期记忆。
- 返回前端可直接渲染的 `TripPlan`。

可以把后端理解成系统的中间层：它一边面对 HTTP 客户端，一边协调 graph、工具、模型和记忆。

## 设计原则

### Async First

后端路由优先使用 async。`POST /api/trip/plan` 会在请求/响应生命周期内调用 async graph。

```python
@router.post("/plan", response_model=TripPlan)
async def create_trip_plan(request: TripPlanRequest) -> TripPlan:
    ...
```

第一版不引入后台任务队列。这样实现更直接，也方便用 curl、Swagger UI 和 pytest 验证完整链路。后续如果规划耗时过长，可以再引入任务队列或进度推送。

### session_id 由后端解析

首次请求可以不传 `session_id`。后端规则如下：

- 如果 `session_id` 缺失、为 `null` 或空字符串，后端生成新的 UUID。
- 如果 `session_id` 存在，后端 trim 后复用它。
- graph 执行时必须拿到非空 `session_id`。
- 最终 `TripPlan.session_id` 必须返回这个 resolved session id。

这样设计是为了让前端首次请求不需要提前创建 session，同时又能在后续请求中延续同一个 planning session。

```text
TripPlanRequest.session_id 可选
resolved_session_id = request.session_id or generate_session_id()
LangGraph thread_id = resolved_session_id
TripPlan.session_id = resolved_session_id
```

前端不应该把完整 session id 展示给用户，但应该在本地保存并随下一次同 session 请求带回。

### Working memory 使用 LangGraph checkpointer

当前 session 的 working memory 存在 LangGraph state 中，并通过 `InMemorySaver` 做 checkpoint。

graph 调用时使用：

```python
config = {
    "configurable": {
        "thread_id": resolved_session_id
    }
}
```

同一进程存活期间，后续请求只要带回相同 `session_id`，就可以恢复同一个 `thread_id` 下的 graph state snapshot。这里的 snapshot 不是长期记忆，也不应该被理解为持久化数据库。

### Long-term memory 使用 PostgresStore

跨 session 的长期记忆使用 LangGraph `PostgresStore`，底层是 Postgres + pgvector。文本通过本地 Ollama `bge-m3:567m` 转成 1024 维 embedding。

长期记忆只保存有复用价值的内容：

- semantic memory：稳定偏好或事实。
- episodic memory：具体历史决策或事件。

应用代码应通过 `PostgresStore.put/search` 这类 Store API 访问长期记忆，不直接依赖 LangGraph 内部表结构或 raw SQL。

## 服务结构

当前后端目录边界如下：

```text
backend/app/
  config.py
  api/
    main.py
    routes/
      health.py
      trip.py
      memory.py
  schemas/
    trip.py
    domain.py
    graph.py
    memory.py
  agents/
    trip_planner_agent.py
    graph.py
    context.py
    nodes.py
    attraction_search.py
    hotel_search.py
    working_memory.py
  memory/
    store.py
    extraction.py
  services/
    amap_service.py
    embedding_service.py
    llm_service.py
```

每个目录承担一个清晰边界：

- `api`：HTTP 路由、依赖获取、错误返回。
- `schemas`：Pydantic 请求、响应、领域模型和 graph 内部合同。
- `agents`：LangGraph 构建、节点、上下文组装、specialist 子图。
- `memory`：长期记忆 store wrapper 和记忆抽取逻辑。
- `services`：Amap MCP、Embedding、LLM 等外部服务封装。
- `config.py`：settings、依赖工厂、生命周期和结构化错误。

## 运行依赖

后端启动时需要准备这些组件：

```text
FastAPI app
TravelPlannerGraph
InMemorySaver checkpointer
LongTermMemoryStore / PostgresStore
EmbeddingService -> Ollama /api/embed
AmapMCPService -> amap-mcp-server
LLMService -> Gemini/OpenAI-compatible endpoint
```

本地运行使用 Docker Compose。容器内部运行 FastAPI，Postgres 和 pgvector 由 Compose 启动，Ollama 运行在宿主机并通过 `host.docker.internal:11434` 被 API 容器访问。

## 配置

`backend/.env` 只保留 secrets 和 provider 选择：

```text
LLM_BASE_URL=...
LLM_API_KEY=...
LLM_MODEL_ID=gemini-3.1-flash-lite

AMAP_MAPS_API_KEY=...
```

下面这些运行时变量由 `docker-compose.yml` 统一覆盖，不建议放进 `.env`：

```text
HOST
PORT
MEMORY_ENABLED
POSTGRES_URL
EMBEDDING_PROVIDER
EMBEDDING_BASE_URL
EMBEDDING_MODEL
EMBEDDING_DIMS
AMAP_MCP_COMMAND
AMAP_MCP_ARGS
```

当前 Docker 路径下，`AMAP_MCP_COMMAND=amap-mcp-server`。不要在 `.env` 里写 Windows 本机 executable 路径。

## 应用生命周期

FastAPI startup 阶段：

1. 加载 settings。
2. 初始化 embedding client。
3. 初始化长期记忆 store；如果 `MEMORY_ENABLED=false`，则跳过长期记忆。
4. 初始化 `InMemorySaver`。
5. 初始化共享 Amap MCP service。
6. 初始化 LLMService。
7. 构建并 compile `TravelPlannerGraph`。
8. 注册 `health`、`trip` 和 `memory` 路由。

FastAPI shutdown 阶段：

1. 关闭 Amap MCP session。
2. 关闭 HTTP client。
3. 关闭 store 或数据库连接，如果实现需要。

如果依赖初始化失败，应用仍可以启动，但依赖获取会返回结构化 `CONFIGURATION_ERROR`，方便本地调试定位问题。

## API 端点

### Health Check

```http
GET /health
```

用途是确认服务运行中。

响应：

```json
{
  "status": "ok"
}
```

### Trip Planning

```http
POST /api/trip/plan
```

用途是运行完整旅行规划 graph。

输入：

```python
TripPlanRequest
```

关键规则：

- 首次请求可以不传 `session_id`。
- 后端会在 graph 执行前解析出非空 `session_id`。
- `cities` 应使用高德可稳定识别的中文城市名，例如 `["北京"]`。
- 日期范围必须合法。
- 偏好索引必须在支持枚举范围内。
- `budget` 如果提供，必须非负。

调用流程：

```text
TripPlanRequest
  -> resolve session_id
  -> build_initial_state
  -> graph.ainvoke(state, config={"configurable": {"thread_id": session_id}})
  -> extract TripPlan
  -> ensure TripPlan.session_id
  -> return TripPlan
```

输出：

```python
TripPlan
```

响应合同：

- `TripPlan.days[*]` 是前端主要渲染单位。
- 每天拥有自己的 `attractions`、`hotel`、`meals`、`map_points` 和 `total_price`。
- 顶层不返回 `budget`，也不返回顶层 `map_points`。
- `TripPlan.session_id` 必须存在。
- provider 返回的 `city`、`name`、`address`、`description` 等文本尽量保持原样。
- 餐食能力仍是 deferred，当前不把每日三餐作为出 API 的硬校验要求。

失败行为：

- 请求非法：FastAPI 默认 validation error。
- 缺少 `session_id`：后端生成新的。
- graph 异常：结构化错误，例如 `GRAPH_EXECUTION_FAILED`。
- planner 多次无法生成有效计划：优先返回 fallback `TripPlan`；如果 fallback 也不可用，则返回结构化错误。

### Recalculate Trip Plan

```http
POST /api/trip/recalculate
```

当前状态：

- 路由已预留。
- MVP 返回结构化 `501 Not Implemented`。
- 错误码为 `TRIP_RECALCULATION_NOT_IMPLEMENTED`。

未来用途：

- 接收用户编辑后的 `TripPlan`。
- 重新计算每日价格。
- 重新生成 map points 或路线 summary。
- 支持删除、重排景点。
- 触发局部 replanning。

### Semantic Memory Inspection

```http
GET /api/memory/semantic
```

用途是本地调试 semantic memory。

查询参数：

```text
user_id: str
query: optional str
limit: int = 10
```

返回字段包括：

```text
memory_type
user_id
query
limit
count
items
```

如果长期记忆未启用或 store 不可用，返回结构化 `MEMORY_STORE_UNAVAILABLE`。

### Episodic Memory Inspection

```http
GET /api/memory/episodic
```

用途是本地调试 episodic memory。参数和响应形状与 semantic memory 调试接口一致。

这些 memory inspection endpoint 面向本地开发和验证。生产环境上线前应该加鉴权或禁用。

## Graph 调用伪代码

```python
@router.post("/plan", response_model=TripPlan)
async def create_trip_plan(
    request: TripPlanRequest,
    graph: CompiledStateGraph = Depends(get_travel_graph),
) -> TripPlan:
    session_id = resolve_session_id(request.session_id)
    resolved_request = request.model_copy(update={"session_id": session_id})
    initial_state = build_initial_state(resolved_request)
    config = {"configurable": {"thread_id": session_id}}

    result_state = await graph.ainvoke(initial_state, config=config)
    trip_plan = result_state.get("trip_plan")
    if trip_plan is None:
        raise StructuredAppError(
            code="GRAPH_EXECUTION_FAILED",
            message="Trip plan was not generated",
        )

    return trip_plan.model_copy(update={"session_id": session_id})
```

当前实现的 `build_initial_state(request)` 很薄，只需要把 `request` 放入 state。具体默认字段由 `InitializeWorkingState` 节点填充。

## 错误处理

后端使用结构化错误形状：

```json
{
  "error": {
    "code": "GRAPH_EXECUTION_FAILED",
    "message": "Trip planning failed",
    "details": {}
  }
}
```

常见错误码：

```text
CONFIGURATION_ERROR
GRAPH_EXECUTION_FAILED
TOOL_CALL_FAILED
PLAN_VALIDATION_FAILED
MEMORY_STORE_UNAVAILABLE
TRIP_RECALCULATION_NOT_IMPLEMENTED
```

MVP 可以保留 FastAPI 默认请求校验错误，但 graph、tool、planner 和 memory 的异常应收口到统一错误形状。

## 本地测试

启动服务后可以先测 health：

```powershell
curl.exe http://127.0.0.1:8000/health
```

再测旅行规划：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/trip/plan" `
  -H "Content-Type: application/json; charset=utf-8" `
  --data-binary "@backend/tests/fixtures/http_requests/trip-request-beijing-public.json"
```

预期：

- 返回值是合法 `TripPlan`。
- 返回值包含 `session_id`。
- `days` 数量匹配日期范围。
- `days[*].total_price` 非负。
- 有坐标的景点、酒店或餐食会生成 `map_points`。
- `Attraction.image_url` 可以是 `null`。
- `route_distance_km`、`route_duration_minutes`、`transit_method` 可以作为轻量路线摘要存在。
- 不返回完整导航步骤。
- `weather_info` 在天气工具成功时填充。
- 验证成功后可能写入 semantic/episodic memory。

查询长期记忆：

```powershell
curl.exe -G "http://127.0.0.1:8000/api/memory/semantic" `
  --data-urlencode "user_id=user_terminal_001" `
  --data-urlencode "query=用户喜欢什么旅行节奏" `
  --data-urlencode "limit=5"

curl.exe -G "http://127.0.0.1:8000/api/memory/episodic" `
  --data-urlencode "user_id=user_terminal_001" `
  --data-urlencode "query=用户拒绝过什么酒店" `
  --data-urlencode "limit=5"
```

## MVP 边界

后端 MVP 不包含：

- 生产鉴权。
- 后台任务队列。
- SSE/WebSocket 进度推送。
- 完整 recalculation。
- 真实酒店库存和实时房价确认。
- 图片 enrichment。
- 完整 turn-by-turn 路线说明。

MVP 的目标是先稳定返回结构化、可验证、可由前端渲染的 `TripPlan`。

## 小结

后端是 ZoeyAgent 的运行中枢。FastAPI 负责 HTTP 边界，LangGraph 负责编排旅行规划，Amap MCP 提供真实地图工具，LLMService 提供模型调用，PostgresStore 提供长期记忆，Pydantic 保证输入输出合同稳定。

这样做的核心收益是：前端只需要消费 `TripPlan`，而复杂的工具调用、记忆召回、repair、fallback 和 provider response normalization 都被后端封装起来。
