# ZoeyAgent

ZoeyAgent 是一个面向旅行规划场景的 Agent 应用。当前仓库包含 FastAPI 后端、React 前端和 Docker 本地运行环境：后端接收结构化旅行请求，运行 LangGraph 规划流程，调用 Amap MCP、Gemini 和长期记忆能力，并返回可由前端直接渲染的 `TripPlan`。

## 文档导航

- [Walk Through](walk_through.md)：教学导览，按总体架构、组件职责和 Pydantic 数据结构解释系统如何工作。
- [Implementation Guide](implementation_guide.md)：实施原则、渐进式实施步骤和 MVP 边界。

## 设计文档

- [Backend Design](doc/backend_design.md)
- [Agents Design](doc/agents_design.md)
- [Schemas Design](doc/schemas_design.md)
- [Memory Design](doc/memory_design.md)
- [Tools Design](doc/tools_design.md)
- [Example Workflow](doc/example_workflow.md)

## 本地启动

本项目只保留 Docker 启动路径。先确认 Docker Desktop 已启动，Ollama 已在宿主机运行并已拉取 `bge-m3:567m`，然后在项目根目录运行：

```powershell
docker compose up --build
```

前端地图使用 `frontend/.env` 中的 `VITE_AMAP_WEB_JS_KEY`。如果要显示高德地图 canvas 和 marker，请先把你的 Web JS API key 写入：

```text
VITE_AMAP_WEB_JS_KEY=your_amap_web_key
```

服务启动后，前端入口是 `http://127.0.0.1:3000`，后端 API 仍然暴露在 `http://127.0.0.1:8000`。在另一个 PowerShell 里可以调用测试请求：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/trip/plan" `
  -H "Content-Type: application/json; charset=utf-8" `
  --data-binary "@backend/tests/fixtures/http_requests/trip-request-beijing-public.json"
```

`backend/.env` 只保留 secrets 和 provider 选择，不写 Windows 路径，也不写容器内网络地址。建议保留：

```text
LLM_BASE_URL=...
LLM_API_KEY=...
LLM_MODEL_ID=gemini-3.1-flash-lite
AMAP_MAPS_API_KEY=...
```

这些值由 `docker-compose.yml` 统一覆盖，不需要放进 `.env`：`HOST`、`PORT`、`POSTGRES_URL`、`MEMORY_ENABLED`、`EMBEDDING_PROVIDER`、`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`EMBEDDING_DIMS`、`AMAP_MCP_COMMAND`、`AMAP_MCP_ARGS`。

HTTP 输入里 `TripPlanRequest.cities` 应传中文城市名，例如 `["北京"]`。当前 Amap MCP 的 POI 搜索对英文城市名不稳定，`["Beijing"]` 可能召回北京以外的 POI；前端展示语言可以自行决定，但传给后端的城市字段应使用高德可稳定识别的中文城市名。

长期记忆调试接口示例：

```powershell
curl.exe -G "http://127.0.0.1:8000/api/memory/semantic" `
  --data-urlencode "user_id=browser-test-001" `
  --data-urlencode "query=轻松历史文化" `
  --data-urlencode "limit=5"

curl.exe -G "http://127.0.0.1:8000/api/memory/episodic" `
  --data-urlencode "user_id=browser-test-001" `
  --data-urlencode "limit=5"
```

端到端测试请求样例放在 `backend/tests/fixtures/http_requests/`，例如 `trip-request-beijing-public.json`、`trip-request-beijing-driving.json` 和 `trip-recalculate-request.json`。运行本地合同测试：

```powershell
docker compose exec api python -m pytest tests/test_e2e_validation.py
```

前端是 React/Vite 应用，生产容器用 Nginx 托管静态 build，并把 `/api/*` 代理到 `api:8000`。前端构建和测试也通过 Docker 运行，避免依赖本机 Node 环境：

```powershell
docker compose build frontend
docker compose run --rm frontend-test
```
