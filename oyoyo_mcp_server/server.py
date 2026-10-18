import os
import logging
import requests
from mcp.server.fastmcp import FastMCP
from woocommerce import API

logging.basicConfig(level=logging.INFO)

mcp = FastMCP(
    "WooCommerce Multi-Store Engine",
    host="0.0.0.0",
    port=9000,
    stateless_http=True,
)

stores = {
    "oyoyo": API(
        url=os.environ.get("OYOYO_URL"),
        consumer_key=os.environ.get("OYOYO_KEY"),
        consumer_secret=os.environ.get("OYOYO_SECRET"),
        version="wc/v3",
    ),
    "creativeulo": API(
        url=os.environ.get("CREATIVEULO_URL"),
        consumer_key=os.environ.get("CREATIVEULO_KEY"),
        consumer_secret=os.environ.get("CREATIVEULO_SECRET"),
        version="wc/v3",
    ),
}

def get_store_api(store_name: str) -> API:
    store_key = store_name.lower().strip()
    if store_key not in stores:
        raise ValueError(f"Unknown store: {store_name}.")
    return stores[store_key]

@mcp.tool()
def get_product(store_name: str, product_id: int) -> str:
    """Fetches details for a single product from either Oyoyo or Creativeulo."""
    wcapi = get_store_api(store_name)
    response = wcapi.get(f"products/{product_id}")
    return str(response.json())

@mcp.tool()
def publish_to_n8n(store_name: str, product_name: str, social_copy: str, image_urls: list[str]) -> str:
    """Sends the generated social media content and images to n8n for publishing."""
    n8n_webhook_url = os.environ.get("N8N_WEBHOOK_URL")
    payload = {
        "store": store_name,
        "product": product_name,
        "social_copy": social_copy,
        "images": image_urls,
    }
    response = requests.post(n8n_webhook_url, json=payload, timeout=30)
    return "Successfully sent to n8n" if response.status_code == 200 else f"Failed: {response.status_code}"

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
