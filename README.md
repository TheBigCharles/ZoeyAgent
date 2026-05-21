# ZoeyAgent

ZoeyAgent 是一个面向旅行规划场景的 Agent 应用后端设计。当前仓库以设计文档为主，目标是逐步实现一个自托管 Python FastAPI 服务：接收结构化旅行请求，运行 LangGraph 规划流程，调用 Amap 工具获取景点、酒店和天气信息，并返回可由前端直接渲染的 `TripPlan`。

## 设计文档

- [Backend Design](doc/backend_design.md)
- [Agents Design](doc/agents_design.md)
- [Schemas Design](doc/schemas_design.md)
- [Memory Design](doc/memory_design.md)
- [Tools Design](doc/tools_design.md)
- [Example Workflow](doc/example_workflow.md)

## 总体架构

```mermaid
flowchart TB
    client["客户端或终端测试"] --> api["FastAPI 后端"]
    api --> schema["Pydantic 请求校验"]
    schema --> travelPlannerGraph["TravelPlannerGraph"]

    subgraph app["应用层"]
        health["GET /health"]
        planApi["POST /api/trip/plan"]
        memoryApi["调试用 memory endpoints"]
    end

    subgraph agents["LangGraph 编排层"]
        init["InitializeWorkingState"]
        loadMemory["LoadMemoryNode"]
        normalize["NormalizeRequestNode"]
        attraction["AttractionSearchSubgraph"]
        weather["WeatherQueryNode"]
        hotel["HotelSearchSubgraph"]
        assemble["ContextAssemblyNode"]
        planner["PlannerNode"]
        validate["ValidateTripPlanNode"]
        saveMemory["SaveMemoryNode"]
        fallback["FallbackNode"]

        init --> loadMemory
        loadMemory --> normalize
        normalize --> attraction
        normalize --> weather
        attraction --> hotel
        attraction --> assemble
        weather --> assemble
        hotel --> assemble
        assemble --> planner
        planner --> validate
        validate -->|valid| saveMemory
        validate -->|repair| assemble
        validate -->|fallback| fallback
    end

    subgraph tools["工具层"]
        amapClient["共享 Amap MCP client"]
        amapServer["Amap MCP server"]
        amapApi["Amap 外部 API"]
        amapClient --> amapServer
        amapServer --> amapApi
    end

    subgraph memory["记忆层"]
        working["Working memory<br/>InMemorySaver"]
        store["Long-term memory<br/>PostgresStore"]
        semantic["Semantic memories"]
        episodic["Episodic memories"]
        embedding["vLLM embeddings<br/>BAAI bge-m3"]
        store --> semantic
        store --> episodic
        store --> embedding
    end

    api --> health
    api --> planApi
    api --> memoryApi
    travelPlannerGraph --> init
    init --> working
    loadMemory --> store
    attraction --> amapClient
    weather --> amapClient
    hotel --> amapClient
    saveMemory --> store
    saveMemory --> response["TripPlan 响应"]
    fallback --> response
    response --> client
```

## 实施原则

实施过程应该是递进式的：每一步都在已有结果上继续增加能力，不能为了进入下一步而推翻、重写或回退上一阶段已经跑通的行为。需要调整设计时，应通过兼容层、适配器、迁移脚本或小范围重构向前演进。

## 渐进式实施步骤

1. 建立项目骨架
   - 创建 `app/` 目录、FastAPI 入口、配置模块和基础路由。
   - 先实现 `GET /health`，保证服务可以启动和被测试。
   - 保留后续目录边界：`api`、`schemas`、`agents`、`memory`、`tools`、`core`。

2. 实现 Pydantic 数据契约
   - 按 `doc/schemas_design.md` 实现 `TripPlanRequest`、`TripPlan`、`DayPlan`、`Attraction`、`Hotel`、`Meal`、`WeatherInfo` 等模型。
   - 加入日期、城市、预算、枚举索引和每日餐食数量校验。
   - 这一阶段只增加 schema 能力，不引入真实 LLM 或外部工具依赖。

3. 打通最小 planning endpoint
   - 实现 `POST /api/trip/plan`。
   - 要求客户端必须传入 `session_id`。
   - 先返回一个固定或 mock 的合法 `TripPlan`，用于验证 API 合同和前端渲染合同。

4. 建立 LangGraph 主流程
   - 创建 `TravelPlanState` 和最小 `TravelPlannerGraph`。
   - 先接入 `InitializeWorkingState`、`NormalizeRequestNode`、`PlannerNode`、`ValidateTripPlanNode`。
   - 工具结果继续使用 mock 数据，确保图编排和验证循环先稳定。

5. 接入 working memory
   - 使用 `InMemorySaver`，将 `session_id` 映射为 LangGraph `thread_id`。
   - 实现 `append_working_message` 和 `append_tool_observation` 这类状态更新 helper。
   - 保持 working memory 只服务当前进程和当前 session，不提前承诺持久化。

6. 实现工具归一化层
   - 建立 Amap MCP client 封装，但先让图节点只依赖项目内部 tool wrapper。
   - 实现坐标、评分、价格、天气温度等 provider response normalization。
   - 保证 raw Amap 响应不会直接进入 `PlannerNode`。

7. 接入天气节点
   - 实现 `WeatherQueryNode` 调用 Amap weather 工具。
   - 将结果归一化为 `list[WeatherInfo]`。
   - 天气失败时返回空列表和结构化 observation，不阻断整条规划链路。

8. 实现景点搜索子图
   - 先实现关键词搜索、POI 归一化、去重和基础排序。
   - 再逐步加入 detail search、around search、质量评估和 bounded retry。
   - 子图只输出 `AttractionSearchResult`，不直接生成最终行程。

9. 实现酒店搜索子图
   - 基于景点结果选择酒店搜索 anchor。
   - 搜索并排序候选酒店，输出 `HotelSearchResult`。
   - 明确 Amap POI 只能提供候选酒店，不能确认真实房态。

10. 强化 PlannerNode
    - 将景点、酒店、天气、预算、偏好和 extra requirements 汇总为 planner context。
    - 生成完整 `TripPlan`，包括每日 attractions、meals、hotel、map_points、total_price 和 route summary。
    - 不输出完整路线步骤，不要求 `image_url`。

11. 强化 ValidateTripPlanNode
    - 校验每日三餐、每日价格、日期数量、map points、枚举值和 day-centric response contract。
    - 失败时带着 validation errors 回到 planner 修复。
    - 超过 retry 上限后进入 `FallbackNode`，返回保守可用结果或结构化错误。

12. 接入长期记忆
    - 配置 Postgres、pgvector、LangGraph `PostgresStore` 和本地 vLLM embedding endpoint。
    - 实现 `LoadMemoryNode` 搜索 semantic 和 episodic memories。
    - 实现 `SaveMemoryNode`，只在 `TripPlan` 验证成功后写入长期记忆。

13. 增加 memory 调试接口
    - 实现 `GET /api/memory/semantic` 和 `GET /api/memory/episodic`。
    - 用于本地开发、终端测试和记忆召回验证。
    - 生产环境上线前应加鉴权或禁用。

14. 预留编辑和重算能力
    - 保留 `POST /api/trip/recalculate` 路由和 `TripRecalculateRequest`。
    - MVP 可以返回 `501 Not Implemented`。
    - 后续在不破坏 `TripPlan` 合同的前提下增加局部重排、删除景点、重新计算价格和路线 summary。

15. 做端到端验证
    - 用 `curl`、HTTP client 或 pytest 覆盖 health、trip planning、memory search。
    - 测试单城市、多城市、公共交通、自驾、预算为空、工具失败、planner validation retry 等路径。
    - 每轮验证只修复当前发现的问题，不回退已经稳定的 API 合同。

## MVP 边界

第一版不需要实现前端、图片 enrichment、真实酒店库存、完整路线说明、异步任务队列、SSE/WebSocket 进度推送、生产鉴权和完整 recalculation。MVP 的目标是先让后端能够稳定返回一个结构化、可验证、可渲染的 `TripPlan`。
