# ZoeyAgent

规划一次旅行通常需要在多个页面之间来回切换：查景点、看天气、找酒店、估算路线，再把这些信息整理成每天能执行的行程。ZoeyAgent 尝试把这个过程交给一个可运行的 Agent 应用完成。用户只需要提供城市、日期、预算和偏好，系统就会调用真实地图工具和 LLM 规划流程，生成前端可以直接渲染的 `TripPlan`。

当前仓库已经包含 FastAPI 后端、React 前端和 Docker 本地运行环境。后端通过 LangGraph 编排行程规划流程，使用 Amap MCP 获取景点、酒店、天气和路线摘要，使用 Gemini 生成结构化计划，并通过 Postgres + pgvector + bge-m3 保存可召回的长期记忆。前端负责提交规划请求、展示每日行程和地图点。

## 文档导航

**在开始升入了解项目之前，请先补齐** Agent 范式、MCP、记忆、上下文工程和结构化数据合同等 **背景知识**，可以阅读 [Background Knowledge](background_knowledge.md)。

如果你想先理解系统是如何工作的，建议从 [Walk Through](walk_through.md) 开始。它会按总体架构、组件职责和 Pydantic 数据结构解释一次请求如何被编排。

如果你想看这个项目是如何一步步实现出来的，可以阅读 [Implementation Guide](implementation_guide.md)。它记录了实施原则、渐进式步骤和 MVP 边界。

## 设计文档

下面这些文档保留了更细的设计说明。README 只作为入口，不展开所有细节。

- [Backend Design](doc/backend_design.md)
- [Agents Design](doc/agents_design.md)
- [Schemas Design](doc/schemas_design.md)
- [Memory Design](doc/memory_design.md)
- [Tools Design](doc/tools_design.md)
- [Example Workflow](doc/example_workflow.md)

## 本地启动

在深入阅读实现之前，建议先把项目跑起来。这样你会更容易把后面的架构图和真实页面、真实 API 响应对应起来。

本项目只保留 Docker 启动路径。先确认 Docker Desktop 已启动，Ollama 已在宿主机运行并已拉取 `bge-m3:567m`。准备好后，在项目根目录运行：

```powershell
docker compose up --build
```

前端地图使用 `frontend/.env` 中的 `VITE_AMAP_WEB_JS_KEY`。这个 key 是浏览器加载高德地图 JS SDK 时使用的，和后端调用 Amap MCP 的服务端 key 不是同一个入口。如果要显示地图 canvas 和 marker，请先写入：

```text
VITE_AMAP_WEB_JS_KEY=your_amap_web_key
```

服务启动后，前端入口是 `http://127.0.0.1:3000`，后端 API 暴露在 `http://127.0.0.1:8000`。如果你想绕过前端，直接验证后端规划链路，可以在另一个 PowerShell 里调用测试请求：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/trip/plan" `
  -H "Content-Type: application/json; charset=utf-8" `
  --data-binary "@backend/tests/fixtures/http_requests/trip-request-beijing-public.json"
```

`backend/.env` 只保留 secrets 和 provider 选择。它不写 Windows 路径，也不写容器内网络地址，因为这些运行时配置已经由 Docker Compose 统一管理。建议保留：

```text
LLM_BASE_URL=...
LLM_API_KEY=...
LLM_MODEL_ID=gemini-3.1-flash-lite
AMAP_MAPS_API_KEY=...
```

下面这些值由 `docker-compose.yml` 统一覆盖，不需要放进 `.env`：`HOST`、`PORT`、`POSTGRES_URL`、`MEMORY_ENABLED`、`EMBEDDING_PROVIDER`、`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`EMBEDDING_DIMS`、`AMAP_MCP_COMMAND`、`AMAP_MCP_ARGS`。

HTTP 输入里 `TripPlanRequest.cities` 应传中文城市名，例如 `["北京"]`。这是一个容易踩坑的地方：当前 Amap MCP 的 POI 搜索对英文城市名不稳定，`["Beijing"]` 可能召回北京以外的 POI。前端展示语言可以自行决定，但传给后端的 provider-facing 城市字段应使用高德可稳定识别的中文城市名。

如果你想确认长期记忆是否已经写入并可召回，可以使用 memory 调试接口：

```powershell
curl.exe -G "http://127.0.0.1:8000/api/memory/semantic" `
  --data-urlencode "user_id=browser-test-001" `
  --data-urlencode "query=轻松历史文化" `
  --data-urlencode "limit=5"

curl.exe -G "http://127.0.0.1:8000/api/memory/episodic" `
  --data-urlencode "user_id=browser-test-001" `
  --data-urlencode "limit=5"
```

端到端测试请求样例放在 `backend/tests/fixtures/http_requests/`，例如 `trip-request-beijing-public.json`、`trip-request-beijing-driving.json` 和 `trip-recalculate-request.json`。这些 fixture 的作用是避免每次测试都手工复制 payload。运行本地合同测试：

```powershell
docker compose exec api python -m pytest tests/test_e2e_validation.py
```

前端是 React/Vite 应用。生产容器用 Nginx 托管静态 build，并把 `/api/*` 代理到 `api:8000`。前端构建和测试也通过 Docker 运行，这样本机不需要单独维护 Node 环境：

```powershell
docker compose build frontend
docker compose run --rm frontend-test
```
