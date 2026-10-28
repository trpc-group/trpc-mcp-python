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
# list_allowed_directories can be replaced with the method you want

response=$(curl -sS -X POST \
    -H "Content-Type: application/json" \
    -d "$json_data" \
    "$url")

# Format the response when jq is available
if command -v jq &> /dev/null; then
    echo "$response" | jq .
else
    echo "$response"
fi

# Print debug info
echo -e "\n请求已发送至: $url"

# Fetch session_id. base_url is optional.
# curl -H "Accept: text/event-stream" http://${ip}:${port}${base_url}/sse

# Send the request
# ./send_req.sh ${ip}:${port} ${session_id}
