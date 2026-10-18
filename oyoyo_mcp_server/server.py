import os
import requests
from mcp.server import Server
import mcp.types as types
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route
import uvicorn
from woocommerce import API

# Initialize the official MCP Server
mcp = Server("WooCommerce Multi-Store Engine")

# Connections securely initialized using environment variables
stores = {
    "oyoyo": API(
        url=os.environ.get("OYOYO_URL"),
        consumer_key=os.environ.get("OYOYO_KEY"),
        consumer_secret=os.environ.get("OYOYO_SECRET"),
        version="wc/v3"
    ),
    "creativeulo": API(
        url=os.environ.get("CREATIVEULO_URL"),
        consumer_key=os.environ.get("CREATIVEULO_KEY"),
        consumer_secret=os.environ.get("CREATIVEULO_SECRET"),
        version="wc/v3"
    )
}

def get_store_api(store_name: str) -> API:
    store_key = store_name.lower().strip()
    if store_key not in stores:
        raise ValueError(f"Unknown store: {store_name}.")
    return stores[store_key]

@mcp.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_product",
            description="Fetches details for a single product from either Oyoyo or Creativeulo.",
            inputSchema={
                "type": "object",
                "properties": {
                    "store_name": {"type": "string"},
                    "product_id": {"type": "integer"}
                },
                "required": ["store_name", "product_id"]
            }
        ),
        types.Tool(
            name="publish_to_n8n",
            description="Sends the generated social media content and images to n8n for publishing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "store_name": {"type": "string"},
                    "product_name": {"type": "string"},
                    "social_copy": {"type": "string"},
                    "image_urls": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["store_name", "product_name", "social_copy", "image_urls"]
            }
        )
    ]

@mcp.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "get_product":
        wcapi = get_store_api(arguments["store_name"])
        response = wcapi.get(f"products/{arguments['product_id']}")
        return [types.TextContent(type="text", text=str(response.json()))]
        
    elif name == "publish_to_n8n":
        n8n_webhook_url = os.environ.get("N8N_WEBHOOK_URL")
        payload = {
            "store": arguments["store_name"],
            "product": arguments["product_name"],
            "social_copy": arguments["social_copy"],
            "images": arguments["image_urls"]
        }
        response = requests.post(n8n_webhook_url, json=payload)
        status = "Successfully sent to n8n" if response.status_code == 200 else f"Failed: {response.status_code}"
        return [types.TextContent(type="text", text=status)]
    
    raise ValueError(f"Unknown tool: {name}")

# Correctly configure SSE endpoints using the official Transport
sse = SseServerTransport("/messages")

async def handle_sse(request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await mcp.run(streams[0], streams[1], mcp.create_initialization_options())

async def handle_messages(request):
    await sse.handle_post_message(request.scope, request.receive, request._send)

# Map the exact routes required by the protocol
app = Starlette(routes=[
    Route("/sse", endpoint=handle_sse, methods=["GET", "HEAD"]),
    Route("/messages", endpoint=handle_messages, methods=["POST"]),
])

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=9000)
