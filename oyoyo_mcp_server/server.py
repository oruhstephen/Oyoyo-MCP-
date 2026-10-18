from fastmcp import FastMCP
from woocommerce import API
import requests
import os

mcp = FastMCP(name="WooCommerce Multi-Store Engine")

# Initialize connections for both stores
stores = {
    "oyoyo": API(
        url="https://www.oyoyo.app3.uk",
        consumer_key=os.environ.get("ck_bd738a7fc8676be2230820be9ed7ed6d06687505"),
        consumer_secret=os.environ.get("cs_66c70fe0c0763795c3ac8e5423a9d9bf1b4c95cf"),
        version="wc/v3"
    ),
    "creativeulo": API(
        url="https://www.creativeulo.app3.uk",
        consumer_key=os.environ.get("ck_e4a13a3ad0d5fd5bf465c1497a5676693c56e4b7"),
        consumer_secret=os.environ.get("cs_bd24237493af6e56e19a4235dbf69d3ed8135c05"),
        version="wc/v3"
    )
}

def get_store_api(store_name: str) -> API:
    """Helper function to route the request to the correct store."""
    store_key = store_name.lower().strip()
    if store_key not in stores:
        raise ValueError(f"Unknown store: {store_name}. Valid options are 'oyoyo' or 'creativeulo'.")
    return stores[store_key]

@mcp.tool
def get_product(store_name: str, product_id: int) -> dict:
    """Fetches details for a single product from either Oyoyo or Creativeulo."""
    wcapi = get_store_api(store_name)
    response = wcapi.get(f"products/{product_id}")
    return response.json()

@mcp.tool
def update_product_description(store_name: str, product_id: int, new_description: str) -> dict:
    """Updates the main description of a WooCommerce product on the specified store."""
    wcapi = get_store_api(store_name)
    data = {"description": new_description}
    response = wcapi.put(f"products/{product_id}", data)
    return {"status": "success" if response.status_code == 200 else "error"}

@mcp.tool
def publish_to_n8n(store_name: str, product_name: str, social_copy: str, image_urls: list) -> str:
    """Sends the generated social media content and images to n8n for publishing."""
    # We pass the store_name to n8n so the workflow knows which social accounts to post to
    n8n_webhook_url = os.environ.get("https://go90ng-n8n.eq7icp.easypanel.host/webhook/2e33cd0a-f0c8-41cd-8117-5221eebfbb92")
    payload = {
        "store": store_name,
        "product": product_name, 
        "social_copy": social_copy, 
        "images": image_urls
    }
    response = requests.post(n8n_webhook_url, json=payload)
    return "Successfully sent to n8n" if response.status_code == 200 else "Failed to send to n8n"

if __name__ == "__main__":
    mcp.run(host="0.0.0.0", port=9000)
