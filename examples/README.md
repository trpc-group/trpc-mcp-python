# tRPC-MCP-Python 示例文档说明

本目录是 **对接 trpc-python 框架的 MCP 服务端 + 客户端** 的完整可运行示例，**用户可以直接拷贝改用**。

服务端用 `@trpc_mcp.tool / resource / prompt` 注册能力并由 trpc 框架托管；客户端用 `trpc_mcp.McpProxy`（底层复用官方 MCP SDK，传输层走 trpc 客户端治理链路）发起调用。每个客户端示例都是 **独立、自包含** 的，拷贝单个文件即可改造。

> 例外：`client/test_official_mcp_client.py` 是用 **官方 MCP SDK 原生客户端** 直连做能力对齐测试用的，`用户不要抄这个文件`。

---

## 目录结构

```
examples/
├── trpc_main.py                 # 服务端入口（每个服务进程托管所有 http_mcp service）
├── trpc_python.yaml             # 默认配置：SSE 传输
├── run_examples.sh              # 一键起服务 + 跑客户端 + 关服务
├── conf/                        # 其他场景配置
│   ├── trpc_python_streamable_http.yaml   # streamable-http 传输
│   ├── trpc_python_selector.yaml          # 自定义 selector（test://）
│   ├── trpc_python_mixed.yaml             # 混合协议：Greeter1=http_mcp + Greeter2=http
│   ├── trpc_python_redis.yaml             # 多进程 SSE + redis 会话同步
│   ├── trpc_python_separate.yaml          # separate 多进程模型
│   └── trpc_python_merge.yaml             # merge 多进程模型
├── mcp_callback/                # 服务端能力实现（被 trpc_main.py import 注册）
│   ├── tools.py                 # 工具
│   ├── resources.py             # 资源 / 资源模板
│   └── prompts.py               # 提示词
├── http_service/               # 普通 trpc HTTP 路由（protocol: http，与 http_mcp 共存示例用）
│   └── handlers.py              # trpc_sdk.http.route 注册 /ping、/echo
├── filters/                     # 治理插件（filter / 自定义 selector / tool filter）
│   ├── server_filter.py         # 服务端 filter：one / two / default
│   ├── client_filter.py         # 客户端 filter：default
│   ├── tool_filter.py           # 工具级 filter：EchoToolFilter（pre/post）
│   └── test_selector.py         # 自定义 selector：test://
├── test_trpc_mcp_tool.py        # 客户端示例：工具
├── test_mcp/                    # 其余客户端示例（按功能拆分）
│   ├── test_trpc_mcp_prompt.py            # 提示词
│   ├── test_trpc_mcp_resource.py          # 资源 / 模板
│   ├── test_trpc_mcp_structured_output.py # 结构化输出
│   ├── test_trpc_mcp_icons_meta.py        # 工具 icons / meta 元数据
│   ├── test_trpc_mcp_roots.py             # roots（服务端->客户端回调）
│   ├── test_trpc_mcp_selector.py          # 自定义 selector 寻址
│   └── test_trpc_mcp_mixed_protocol.py    # 混合协议：http_mcp + http 同进程共存
├── client/test_official_mcp_client.py     # 官方 SDK 原生客户端（仅对齐用，勿抄）
└── curl_cmd/send_req.sh                    # 用 curl 手动发 SSE 请求的小工具
```

---

## 一、服务运行的方式

服务端入口是 `trpc_main.py`，运行方式很简单：

```bash
# 在仓库根目录，用项目 venv
venv/bin/python examples/trpc_main.py --conf examples/trpc_python.yaml
```

它做的事情（`trpc_main.py`）：

1. `import mcp_callback.tools / resources / prompts`：**导入即注册**，被 `@trpc_mcp.tool/resource/prompt` 装饰的函数在 import 时写入注册表。
2. `import filters`：注册 server/client filter、tool filter、自定义 selector 插件。
3. `svr = create_server(conf_path)`（`trpc_sdk.server`）按配置创建框架服务。
4. `trpc_mcp.register_trpc_mcp_server(svr, None)`：把已注册的 MCP 能力挂到 trpc server 上。
5. `svr.serve()` 启动监听。

运行模型：

- **每个服务进程**托管配置里 `server.service` 下的所有 http_mcp service（示例为 `Greeter1`@8008、`Greeter2`@8009），并跑**一个 uvicorn 线程和一个 MCP app**；同一进程内的多个 service **共用一个 MCP session manager**。
- 进程模型由 `global.processmodel` 决定：默认单进程 merge；`conf/trpc_python_separate.yaml`（separate，rpc task 进程各跑一个 uvicorn）与 `conf/trpc_python_merge.yaml`（merge，对等 worker 各跑一个 uvicorn）演示多进程，详见仓库根 README 的“进程/线程模型”。
- 传输协议由 `plugins.mcp.server.transport` 决定：`sse` 或 `streamable-http`（**stdio 不支持，会直接报错**）。
- service 与能力的绑定关系（见下文）决定每个端口能访问哪些 tool/resource/prompt。

服务端能力与 service 的绑定（`mcp_name` 决定）：

| 类型 | 名称 | 绑定 service | 说明 / 场景 |
|---|---|---|---|
| tool | `add` | 全部 | 基础加法，带参数注解（给大模型更好理解入参） |
| tool | `echo_header` | 全部 | 回显客户端 HTTP 头，用于验证头部透传 |
| tool | `common_tool` | 全部 | 用 `make_call_tool_result` 返回，演示透传 `meta` |
| tool | `branded_tool` | 全部 | 演示 `icons` + `meta` 工具元数据 |
| tool | `allowed_directories` | 全部 | 反向调用 `roots/list`，需要客户端注册 roots 回调 |
| tool | `get_weather` | Greeter1 | 返回 Pydantic 模型，演示结构化输出 |
| tool | `echo_tool` | Greeter1 | 命中 `EchoToolFilter`，演示工具级 pre/post filter |
| tool | `show_tool` | Greeter1 | 普通工具 |
| tool | `shell_tool` | Greeter2 | 执行 shell，演示绑定到另一个 service |
| resource | `echo://static` | Greeter1 | 静态资源 |
| resource | `template://{text}` | Greeter2 | 资源模板（参数化 URI） |
| resource | `common://{data}` | 全部 | 通用资源模板 |
| prompt | `echo_prompt` | Greeter1 | 提示词 |
| prompt | `show_prompt` | Greeter2 | 提示词 |
| prompt | `common_prompt` | 全部 | 通用提示词 |

> 绑定规则：指定 `mcp_name=` 的能力只在对应 service 可见；不指定的为公共能力，所有 service 都可见。访问不属于该 service 的能力会直接报错（service 隔离）。

---

## 二、测试的功能有哪些，对应什么场景

每个客户端示例只测一类功能（拷贝即用），文件头部都有详细注释与预期输出：

| 示例文件 | 测试功能 | 典型场景 |
|---|---|---|
| `test_trpc_mcp_tool.py` | `list_tools` / `execute_tool`，并验证自定义 HTTP 头端到端透传 | 最常用：发现并调用工具；需要给后端带鉴权头/染色头时 |
| `test_mcp/test_trpc_mcp_prompt.py` | `list_prompts` / `get_prompts` | 让服务端按模板渲染提示词供 LLM 使用 |
| `test_mcp/test_trpc_mcp_resource.py` | `list_resources` / `list_resource_templates` / `read_resource` | 读取静态资源、按模板填参读取动态资源 |
| `test_mcp/test_trpc_mcp_structured_output.py` | 读取 `tool.outputSchema` 与 `CallToolResult.structuredContent` | 调用方（Agent）需要可靠按字段读取结果，而非解析自由文本 |
| `test_mcp/test_trpc_mcp_icons_meta.py` | 工具 `icons` / `meta` 元数据 + 调用级 `meta` 透传 | 客户端要展示工具图标、或按 OpenAI Apps 约定透传元数据 |
| `test_mcp/test_trpc_mcp_roots.py` | 注册 `list_roots_callback`，由 `allowed_directories` 触发 `roots/list` | 服务端工具要访问客户端本地文件/仓库，需先问允许的根目录（双向通道） |
| `test_mcp/test_trpc_mcp_selector.py` | 自定义 `test://` selector 寻址 + 治理链路 | 自定义服务发现/寻址逻辑；`options` 里 `Options().set_target(...)` 优先级高于配置 |
| `test_mcp/test_trpc_mcp_mixed_protocol.py` | 同进程内 `http_mcp`（MCP）与 `http`（普通 HTTP）两个 service 同时调用 | 业务里 MCP 服务与普通 HTTP 服务并存；验证 `http_mcp` 专用 codec 被隔离、不影响普通 `http` |
附带的治理能力（在上面示例中顺带体现）：

- **客户端 filter**（`filters/client_filter.py`，名为 `default`）：每次请求打印 deadline，证明客户端治理链路接上了。
- **服务端 filter**（`filters/server_filter.py`：`one`/`two`/`default`）：服务端 filter 链。
- **工具级 filter**（`filters/tool_filter.py` 的 `EchoToolFilter`）：对 `echo_tool` 做 pre/post 拦截。
- **自定义 selector**（`filters/test_selector.py`）：实现 `test://` 寻址。

---

## 三、怎么运行例子和配置文件

### 1. 一键脚本（推荐）

`run_examples.sh` 会自动：起对应配置的服务 → 等端口就绪 → 跑客户端 → 关服务。

```bash
cd examples

./run_examples.sh list                 # 列出所有可用示例
./run_examples.sh                       # 跑全部默认（SSE）示例
./run_examples.sh all                   # 同上
./run_examples.sh tool                  # 只跑某一个（tool/prompt/resource/...）
./run_examples.sh streamable            # 核心示例全部用 streamable-http 跑一遍
./run_examples.sh tool conf/xxx.yaml    # 指定配置（服务端 + 客户端用同一份）
```

可用示例名：`tool prompt resource structured_output icons_meta roots selector mixed`。
脚本默认监听端口 `8008`、`8009`，跑之前请确保端口空闲。

### 2. 手动两步（理解原理 / 调试用）

先起服务端，再用**同一份配置**跑客户端：

```bash
# 终端 1：起服务（SSE）
venv/bin/python examples/trpc_main.py --conf examples/trpc_python.yaml

# 终端 2：跑客户端
venv/bin/python examples/test_trpc_mcp_tool.py \
    --conf examples/trpc_python.yaml --service trpc.test.mcp.Greeter1
```

换 streamable-http：服务端和客户端都换成 `examples/conf/trpc_python_streamable_http.yaml` 即可。

客户端通用参数：`--conf`（配置文件）、`--service`（要调用的 `client.service` 名）；`resource` 示例额外有 `--uri`。

### 3. 配置文件一览

| 配置文件 | 传输 | 用途 / 关键点 |
|---|---|---|
| `trpc_python.yaml` | SSE | 默认配置，单进程 merge，`base_url: /test` |
| `conf/trpc_python_streamable_http.yaml` | streamable-http | 单进程且 `stateless_http: false`（roots/list 需要有状态 session） |
| `conf/trpc_python_selector.yaml` | SSE | 演示自定义 `test://` selector，`client.target` 用 `http://` |
| `conf/trpc_python_mixed.yaml` | SSE + 普通 HTTP | 混合协议：`Greeter1=http_mcp`（MCP）+ `Greeter2=http`（普通 HTTP，`trpc_sdk.http.route`） |
| `conf/trpc_python_redis.yaml` | SSE | `processmodel` separate 2 进程 + redis；`stateless_http: false` 时会被自动降为 1 个进程 |
| `conf/trpc_python_separate.yaml` | SSE | separate 多进程（`handle_num: 2`）+ 本地 redis + `stateless_http: true` |
| `conf/trpc_python_merge.yaml` | SSE | merge 多进程（`handle_num: 2`）+ 本地 redis + `stateless_http: true` |
配置里和 MCP 相关的关键块：

- `server.service[].protocol` / `client.service[].protocol`：必须是 `http_mcp`。
- `plugins.mcp.server`：`transport`（sse/streamable-http）、`base_url`、`settings`（如 `message_path`、`stateless_http`）、`redis`。
- `plugins.mcp.client`：`transport`、`base_url`——`McpProxy` 在未显式传参时会从这里读默认值。

`McpProxy` 的配置解析优先级：**构造参数 > `options`（如 `Options().set_target(...)`）> 配置文件**。

---

## 四、需要注意什么

1. **MCP service 的 protocol 必须用 `http_mcp`**：MCP 服务端、客户端、自定义 selector 返回的 `node.protocol` 都要是 `http_mcp`。若客户端或 selector 退回成普通 `http`，会把 MCP 专用 codec 降级，导致 SSE POST 的 `202 ACCEPTED` 被当成错误。`http_mcp` 的 codec 是**按协议隔离注册**的，不会劫持全局 `http`，所以同一进程里普通 `http` 业务 service 可以和 `http_mcp` 服务共存（见 `mixed` 示例 / `conf/trpc_python_mixed.yaml`）。
2. **base_url 两端要一致**：示例统一为 `/test`。客户端会基于 `base_url` 拼接 SSE/streamable 路径，不一致会 404。
3. **streamable-http 测 roots/list 的硬性要求**：单进程且 `stateless_http: false`。`roots/list` 是服务端反向请求客户端，依赖有状态 session；stateless 或多进程会拿不到同一个 session。
4. **多进程 SSE 必须配 redis**：`sse-starlette` 的 session 是进程内状态。separate/peer 多进程需要 redis 做跨进程的消息/会话同步，否则 POST 命中的进程与持有 SSE 长连接的进程不是同一个就会失败。缺 redis 或 `stateless_http: false` 时 trpc-mcp 会把进程数降为 1 并打 warning。
5. **service 能力隔离**：访问不属于目标 service 的 tool/resource/prompt 会报错。用 `--service` 选对端口对应的 service；公共能力（无 `mcp_name`）在所有 service 都能访问。
6. **端口占用**：示例固定用 `8008`/`8009`；手动起服务后记得关掉，避免下次端口被占。
7. **stdio 不支持**：本实现明确不支持 stdio 传输，配了会直接抛错。
8. **`client/` 与 `mcp_sdk` 类示例不要抄**：那是用官方原生客户端做能力对齐的，不代表推荐用法。请以 `test_trpc_mcp_*.py` 为准。
9. **版本兼容**：依赖 `mcp>=1.11.0,<2`。部分能力（如工具 `icons`/`meta`、resource `annotations`、调用级 `meta`）是较高版本才有的，trpc-mcp 已做版本自适应——低版本会自动忽略并告警，不会报错。
