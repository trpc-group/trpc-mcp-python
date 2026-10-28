[English](README.md) | 中文

# tRPC-MCP-Python

`trpc-mcp` 是 trpc-python 框架对接 **MCP（Model Context Protocol）** 协议的插件。它让你用 trpc 的方式提供和调用 MCP 能力（Tool / Resource / Prompt），并把 MCP 接入 trpc 的服务治理体系。

一句话概括：

```text
trpc-mcp = 官方 MCP SDK（FastMCP / ClientSession）+ trpc-python 服务治理（selector / filter / options）+ SSE & Streamable-HTTP 传输
```

服务端用装饰器声明能力、由 trpc server 托管；客户端用 `McpProxy` 调用，传输层桥接到 trpc 客户端，从而复用 trpc 全套治理能力，同时接口形态与官方 MCP SDK 保持一致。

## 核心特点

- **trpc 原生体验**：服务端 `@trpc_mcp.tool / @trpc_mcp.resource / @trpc_mcp.prompt` 声明能力；客户端 `McpProxy` 像普通 trpc 后端一样按配置寻址、调用。
- **复用官方 MCP SDK**：构建在官方 `mcp` SDK 之上（`FastMCP` / `ClientSession` / 官方传输），协议新特性大多"继承即用"，维护成本低。
- **对接 trpc 服务治理**：客户端复用 selector（IP / 自定义）、filter、options（协议 / 命名空间 / 超时 / 染色）等治理链路。
- **多传输支持**：SSE 与 Streamable-HTTP 两种传输可切换（不支持 stdio）；多进程 SSE 可用 redis 做会话同步。
- **适配全部进程模型**：单进程 merge（单 loop / 多线程）、separate、peer 均可用，每个服务进程一个 MCP app + 一个 uvicorn，SIGTERM 时随框架优雅退出。
- **双向通道**：除 client→server 调用外，支持 server→client 回调（`roots/list`、`sampling`、`elicitation` 等，通过 `session_args` 注入）。
- **结构化输出**：支持 `outputSchema` 与 `CallToolResult.structuredContent`，调用方可按字段可靠读取结果。
- **多 service 隔离**：能力可绑定到指定 service，也可作为公共能力被所有 service 访问。
- **版本自适应**：依赖 `mcp>=1.11.0,<2`，对各版本差异（如 `icons`/`meta`/resource `annotations`、`call_tool(meta=)`）做了自适应，低版本自动降级不报错。

## 安装与快速开始

### 环境要求

- Python `>=3.10`（推荐 3.12），建议用虚拟环境隔离依赖。
- trpc-python SDK（`trpc_sdk` 包，PyPI 名 `trpc-python`），不支持 Windows。

### 安装

```bash
pip install trpc-mcp
```

依赖：`trpc-python`（提供 `trpc_sdk`）、`mcp>=1.11.0,<2`、`uvicorn`、`redis`（多进程 SSE 场景需要）。

### 快速开始

#### 1. 服务端：声明能力并启动

```python
# trpc_main.py
import trpc_mcp
from trpc_sdk.server import create_server


@trpc_mcp.tool()                       # 不指定 mcp_name -> 所有 service 可见
def add(ctx, a: int, b: int) -> int:
    """两个整数相加"""
    return a + b


@trpc_mcp.resource("echo://static", mcp_name="trpc.test.mcp.Greeter1")
def echo_resource(ctx) -> str:         # 绑定到指定 service
    return "this is static resource!"


@trpc_mcp.prompt("echo")
def echo_prompt(ctx, prompt: str) -> str:
    return f"this is {prompt}"


def serve(conf_path: str):
    svr = create_server(conf_path)
    trpc_mcp.register_trpc_mcp_server(svr, None)   # 把已注册的 MCP 能力挂到 trpc server
    svr.serve()
```

启动：

```bash
python trpc_main.py --conf trpc_python.yaml
```

#### 2. 客户端：用 McpProxy 调用

```python
import trpc_mcp
from trpc_sdk.abc import TrpcContext
from trpc_sdk.client import Options


async def call():
    proxy = trpc_mcp.McpProxy(
        name="trpc.test.mcp.Greeter1",                 # 按配置自动寻址
        options=[Options().set_protocol("http_mcp").set_namespace("Development")],
    )
    try:
        await proxy.initialize(TrpcContext())
        tools = await proxy.list_tools(TrpcContext())
        result = await proxy.execute_tool(TrpcContext(), "add", {"a": 1, "b": 2})
        print(result.structuredContent, result.content)
    finally:
        await proxy.cleanup()
```

> 各功能（tool / prompt / resource / 结构化输出 / icons·meta / roots / 自定义 selector）的完整可运行示例、配置说明与一键运行脚本见 **[`examples/README.md`](examples/README.md)**。

## 整体设计

客户端复用 trpc 客户端治理链路，传输层桥接到官方 MCP SDK；服务端是继承官方 `FastMCP` 的 trpc 适配层。

```mermaid
flowchart TD
    subgraph Client
      A[TrpcContext + options] --> B[McpProxy]
      B --> C[官方 ClientSession + sse_client / streamable_http_client]
      C --> D[httpx 桥接 TrpcHttpxTransport]
      D --> E[trpc http 客户端: selector / filter / options / codec]
    end
    E -->|HTTP / SSE| F[每个服务进程一个 uvicorn 线程: start_mcp]
    subgraph Server
      F --> G[TrpcMcpServer 继承 FastMCP]
      G --> H[Tools / Resources / Prompts]
    end
```

要点：

- **客户端**：`McpProxy` 驱动官方 `ClientSession` 与官方传输，但所有 HTTP 往返通过 `httpx` 自定义传输落到 trpc 客户端，从而每次请求都走 trpc 的节点选择、filter、options 与编解码。
- **服务端**：`TrpcMcpServer` 继承官方 `FastMCP`。`import trpc_mcp` 时通过 `trpc_sdk.transport.register_protocol_handle("http_mcp", start_mcp)` 注册协议启动器，由 SDK 在每个服务进程里调用，起一个 uvicorn 线程托管该进程全部 `http_mcp` 端口；请求先经过 trpc server filter 链再进入 MCP。
- **会话隔离**：Streamable-HTTP 的单会话崩溃隔离由官方 SDK（`mcp>=1.11.0`）保证，trpc-mcp 直接复用。

## 使用方式

### 服务端能力声明

- `@trpc_mcp.tool(name=, title=, description=, structured_output=, annotations=, icons=, meta=, mcp_name=)`
- `@trpc_mcp.resource(uri, name=, title=, description=, mime_type=, icons=, annotations=, meta=, mcp_name=)`
- `@trpc_mcp.prompt(name=, title=, description=, icons=, mcp_name=)`

`mcp_name` 决定能力绑定到哪个 service；不填则为公共能力（所有 service 可见）。函数第一个参数固定是 `ctx`（`TrpcContext`），可用 `trpc_mcp.get_http_req(ctx)`、`get_server_addr(ctx)`、`get_session_func(ctx)` 等读取上下文。

### 客户端 McpProxy

常用方法：`list_tools` / `execute_tool` / `list_resources` / `list_resource_templates` / `read_resource` / `list_prompts` / `get_prompts`。

- host / base_url / transport / target 可从配置自动解析，也可在构造或 `options` 显式指定（优先级：构造参数 > options > 配置）。
- `options` 是 `trpc_sdk.client.Options` 列表，按顺序生效、后写覆盖；`McpProxy` 会在最后追加 `set_protocol("http_mcp")`，未传任何 options 时补一个默认超时。
- 自定义 HTTP 头：`set_http_header_to_context(ctx, {...})`，会注入到该连接的每个 HTTP 请求。
- 注入官方 `ClientSession` 回调（server→client）：`initialize(ctx, session_args={"list_roots_callback": ..., "sampling_callback": ..., "elicitation_callback": ...})`。

### 配置

MCP 相关配置在 `plugins.mcp`，例如选择传输和 base_url：

```yaml
plugins:
  mcp:
    server:
      transport: sse            # sse / streamable-http
      base_url: /test
      settings:
        message_path: /messages/
    client:
      transport: sse            # McpProxy 未显式传参时的默认传输
      base_url: /test
```

多进程 SSE 用 redis 做会话同步（否则请求路由到不同进程会导致 session 失效）：

```yaml
plugins:
  mcp:
    server:
      redis:
        host: 127.0.0.1
        port: 6379
        db: 0
```

## 进程/线程模型

进程模型由框架 YAML 的 `global.processmodel` 决定。无论哪种模型，**每个服务进程只有一个 MCP app 和一个 uvicorn**：uvicorn 跑在独立的 daemon 线程里，用 `SO_REUSEPORT` 绑定该进程负责的全部 `http_mcp` 端口。

| 模型 | YAML | MCP/uvicorn 在哪 |
|---|---|---|
| merge 单 loop（默认） | 不配 `processmodel` | 主进程 1 个 |
| merge 多线程 | `mode: single_process`，`io_num`/`handle_num` > 1 | 主进程 1 个（由第 0 个 serving 线程启动，其他线程不重复起） |
| separate | `mode: multi_process`，`io_handle_type: separate`，`handle_num: N` | 每个 rpc task 进程 1 个；I/O 进程不监听 `http_mcp` 端口 |
| peer | `mode: multi_process`，`io_handle_type: peer`（或 `merge`），`handle_num: N` | 每个对等 worker 进程 1 个 |

```yaml
global:
  processmodel:
    mode: multi_process
    io_handle_type: separate
    handle_num: 2          # 0 表示 CPU 核数
```

**进程数自动修正**：separate / peer 下进程数 > 1 时，若 `plugins.mcp.server.redis` 未配置，或 `settings.stateless_http` 为 `false`，`register_trpc_mcp_server` 会在 fork 前把进程数改为 1 并打 warning。MCP session 是进程内状态，多进程必须同时满足“redis 做 SSE 会话同步”和“无状态 HTTP”。merge 模式不受影响。

**优雅退出**：收到 SIGTERM 后，框架的 `exit_callbacks` 让 uvicorn 停止接收新连接并开始 graceful shutdown（超时取框架的 drain 时间），`post_drain_callbacks` 再等待 uvicorn 线程结束（drain 时间 + 2 秒，超时打 warning）。

**限制**：

- uvicorn 的事件循环在 SDK 线程模型之外：MCP 请求在 uvicorn 线程里执行 server filter 和能力函数，不占用框架的 handle 线程，也不受其排队/过载保护控制。
- 在 MCP 能力函数里用 trpc 客户端调用下游时，客户端连接属于 uvicorn 线程的 loop；不要把在别的 loop 上创建的 HTTP client session 跨 loop 复用。

## 注意事项

- **协议**：服务端与客户端的 `protocol` 都用 `http_mcp`；自定义 selector 返回的 `node.protocol` 也要是 `http_mcp`，否则 codec 会被降级。
- **base_url**：客户端与服务端要一致，否则路径拼接 404。
- **SSE 模式**：单进程即可；多进程（separate / peer）必须配置 redis 且 `stateless_http: true`，否则自动降为 1 个进程（见下文“进程/线程模型”）。
- **Streamable-HTTP 模式**：
  - 有状态（`stateless_http: false`）：只能单进程，暂不支持 redis。
  - 无状态（`stateless_http: true`）：支持多进程，但不支持 `list_roots` 调用。
- **`list_roots` 支持条件**：SSE 模式都支持；Streamable-HTTP 必须 `stateless_http: false` 且单进程。
- **不支持 stdio 传输**（配了会直接报错）。

## 目录参考

- `trpc_mcp/tools.py` / `resources.py` / `prompts.py`：能力注册装饰器与注册表。
- `trpc_mcp/_trpc_mcp_server.py`：`TrpcMcpServer`（继承 `FastMCP`），含 service 隔离、tool filter、call_tool 等。
- `trpc_mcp/_trpc_server_transport.py`：`http_mcp` 协议启动器 `start_mcp`，每进程构建 MCP app、起 uvicorn 线程并挂接优雅退出回调。
- `trpc_mcp/service_desc.py`：`register_trpc_mcp_server`，按进程模型修正进程数。
- `trpc_mcp/_sse_transport.py`：SSE 传输（含多进程 redis 同步）。
- `trpc_mcp/mcp_client.py`：客户端 `McpProxy`。
- `trpc_mcp/_httpx_transport.py`：把官方 MCP SDK 的 httpx 请求桥接到 trpc 客户端（含 streamable 传输版本自适应）。
- `trpc_mcp/_codec.py`：`http_mcp` 协议的客户端/服务端编解码。
- `trpc_mcp/_compat.py`：可选 `mcp.types` 符号（如 `Icon`）的版本兼容垫片。
- `trpc_mcp/mcp_api.py` / `utils.py`：上下文读取与 HTTP 头/参数注入等工具。
- `examples/`：完整可运行示例，见 [`examples/README.md`](examples/README.md)。
- `docs/troubleshooting.md`：排障备忘；`docs/compatibility_old_vs_new.md`：新旧实现兼容性对比。

## 常见问题

### 客户端 `protocol` 配成 `http` 可以吗？

建议统一用 `http_mcp`。若客户端或自定义 selector 退回成普通 `http`，会把 MCP 专用 codec 降级，导致 SSE POST 的 `202 ACCEPTED` 被当成错误。`McpProxy` 内部会强制 `http_mcp`，但 selector 返回的 `node.protocol` 仍需是 `http_mcp`。

### 为什么 streamable-http 测 `list_roots` 失败？

`list_roots` 是服务端反向请求客户端，依赖有状态 session。Streamable-HTTP 下必须 `stateless_http: false` 且单进程；stateless 或多进程会拿不到同一个 session。SSE 模式不受此限制。

### sse 协议下，多进程为什么必须配 redis？

`sse-starlette` 的 session 是进程内状态。多进程时 POST 命中的进程与持有 SSE 长连接的进程可能不是同一个，需要 redis 做跨进程的消息/会话同步。

### 装了较低版本的 mcp，新特性会报错吗？

不会。`icons`/`meta`/resource `annotations`、`call_tool(meta=)` 等是较高版本才有的；trpc-mcp 按已安装 SDK 的签名做自适应过滤，低版本会自动忽略并打印告警，不会抛 `TypeError`。详见 `docs/troubleshooting.md`。
