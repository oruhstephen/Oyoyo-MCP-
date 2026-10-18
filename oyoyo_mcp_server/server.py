from fastmcp import FastMCP
from woocommerce import API
import requests
import os

# Initialize the MCP Server
mcp = FastMCP(name="WooCommerce Custom Engine")

# Connect to WooCommerce REST API using Environment Variables
wcapi = API(
    url=os.environ.get("https://www.oyoyo.app3.uk/"),
    consumer_key=os.environ.get("ck_bd738a7fc8676be2230820be9ed7ed6d06687505"),
    consumer_secret=os.environ.get("cs_66c70fe0c0763795c3ac8e5423a9d9bf1b4c95cf"),
    version="wc/v3"
)

@mcp.tool
def get_product(product_id: int) -> dict:
    """Fetches details for a single product from WooCommerce."""
    response = wcapi.get(f"products/{product_id}")
    return response.json()

@mcp.tool
def update_product_description(product_id: int, new_description: str) -> dict:
    """Updates the main description of a WooCommerce product."""
    data = {"description": new_description}
    response = wcapi.put(f"products/{product_id}", data)
    return {"status": "success" if response.status_code == 200 else "error"}

@mcp.tool
def publish_to_n8n(product_name: str, social_copy: str, image_urls: list) -> str:
    """Sends the generated social media content and images to n8n for publishing."""
    n8n_webhook_url = os.environ.get("https://go90ng-n8n.eq7icp.easypanel.host/webhook/2e33cd0a-f0c8-41cd-8117-5221eebfbb92")
    payload = {"product": product_name, "social_copy": social_copy, "images": image_urls}
    response = requests.post(n8n_webhook_url, json=payload)
    return "Successfully sent to n8n" if response.status_code == 200 else "Failed to send to n8n"

if __name__ == "__main__":
    # Start the server listening on all interfaces at port 8000
    mcp.run(host="0.0.0.0", port=8000)