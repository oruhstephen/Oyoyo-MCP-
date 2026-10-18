import os
import requests
from mcp.server import Server
import mcp.types as types
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route
import uvicorn
from woocommerce import API

# Initialize the low-level MCP Server
mcp = Server("WooCommerce Multi-Store Engine")

# Connections initialized with your exact keys and URLs
stores = {
    "oyoyo": API(
        url="https://www.oyoyo.app3.uk",
        consumer_key="ck_bd738a7fc8676be2230820be9ed7ed6d06687505",
        consumer_secret="cs_66c70fe0c0763795c3ac8e5423a9d9bf1b4c95cf",
        version="wc/v3"
    ),
    "creativeulo": API(
        url="https://www.creativeulo.app3.uk",
        consumer_key="ck_e4a13a3ad0d5fd5bf465c1497a5676693c56e4b7",
        consumer_secret="cs_bd24237493af6e56e19a4235dbf69d3ed8135c05",
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
                    "store_name": {"type": "string", "description": "The name of the store (oyoyo or creativeulo)"},
                    "product_id": {"type": "integer", "description": "The WooCommerce product ID"}
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
        n8n_webhook_url = "https://go90ng-n8n.eq7icp.easypanel.host/webhook/2e33cd0a-f0c8-41cd-8117-5221eebfbb92"
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

# Configure SSE endpoints to handle both normal traffic and Gemini's POST probe
sse = SseServerTransport("/messages")

async def handle_sse(request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await mcp.run(streams[0], streams[1], mcp.create_initialization_options())

async def handle_messages(request):
    await sse.handle_post_message(request.scope, request.receive, request._send)

app = Starlette(routes=[
    Route("/sse", endpoint=handle_sse, methods=["GET", "HEAD"]),
    Route("/messages", endpoint=handle_messages, methods=["POST"]),
    Route("/sse", endpoint=handle_messages, methods=["POST"]) # Intercepts Gemini's 405 error check
])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
