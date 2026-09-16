#!/bin/bash

if [ $# -ne 2 ]; then
    echo "用法: $0 <IP:Port> <SessionID>"
    exit 1
fi

ip_port=$1
sessionId=$2
base_url="/"

url="http://${ip_port}${base_url}messages/?session_id=${sessionId}"

json_data=$(cat <<EOF
{
    "jsonrpc": "2.0",
    "method": "notifications/initialized"
}
EOF
)

response=$(curl -sS -X POST \
    -H "Content-Type: application/json" \
    -d "$json_data" \
    "$url")

json_data=$(cat <<EOF
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "show_tool",
        "arguments": {"text": "Hello, World!"}
    }
}
EOF
)
# list_allowed_directories 可以换成期望的方法

response=$(curl -sS -X POST \
    -H "Content-Type: application/json" \
    -d "$json_data" \
    "$url")

# 处理响应（可选：用 jq 格式化输出）
if command -v jq &> /dev/null; then
    echo "$response" | jq .
else
    echo "$response"
fi

# 输出调试信息
echo -e "\n请求已发送至: $url"

# 获取 session_id, base_url可以不需要
# curl -H "Accept: text/event-stream" http://${ip}:${port}${base_url}/sse

# 发送请求
# ./send_req.sh ${ip}:${port} ${session_id}
