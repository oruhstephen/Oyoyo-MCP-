import os
import requests
from mcp.server import Server
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

# Register tools using the standard decorator
@mcp.tool()
async def get_product(store_name: str, product_id: int) -> str:
    """Fetches details for a single product from either Oyoyo or Creativeulo."""
    wcapi = get_store_api(store_name)
    response = wcapi.get(f"products/{product_id}")
    return str(response.json())

@mcp.tool()
async def publish_to_n8n(store_name: str, product_name: str, social_copy: str, image_urls: list[str]) -> str:
    """Sends the generated social media content and images to n8n for publishing."""
    n8n_webhook_url = os.environ.get("N8N_WEBHOOK_URL")
    payload = {
        "store": store_name,
        "product": product_name,
        "social_copy": social_copy,
        "images": image_urls
    }
    response = requests.post(n8n_webhook_url, json=payload)
    return "Successfully sent to n8n" if response.status_code == 200 else f"Failed: {response.status_code}"

# Configure SSE endpoints using the official Transport
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
