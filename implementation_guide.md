# Implementation Guide

这份文档记录 ZoeyAgent 的实施原则、渐进式实施步骤和 MVP 边界。它的目标是保证每一步都在已有能力上向前演进，而不是为了进入下一阶段推翻前面的结果。

## 实施原则

实施过程应该是递进式的：每一步都在已有结果上继续增加能力，不能为了进入下一步而推翻、重写或回退上一阶段已经跑通的行为。需要调整设计时，应通过兼容层、适配器、迁移脚本或小范围重构向前演进。

**Specialist 子图共同约束**

- Specialist 子图是 bounded ReAct 风格：LLM 只负责局部 plan/action 决策，工具调用必须经过项目内部 service，规则 evaluator 负责质量判断和 retry 边界。
- 子图拥有自己的 local scratchpad，例如 local plan、attempted keywords、local observations、partial candidates、quality 和 retry count。
- 子图使用自己的 local context builder 组装 LLM messages；它不是主 graph 里的 `ContextAssemblyNode`，也不会读取完整 planner context。
- 子图可以共用同一个 `LLMService` API wrapper，但每个子图和 `PlannerNode` 都使用各自独立的 `messages`，不会共享 LLM 对话历史或 session。
- 子图不直接读取完整 planner context，不生成最终 `TripPlan`，也不直接写 long-term memory。
- 子图写回主 state 时只返回结构化结果和简短 observation，避免把完整 ReAct scratchpad 塞进 `TravelPlanState`。

## 渐进式实施步骤

1. 建立项目骨架
   - 创建 `backend/app/` 目录、FastAPI 入口、配置模块和基础路由。
   - 先实现 `GET /health`，保证服务可以启动和被测试。
   - 保留后续目录边界：`api`、`schemas`、`agents`、`memory`、`services`、`config.py`。
   - 验证方式：启动 FastAPI app，并用 `curl /health` 确认返回 `{"status": "ok"}`。

2. 实现 Pydantic 数据契约
   - 按 `doc/schemas_design.md` 实现 `TripPlanRequest`、`TripPlan`、`DayPlan`、`Attraction`、`Hotel`、`Meal`、`WeatherInfo` 等模型。
   - 将模型按边界拆分到 `schemas/trip.py`、`schemas/domain.py`、`schemas/graph.py`、`schemas/memory.py`，避免后续阶段在一个大文件里堆叠。
   - 加入日期、城市、预算、枚举索引和每日餐食数量校验。
   - 这一阶段只增加 schema 能力，不引入真实 LLM 或外部工具依赖。
   - 验证方式：为请求模型、响应模型和关键 validator 添加单元测试。

3. 打通最小 planning endpoint
   - 实现 async `POST /api/trip/plan`。
   - 首次请求可以不传 `session_id`；后端生成新的 `session_id`，并在 `TripPlan.session_id` 中返回。
   - 如果前端已经拿到 `session_id`，后续同一 planning session 必须继续传回该值。
   - 先返回一个受控的合法 `TripPlan` 测试数据，用于验证 API 合同和前端渲染合同。
   - 验证方式：用 `curl` 提交不带 `session_id` 的最小合法请求，确认返回值能通过 `TripPlan` 校验且包含后端生成的 `session_id`。

4. 建立 LangGraph 主流程
   - 创建 `TravelPlanState` 和最小 `TravelPlannerGraph`。
   - 先接入 `InitializeWorkingState`、`NormalizeRequestNode`、`PlannerNode`、`ValidateTripPlanNode`。
   - 工具结果继续使用受控测试数据，确保图编排和验证循环先稳定。
   - 保持 graph 调用入口为 async，后续可以直接替换成 `graph.ainvoke(...)`。
   - 验证方式：通过 `/api/trip/plan` 调用测试 graph，确认 endpoint 不再直接拼响应，而是从 graph 输出 `TripPlan`。

5. 建立应用生命周期、依赖注入和错误边界
   - 在 `config.py` 中集中管理 settings、graph、checkpointer、store、Amap MCP client 和 LLM client。
   - 在 FastAPI startup/shutdown 中预留初始化和关闭外部资源的生命周期。
   - 引入结构化错误边界，例如 `GRAPH_EXECUTION_FAILED`、`TOOL_CALL_FAILED`、`PLAN_VALIDATION_FAILED`。
   - MVP 可以先保留 FastAPI 默认校验错误，但 graph/tool/planner 异常需要开始收口到统一错误形状。
   - 验证方式：用 dependency override 覆盖 graph 成功、graph 抛错、配置缺失三类路径。

6. 封装 LLM service 和 LLM 节点基础设施
   - 在 `services/llm_service.py` 中封装 OpenAI-compatible chat completion。
   - 先实现普通非流式调用和非流式 function calling/tool calling。
   - 保留 stream response 方法签名，但真实 streaming 推迟到 SSE/WebSocket 或进度 UI 阶段。
   - 图节点只依赖项目内部 `LLMService`，不直接散落调用 OpenAI SDK。
   - 建立 `PromptTemplateRegistry`、`BaseLLMNode`、structured output validation 和 retry policy skeleton。
   - 验证方式：用注入式测试 client 覆盖 message、tools 和 deferred stream 行为，并用真实 `.env` 做 LLM smoke test。

7. 实现上下文组装层
   - 实现 reusable `ContextAssembler`，支持 `ContextProfile`、`PromptTemplateSpec` 和 token budget。
   - 将 main graph 的 `ContextAssemblyNode` 做成可替换 adapter，基于 `ContextAssemblyInterface` 在 `PlannerNode` 前执行 Gather、Select、Structure、Compress。
   - 实现 `SpecialistContextBuilder`，让 ReAct 子图内部 LLM 节点通过 local state 和必要主 state 摘要组装 messages。
   - specialist subgraph 不额外画主图级 `ContextAssemblyNode`，但拥有自己的 local context assembly。
   - 验证方式：用固定 state 测试上下文来源过滤、重要性排序、压缩开关、planner context sections、主 context node 可替换性和 specialist local message 构造。

8. 封装 Amap MCP tool 和归一化层
   - 使用 MCP Python client，通过 stdio 连接已安装的 `sugarforever/amap-mcp-server`。
   - 默认启动配置为 `AMAP_MCP_COMMAND=amap-mcp-server`、`AMAP_MCP_ARGS=`，密钥环境变量为 `AMAP_MAPS_API_KEY`。
   - `TripPlanRequest.cities` 面向 Amap 查询时必须使用中文城市名，例如 `北京`；英文城市名可以保留给前端展示层，但不应作为 provider-facing 城市输入。
   - 在 `services/amap_service.py` 中建立共享 Amap MCP client 封装，整个后端通过同一个服务边界调用地图工具。
   - 接入真实 MCP 工具名：`maps_text_search`、`maps_search_detail`、`maps_geo`、`maps_weather`、`maps_direction_walking_by_address`、`maps_direction_driving_by_address`、`maps_direction_transit_integrated_by_address`。
   - 实现坐标、评分、价格、天气温度和 route summary 的 provider response normalization。
   - 当 `maps_text_search` 返回 POI 但缺少经纬度时，先用 `maps_search_detail` 按 POI ID 补全坐标，再用 `maps_geo` 按城市和地址/名称兜底。
   - 增加地图 anchor helper：只从有 `location` 的景点、酒店和餐食生成 `MapPoint`，保证 `DayPlan.map_points` 可被前端直接渲染。
   - direction tool 输出只保留距离、耗时和交通方式，不返回公交站数、换乘细节或 turn-by-turn 路线。
   - 保证 raw Amap 响应不会直接进入 `PlannerNode`。
   - 验证方式：用真实 Amap MCP smoke test 覆盖 POI 搜索、POI detail/geocode 坐标补全、天气和 route summary；单元测试使用从真实响应形状抽出的测试 fixture 防止回归。

9. 接入天气节点
   - 实现 `WeatherQueryNode` 调用 Amap weather 工具。
   - 将结果归一化为 `list[WeatherInfo]`。
   - 天气失败时返回空列表和结构化 observation，不阻断整条规划链路。
   - 验证方式：用真实 Amap weather 响应形状的测试 fixture 和 smoke test 确认 graph state 中写入 `weather_info`。

10. 建立 specialist search 子图基础设施
   - 建立 specialist 子图共同方法论：local task planner、restricted tool executor、step evaluator、bounded retry、rank/deduplicate 和 result write-back。
   - 共同基础设施不定义独立的通用搜索配置 schema；共享的是接口、约束和 helper，具体搜索逻辑保留在各自领域子图中。
   - 子图拥有自己的 local context 和 local scratchpad，不直接读取完整 planner context，也不直接生成最终 `TripPlan`。
   - 子图只通过项目内部 service 调工具，例如 Amap service 或后续其他工具封装，不能直接把 raw provider response 写进 planner。
   - 验证方式：用真实响应形状的测试 fixture 覆盖 retry 上限、quality warning、best-effort result、去重排序和 result write-back。

11. 实现 LLM ReAct 景点搜索子图
   - 实现 `AttractionSearchSubgraph`：LLM 先生成局部搜索计划，再根据 observation 选择 `search_attractions` action。
   - 子图通过 `SpecialistContextBuilder` 构造 plan/action messages，不直接手写完整 prompt context，也不复用主 graph 的 `ContextAssemblyNode`。
   - executor 调用 `AmapMCPService.search_attractions()`，不直接调用 raw MCP；service 内部负责 `maps_text_search`、`maps_search_detail`、`maps_geo` 和 `Attraction` 归一化。
   - 规则 evaluator 基于候选数量、坐标完整度、去重后数量和偏好匹配生成 `SearchQuality`，质量不足时 bounded retry。
   - 子图只写回 `AttractionSearchResult`、扁平 `attractions` 和简短 `tool_observations`，不生成最终行程。
   - 验证方式：用 fake LLM/fake Amap 覆盖 plan/action、去重、排序、retry、非法 LLM 输出和依赖缺失；用真实 Gemini + Amap smoke 确认输出尽量 map-ready 的景点候选。

12. 实现 LLM ReAct 酒店搜索子图
   - 实现 `HotelSearchSubgraph`：LLM 先基于景点结果、城市、预算、交通方式和住宿偏好生成局部酒店搜索计划。
   - 子图同样通过 `SpecialistContextBuilder` 构造 plan/action messages，只读取必要的景点候选摘要和酒店 local scratchpad。
   - LLM 每轮选择受限 action，例如搜索酒店候选、切换景点 anchor、扩大搜索范围或请求 direction summary。
   - executor 只调用项目内部归一化工具，例如 `AmapMCPService.search_hotels()` 和必要的 route summary helper，不直接把 raw Amap 响应交给 Planner。
   - 规则 evaluator 基于候选数量、坐标完整度、到景点 anchor 的距离/耗时、预算线索、评分和交通偏好生成 `SearchQuality`。
   - 明确 Amap POI 只能提供候选酒店，不能确认真实房态；子图只输出 `HotelSearchResult`、扁平 `hotels`、selected hotel 和 ranking reasons。
   - 验证方式：用 fake LLM/fake Amap 覆盖 action、anchor 切换、retry、best-effort、候选排序和工具失败；用真实酒店 POI/detail/geocode 响应形状确认候选酒店可用于后续 Planner。

13. 强化 PlannerNode
   - 将景点、酒店、天气、预算、偏好和 extra requirements 汇总为 planner context。
   - 生成完整 `TripPlan`，包括每日 attractions、meals、hotel、map_points、total_price 和 route summary。
   - 不输出完整路线步骤，不要求 `image_url`。
   - 验证方式：用固定 planner 输入测试每日价格、地图点和合理的日期数量；餐食可为空，等后续 meal 能力接入后再强化。

14. 强化 ValidateTripPlanNode、repair 和 fallback
   - 校验日期数量、每日 `day_index`、每日价格、map points、枚举值和 day-centric response contract；不校验每日三餐。
   - 失败时带着 validation errors 回到 planner 修复。
   - 超过 retry 上限后进入 `FallbackNode`，返回保守可用结果或结构化错误。
   - 验证方式：构造日期数量错误、日期和 `day_index` 不一致、价格为负、map points 缺失等坏输出，确认 validator 能拒绝并触发 repair 或 fallback。

15. 接入 working memory
   - 使用 `InMemorySaver`，将解析后的 `session_id` 映射为 LangGraph `thread_id`，并通过 `graph.compile(checkpointer=checkpointer)` 启用 checkpoint。
   - API 每次只提交当前 `TripPlanRequest`；同一 `thread_id` 的 `working_messages` 和 `tool_observations` 从 checkpoint 恢复。
   - 实现 `maintain_working_messages` 和 `maintain_tool_observations` 这类统一状态更新 helper。
   - working memory 超过 50 条消息时触发 overflow policy，保留最新 50 条。
   - 保持 working memory 只服务当前进程和当前 session，不提前承诺持久化。
   - 验证方式：用相同 `session_id` 连续请求，确认进程存活期间 graph state 能被恢复。

16. 实现 MemoryExtractionService
   - 将工作记忆 overflow 和最终成功计划的记忆抽取统一到 `memory/extraction.py`。
   - 抽取 `MemoryCandidate`，分类为 semantic、episodic 或 discard。
   - 对候选记忆做去重、置信度过滤和写入前校验；这一阶段只产出候选，不写入长期 store。
   - overflow 时在裁掉旧 working memory 前抽取 semantic/episodic 候选；final valid `TripPlan` 后通过 `SaveMemoryNode` 抽取本轮成功计划候选。
   - 验证方式：用固定 working messages、overflow items 和 final `TripPlan` 测试分类、discard、dedup 和 dropped_count。

17. 接入长期记忆
   - 配置 Postgres、pgvector、LangGraph `PostgresStore` 和本地 embedding endpoint；MVP 使用 Ollama `bge-m3:567m`，并保留 OpenAI-compatible/vLLM 入口。
   - 实现 `EmbeddingService` 和 `LongTermMemoryStore`，让 `PostgresStore` 对 `text` 字段建立 embedding index。
   - 实现 `LoadMemoryNode`，在规划前按 `user_id` 搜索 semantic 和 episodic memories 并写入 `TravelPlanState`。
   - 扩展 `SaveMemoryNode`，只在 `TripPlan` 验证成功后把 `MemoryExtractionService` 产出的候选写入长期记忆。
   - 本地未配置 Postgres 时可通过 `MEMORY_ENABLED=false` 关闭长期记忆，避免开发流程被基础设施阻塞。
   - 验证方式：分别测试 memory disabled、测试 store wrapper、真实 PostgresStore + pgvector + Ollama 三种路径。

18. 增加 memory 调试接口
   - 实现 `GET /api/memory/semantic` 和 `GET /api/memory/episodic`。
   - 用于本地开发、终端测试和记忆召回验证。
   - 返回 `memory_type`、`user_id`、`query`、`limit`、`count` 和 `items`，便于终端直接检查召回结果。
   - 生产环境上线前应加鉴权或禁用。
   - 验证方式：在测试 store 和真实 store 下分别查询 semantic/episodic memory。

19. 预留编辑和重算能力
   - 保留 `POST /api/trip/recalculate` 路由和 `TripRecalculateRequest`。
   - MVP 当前返回结构化 `501 Not Implemented`，错误码为 `TRIP_RECALCULATION_NOT_IMPLEMENTED`。
   - 后续在不破坏 `TripPlan` 合同的前提下增加局部重排、删除景点、重新计算价格和路线 summary。
   - 验证方式：确认 endpoint 存在、返回明确的未实现响应，并不会影响 `/api/trip/plan`。

20. 做端到端验证
   - 在 `backend/tests/fixtures/http_requests/` 下保存可复用 JSON 请求样例，避免端到端验证依赖手工复制 payload。
   - 用 pytest + FastAPI TestClient 覆盖 health、trip planning、memory search 和 reserved recalculate。
   - 测试单城市、多城市、公共交通、自驾、预算为空、工具失败、planner validation retry 等路径。
   - 每轮验证只修复当前发现的问题，不回退已经稳定的 API 合同。

## MVP 边界

第一版不需要实现前端、图片 enrichment、真实酒店库存、完整路线说明、异步任务队列、SSE/WebSocket 进度推送、生产鉴权和完整 recalculation。MVP 的目标是先让后端能够稳定返回一个结构化、可验证、可渲染的 `TripPlan`。
