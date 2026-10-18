import requests
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
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

# Define Tools
@mcp.list_tools()
async def list_tools() -> list:
    return [
        {
            "name": "get_product",
            "description": "Fetches details for a single product from either Oyoyo or Creativeulo.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "store_name": {"type": "string", "description": "The name of the store (oyoyo or creativeulo)"},
                    "product_id": {"type": "integer", "description": "The WooCommerce product ID"}
                },
                "required": ["store_name", "product_id"]
            }
        },
        {
            "name": "publish_to_n8n",
            "description": "Sends the generated social media content and images to n8n for publishing.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "store_name": {"type": "string"},
                    "product_name": {"type": "string"},
                    "social_copy": {"type": "string"},
                    "image_urls": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["store_name", "product_name", "social_copy", "image_urls"]
            }
        }
    ]

@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name == "get_product":
        wcapi = get_store_api(arguments["store_name"])
        response = wcapi.get(f"products/{arguments['product_id']}")
        return [{"type": "text", "text": str(response.json())}]
        
    elif name == "publish_to_n8n":
        # Your exact n8n webhook URL hardcoded
        n8n_webhook_url = "https://go90ng-n8n.eq7icp.easypanel.host/webhook/2e33cd0a-f0c8-41cd-8117-5221eebfbb92"
        payload = {
            "store": arguments["store_name"],
            "product": arguments["product_name"],
            "social_copy": arguments["social_copy"],
            "images": arguments["image_urls"]
        }
        response = requests.post(n8n_webhook_url, json=payload)
        status = "Successfully sent to n8n" if response.status_code == 200 else f"Failed: {response.status_code}"
        return [{"type": "text", "text": status}]
    
    raise ValueError(f"Unknown tool: {name}")


# Define the SSE Transport and Web Server
sse_transport = None

async def sse_handler(request):
    global sse_transport
    sse_transport = SseServerTransport("/messages")
    return await sse_transport.handle_sse(request)

async def messages_handler(request):
    global sse_transport
    if sse_transport is None:
        return JSONResponse({"error": "No active SSE connection"}, status_code=400)
    return await sse_transport.handle_post_message(request)

app = Starlette(routes=[
    Route("/sse", endpoint=sse_handler, methods=["GET", "HEAD"]),
    Route("/messages", endpoint=messages_handler, methods=["POST"]),
])

if __name__ == "__main__":
    import asyncio
    
    async def start_mcp():
        global sse_transport
        while True:
            if sse_transport:
                await mcp.run(sse_transport, mcp.create_initialization_options())
            await asyncio.sleep(0.1)

    loop = asyncio.get_event_loop()
    loop.create_task(start_mcp())
    
    # Run the web server on port 9000
    uvicorn.run(app, host="0.0.0.0", port=9000)
