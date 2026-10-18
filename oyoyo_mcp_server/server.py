from fastmcp import FastMCP
from woocommerce import API
from starlette.requests import Request
from starlette.responses import JSONResponse
import requests

mcp = FastMCP("WooCommerce Multi-Store Engine")

# Connections initialized with your exact keys properly formatted as strings
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

@mcp.tool()
def get_product(store_name: str, product_id: int) -> dict:
    """Fetches details for a single product from either Oyoyo or Creativeulo."""
    wcapi = get_store_api(store_name)
    response = wcapi.get(f"products/{product_id}")
    return response.json()

@mcp.tool()
def publish_to_n8n(store_name: str, product_name: str, social_copy: str, image_urls: list[str]) -> str:
    """Sends the generated social media content and images to n8n for publishing."""
    n8n_webhook_url = "https://go90ng-n8n.eq7icp.easypanel.host/webhook/2e33cd0a-f0c8-41cd-8117-5221eebfbb92"
    payload = {
        "store": store_name,
        "product": product_name,
        "social_copy": social_copy,
        "images": image_urls
    }
    response = requests.post(n8n_webhook_url, json=payload)
    return "Successfully sent to n8n" if response.status_code == 200 else f"Failed: {response.status_code}"

# Intercept Gemini's HTTP POST probe to prevent the '405 Method Not Allowed' UI error
@mcp.custom_route("/sse", methods=["POST"])
async def sse_probe_handler(request: Request):
    return JSONResponse({"status": "ok"})

if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=9000)
