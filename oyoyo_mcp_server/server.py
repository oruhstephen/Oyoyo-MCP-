import os
import json
import time
import logging
from typing import Optional

import requests
from mcp.server.fastmcp import FastMCP
from woocommerce import API

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("woo-mcp")

mcp = FastMCP(
    "WooCommerce Multi-Store Engine",
    host="0.0.0.0",
    port=9000,
    stateless_http=True,
)

# ---------------------------------------------------------------- stores

def _build_stores() -> dict:
    found = {}
    for name in ("oyoyo", "creativeulo"):
        p = name.upper()
        url = os.environ.get(f"{p}_URL")
        key = os.environ.get(f"{p}_KEY")
        secret = os.environ.get(f"{p}_SECRET")
        if url and key and secret:
            found[name] = API(url=url, consumer_key=key, consumer_secret=secret,
                              version="wc/v3", timeout=30)
        else:
            log.warning("Store '%s' skipped: missing %s_URL/KEY/SECRET", name, p)
    return found

stores = _build_stores()

def get_store_api(store_name: str) -> API:
    key = store_name.lower().strip()
    if key not in stores:
        raise ValueError(f"Unknown store '{store_name}'. Available: {', '.join(stores) or 'none'}")
    return stores[key]

# ------------------------------------------------- dynamic field handling

# Compact default views. Override without code changes via env vars,
# e.g. WOO_FIELDS_PRODUCT="id,name,price,sku,meta_data"
DEFAULT_FIELDS = {
    "product": ["id", "name", "slug", "permalink", "type", "status", "sku", "price",
                "regular_price", "sale_price", "stock_status", "stock_quantity",
                "manage_stock", "short_description", "categories", "images"],
    "order": ["id", "number", "status", "currency", "total", "date_created",
              "payment_method_title", "billing", "shipping", "line_items", "customer_note"],
    "customer": ["id", "email", "first_name", "last_name", "username",
                 "date_created", "orders_count", "total_spent", "billing"],
    "review": ["id", "product_id", "product_name", "status", "reviewer",
               "rating", "review", "date_created"],
    "coupon": ["id", "code", "discount_type", "amount", "date_expires",
               "usage_count", "usage_limit", "individual_use"],
}
for _kind in DEFAULT_FIELDS:
    _env = os.environ.get(f"WOO_FIELDS_{_kind.upper()}")
    if _env:
        DEFAULT_FIELDS[_kind] = [f.strip() for f in _env.split(",") if f.strip()]

RESOURCE_ENDPOINTS = {"product": "products", "order": "orders", "customer": "customers",
                      "coupon": "coupons", "review": "products/reviews"}

def _view(kind: str, fields: Optional[str]):
    """Returns (field_list_or_None, compact).
    None -> default compact view; 'all' -> everything; 'a,b,c' -> exactly those, raw."""
    if fields is None or not fields.strip():
        return DEFAULT_FIELDS[kind], True
    if fields.strip().lower() == "all":
        return None, False
    return [f.strip() for f in fields.split(",") if f.strip()], False

def _slim(item, fields, compact):
    if not isinstance(item, dict):
        return item
    out = {k: item[k] for k in fields if k in item}
    if compact:  # shrink bulky nested objects in the default view only
        if isinstance(out.get("images"), list):
            out["images"] = [i.get("src") for i in out["images"] if isinstance(i, dict)]
        if isinstance(out.get("categories"), list):
            out["categories"] = [{"id": c.get("id"), "name": c.get("name")}
                                 for c in out["categories"] if isinstance(c, dict)]
        if isinstance(out.get("line_items"), list):
            out["line_items"] = [{"product_id": li.get("product_id"), "name": li.get("name"),
                                  "quantity": li.get("quantity"), "total": li.get("total")}
                                 for li in out["line_items"] if isinstance(li, dict)]
    return out

def _call(store: str, method: str, endpoint: str, data=None, params=None,
          fields=None, compact=False) -> str:
    """Runs a WooCommerce request and returns JSON text (errors included)."""
    try:
        api = get_store_api(store)
        params = dict(params or {})
        if method == "GET":
            if fields:
                params["_fields"] = ",".join(fields)  # server-side filtering
            r = api.get(endpoint, params=params)
        elif method == "POST":
            r = api.post(endpoint, data or {})
        elif method == "PUT":
            r = api.put(endpoint, data or {})
        else:
            raise ValueError(f"Unsupported method {method}")
    except (ValueError, requests.RequestException) as e:
        return json.dumps({"error": str(e)})

    try:
        body = r.json()
    except ValueError:
        body = r.text
    if r.status_code >= 400:
        return json.dumps({"error": True, "status": r.status_code, "details": body})
    if fields:
        body = [_slim(i, fields, compact) for i in body] if isinstance(body, list) \
            else _slim(body, fields, compact)
    return json.dumps(body, ensure_ascii=False, default=str)

def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}

# ------------------------------------------------- dynamic order statuses

_status_cache: dict = {}

def _order_statuses(store: str):
    """Live list of order status slugs for a store (cached 10 min). None if unavailable."""
    now = time.time()
    cached = _status_cache.get(store)
    if cached and now - cached[0] < 600:
        return cached[1]
    try:
        r = get_store_api(store).get("reports/orders/totals")
        if r.status_code == 200:
            slugs = {s["slug"].removeprefix("wc-") for s in r.json()
                     if isinstance(s, dict) and s.get("slug")}
            if slugs:
                _status_cache[store] = (now, slugs)
                return slugs
    except Exception as e:  # network or unexpected shape: fall back to Woo-side validation
        log.warning("Could not fetch order statuses for %s: %s", store, e)
    return None

# ------------------------------------------------------------------ meta

@mcp.tool()
def list_stores() -> str:
    """Lists the store names this server can talk to."""
    return json.dumps(list(stores))

@mcp.tool()
def describe_fields(store_name: str, resource: str) -> str:
    """Lists every field name WooCommerce currently returns for a resource
    (product, order, customer, coupon, review), sampled from one live record, plus the
    default view. Use it to discover new or plugin fields, then pass them in `fields`.
    Note: fields can differ between record types (e.g. variable vs simple products)."""
    endpoint = RESOURCE_ENDPOINTS.get(resource.lower().strip())
    if not endpoint:
        return json.dumps({"error": f"resource must be one of {list(RESOURCE_ENDPOINTS)}"})
    raw = _call(store_name, "GET", endpoint, params={"per_page": 1})
    try:
        items = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(items, list) or not items:
        return raw if not isinstance(items, list) else json.dumps({"error": "No records to sample."})
    return json.dumps({"resource": resource, "available_fields": sorted(items[0].keys()),
                       "default_view": DEFAULT_FIELDS[resource.lower().strip()]})

@mcp.tool()
def get_order_statuses(store_name: str) -> str:
    """Lists the order statuses this store currently supports, including custom ones."""
    statuses = _order_statuses(store_name)
    if statuses is None:
        return json.dumps({"error": "Could not fetch statuses; WooCommerce will validate any status you try."})
    return json.dumps(sorted(statuses))

# -------------------------------------------------------------- products
# Every read tool takes `fields`: omit for the compact default view,
# "all" for everything, or a comma list such as "id,name,meta_data".

@mcp.tool()
def get_product(store_name: str, product_id: int, fields: Optional[str] = None) -> str:
    """Fetches a single product. fields: optional comma list, or 'all'."""
    f, c = _view("product", fields)
    return _call(store_name, "GET", f"products/{product_id}", fields=f, compact=c)

@mcp.tool()
def list_products(store_name: str, search: Optional[str] = None,
                  category_id: Optional[int] = None, status: str = "publish",
                  stock_status: Optional[str] = None, on_sale: Optional[bool] = None,
                  per_page: int = 20, page: int = 1, fields: Optional[str] = None) -> str:
    """Lists or searches products. status: publish, draft, private, pending, any.
    stock_status: instock, outofstock, onbackorder. fields: optional comma list, or 'all'."""
    f, c = _view("product", fields)
    params = _clean({"search": search, "category": category_id, "status": status,
                     "stock_status": stock_status, "on_sale": on_sale,
                     "per_page": min(per_page, 100), "page": page})
    return _call(store_name, "GET", "products", params=params, fields=f, compact=c)

@mcp.tool()
def get_low_stock_products(store_name: str, threshold: int = 5, per_page: int = 100,
                           fields: Optional[str] = None) -> str:
    """Published products whose managed stock is at or below the threshold.
    fields: optional comma list, or 'all'."""
    f, c = _view("product", fields)
    needed = sorted(set(f) | {"manage_stock", "stock_quantity"}) if f else None
    raw = _call(store_name, "GET", "products",
                params={"status": "publish", "per_page": min(per_page, 100)},
                fields=needed, compact=False)
    try:
        items = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(items, list):
        return raw
    low = [p for p in items if p.get("manage_stock") and p.get("stock_quantity") is not None
           and p["stock_quantity"] <= threshold]
    return json.dumps([_slim(p, f, c) if f else p for p in low], ensure_ascii=False)

@mcp.tool()
def get_product_variations(store_name: str, product_id: int, fields: Optional[str] = None) -> str:
    """Lists variations (sizes, colours...) of a variable product. fields: comma list, or 'all'."""
    if fields is None or not fields.strip():
        f = ["id", "sku", "price", "regular_price", "sale_price",
             "stock_status", "stock_quantity", "attributes"]
    else:
        f = None if fields.strip().lower() == "all" else [x.strip() for x in fields.split(",")]
    return _call(store_name, "GET", f"products/{product_id}/variations",
                 params={"per_page": 100}, fields=f)

@mcp.tool()
def create_product(store_name: str, name: str, regular_price: str,
                   description: str = "", short_description: str = "",
                   category_ids: Optional[list[int]] = None,
                   image_urls: Optional[list[str]] = None,
                   sku: Optional[str] = None, status: str = "draft",
                   extra: Optional[dict] = None) -> str:
    """Creates a simple product (defaults to DRAFT). `extra` is any additional raw
    WooCommerce product fields to send, e.g. {"tags": [{"id": 5}], "weight": "1.2"}."""
    data = _clean({
        "name": name, "type": "simple", "regular_price": regular_price,
        "description": description, "short_description": short_description,
        "sku": sku, "status": status,
        "categories": [{"id": cid} for cid in category_ids] if category_ids else None,
        "images": [{"src": u} for u in image_urls] if image_urls else None,
    })
    data.update(extra or {})
    return _call(store_name, "POST", "products", data=data,
                 fields=DEFAULT_FIELDS["product"], compact=True)

@mcp.tool()
def update_product(store_name: str, product_id: int, name: Optional[str] = None,
                   regular_price: Optional[str] = None, sale_price: Optional[str] = None,
                   description: Optional[str] = None, short_description: Optional[str] = None,
                   status: Optional[str] = None, category_ids: Optional[list[int]] = None,
                   extra: Optional[dict] = None) -> str:
    """Updates a product; only fields you pass change. sale_price="" clears a sale.
    `extra` = any additional raw WooCommerce fields, e.g. {"meta_data": [{"key": "x", "value": "y"}]}."""
    data = _clean({
        "name": name, "regular_price": regular_price, "sale_price": sale_price,
        "description": description, "short_description": short_description,
        "status": status,
        "categories": [{"id": cid} for cid in category_ids] if category_ids is not None else None,
    })
    data.update(extra or {})
    if not data:
        return json.dumps({"error": "No fields to update."})
    return _call(store_name, "PUT", f"products/{product_id}", data=data,
                 fields=DEFAULT_FIELDS["product"], compact=True)

@mcp.tool()
def update_stock(store_name: str, product_id: int, stock_quantity: int) -> str:
    """Sets the stock quantity for a product and turns on stock management."""
    return _call(store_name, "PUT", f"products/{product_id}",
                 data={"manage_stock": True, "stock_quantity": stock_quantity},
                 fields=DEFAULT_FIELDS["product"], compact=True)

@mcp.tool()
def list_categories(store_name: str, search: Optional[str] = None) -> str:
    """Lists product categories with IDs and product counts."""
    return _call(store_name, "GET", "products/categories",
                 params=_clean({"search": search, "per_page": 100}),
                 fields=["id", "name", "slug", "parent", "count"])

@mcp.tool()
def list_product_reviews(store_name: str, product_id: Optional[int] = None,
                         status: str = "all", per_page: int = 20,
                         fields: Optional[str] = None) -> str:
    """Lists product reviews. status: all, approved, hold, spam, trash. fields: comma list, or 'all'."""
    f, c = _view("review", fields)
    params = _clean({"product": [product_id] if product_id else None,
                     "status": status, "per_page": min(per_page, 100)})
    return _call(store_name, "GET", "products/reviews", params=params, fields=f, compact=c)

# ---------------------------------------------------------------- orders

@mcp.tool()
def list_orders(store_name: str, status: str = "any", after: Optional[str] = None,
                before: Optional[str] = None, customer_id: Optional[int] = None,
                per_page: int = 20, page: int = 1, fields: Optional[str] = None) -> str:
    """Lists orders. status: 'any' or a status slug (see get_order_statuses).
    after/before: ISO dates like 2026-10-01T00:00:00. fields: comma list, or 'all'."""
    f, c = _view("order", fields)
    params = _clean({"status": status.removeprefix("wc-"), "after": after, "before": before,
                     "customer": customer_id, "per_page": min(per_page, 100), "page": page})
    return _call(store_name, "GET", "orders", params=params, fields=f, compact=c)

@mcp.tool()
def get_order(store_name: str, order_id: int, fields: Optional[str] = None) -> str:
    """Fetches a single order. fields: optional comma list, or 'all'."""
    f, c = _view("order", fields)
    return _call(store_name, "GET", f"orders/{order_id}", fields=f, compact=c)

@mcp.tool()
def update_order_status(store_name: str, order_id: int, status: str) -> str:
    """Changes an order's status (can trigger customer emails and stock changes).
    Valid statuses are fetched live from the store; see get_order_statuses."""
    status = status.strip().removeprefix("wc-")
    valid = _order_statuses(store_name)
    if valid is not None and status not in valid:
        return json.dumps({"error": f"Invalid status '{status}'.", "valid": sorted(valid)})
    return _call(store_name, "PUT", f"orders/{order_id}", data={"status": status},
                 fields=DEFAULT_FIELDS["order"], compact=True)

@mcp.tool()
def add_order_note(store_name: str, order_id: int, note: str,
                   customer_note: bool = False) -> str:
    """Adds a note to an order. customer_note=True also emails it to the customer."""
    return _call(store_name, "POST", f"orders/{order_id}/notes",
                 data={"note": note, "customer_note": customer_note})

# ------------------------------------------------------------- customers

@mcp.tool()
def list_customers(store_name: str, search: Optional[str] = None,
                   email: Optional[str] = None, per_page: int = 20,
                   fields: Optional[str] = None) -> str:
    """Lists or searches customers by name/email. fields: comma list, or 'all'."""
    f, c = _view("customer", fields)
    params = _clean({"search": search, "email": email, "per_page": min(per_page, 100)})
    return _call(store_name, "GET", "customers", params=params, fields=f, compact=c)

@mcp.tool()
def get_customer(store_name: str, customer_id: int, fields: Optional[str] = None) -> str:
    """Fetches a single customer. fields: optional comma list, or 'all'."""
    f, c = _view("customer", fields)
    return _call(store_name, "GET", f"customers/{customer_id}", fields=f, compact=c)

# --------------------------------------------------------------- coupons

@mcp.tool()
def list_coupons(store_name: str, search: Optional[str] = None, per_page: int = 20,
                 fields: Optional[str] = None) -> str:
    """Lists discount coupons. fields: optional comma list, or 'all'."""
    f, c = _view("coupon", fields)
    params = _clean({"search": search, "per_page": min(per_page, 100)})
    return _call(store_name, "GET", "coupons", params=params, fields=f, compact=c)

@mcp.tool()
def create_coupon(store_name: str, code: str, amount: str,
                  discount_type: str = "percent", date_expires: Optional[str] = None,
                  usage_limit: Optional[int] = None, individual_use: bool = True,
                  extra: Optional[dict] = None) -> str:
    """Creates a coupon. discount_type is validated by WooCommerce itself (usually percent,
    fixed_cart, fixed_product). date_expires: ISO date. `extra` = any other raw coupon fields."""
    data = _clean({"code": code, "amount": amount, "discount_type": discount_type,
                   "date_expires": date_expires, "usage_limit": usage_limit,
                   "individual_use": individual_use})
    data.update(extra or {})
    return _call(store_name, "POST", "coupons", data=data,
                 fields=DEFAULT_FIELDS["coupon"], compact=True)

# --------------------------------------------------------------- reports

@mcp.tool()
def get_sales_report(store_name: str, period: str = "month",
                     date_min: Optional[str] = None, date_max: Optional[str] = None) -> str:
    """Sales totals. period: week, month, last_month, year; or date_min/date_max
    (YYYY-MM-DD), which override period."""
    params = {"date_min": date_min, "date_max": date_max} if (date_min or date_max) \
        else {"period": period}
    return _call(store_name, "GET", "reports/sales", params=_clean(params))

@mcp.tool()
def get_top_sellers(store_name: str, period: str = "month") -> str:
    """Best-selling products. period: week, month, last_month, year."""
    return _call(store_name, "GET", "reports/top_sellers", params={"period": period})

# ------------------------------------------------------------------- n8n

def _post_to_n8n(payload: dict) -> str:
    url = os.environ.get("N8N_WEBHOOK_URL")
    if not url:
        return "Failed: N8N_WEBHOOK_URL is not set"
    try:
        r = requests.post(url, json=payload, timeout=30)
    except requests.RequestException as e:
        return f"Failed: {e}"
    return "Successfully sent to n8n" if r.status_code == 200 else f"Failed: {r.status_code}"

@mcp.tool()
def publish_to_n8n(store_name: str, product_name: str, social_copy: str,
                   image_urls: list[str]) -> str:
    """Sends generated social media content and images to n8n for publishing."""
    return _post_to_n8n({"store": store_name, "product": product_name,
                         "social_copy": social_copy, "images": image_urls})

@mcp.tool()
def publish_product_to_n8n(store_name: str, product_id: int, social_copy: str) -> str:
    """Looks up a product (name, link, price, images) and sends it with your social
    copy to n8n, so you don't have to pass image URLs yourself."""
    raw = _call(store_name, "GET", f"products/{product_id}",
                fields=["id", "name", "permalink", "price", "images"], compact=True)
    try:
        p = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(p, dict) or "error" in p:
        return raw
    return _post_to_n8n({"store": store_name, "product": p.get("name"),
                         "product_id": product_id, "permalink": p.get("permalink"),
                         "price": p.get("price"), "social_copy": social_copy,
                         "images": p.get("images", [])})

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
