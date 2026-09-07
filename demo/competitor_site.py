"""
Clock-driven mock competitor site for demos.

Every page is a *pure function of time* (no mutable state): prices drift,
a promo banner rotates and a limited product appears/disappears on a slow
cadence. The APScheduler polls these pages; each poll very likely registers
a change, so history and scrape_runs visibly grow in the UI.

Run standalone:
    uvicorn demo.competitor_site:app --port 9000

Or as part of the demo stack: see docker-compose.demo.yml.
"""

import html
import math
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

EPOCH_SECONDS = 20  # 1 "market tick"
ROTATE_PERIOD = 3  # limited product present for 3 ticks, absent for 3

_CSS = """
body{font-family:sans-serif;max-width:760px;margin:40px auto;color:#222}
table{border-collapse:collapse;width:100%}
td,th{border:1px solid #ccc;padding:8px;text-align:left}
.promo{background:#fff3cd;padding:10px;border-radius:6px}
"""


def _now_epoch() -> int:
    return int(time.time() // EPOCH_SECONDS)


def _price(base: float, seed: int, epoch: int) -> float:
    drift = 0.35 * math.sin(epoch / 2.0 + seed)
    return round(base + drift, 2)


def _fmt(price: float) -> str:
    return f"{price:.2f}"


def _promo(name: str, epoch: int) -> str:
    options = {
        "alpha": [
            "Spring savings: take 10 percent off every cocoa order this week.",
            "New arrival: single origin dark chocolate now in stock.",
            "Free standard shipping on all orders above twenty dollars.",
        ],
        "beta": [
            "Bundle deal: buy two beverage boxes and get one free today.",
            "Limited batch: cold brew concentrate restocked for this month.",
            "Free delivery for subscribers on their first three orders.",
        ],
    }
    return options[name][epoch % len(options[name])]


def _product_rows(name: str, epoch: int) -> list[tuple[str, str, str]]:
    """Returns (product, price, stock) rows. One drifts, one rotates."""
    if name == "alpha":
        stable = ("Classic Cocoa Bar 100g", "3.49", "In stock")
        drift_p = ("Premium 70 percent Dark Bar 250g", _fmt(_price(6.90, 2, epoch)), "In stock")
    else:
        stable = ("Signature Coffee Beans 250g", "8.90", "In stock")
        drift_p = ("Decaf Ground Coffee 500g", _fmt(_price(11.40, 5, epoch)), "In stock")

    rotating = epoch % (2 * ROTATE_PERIOD) < ROTATE_PERIOD
    rows = [stable, drift_p]
    if rotating:
        if name == "alpha":
            rows.append(
                ("Limited Caramel Sea Salt Bar 80g", _fmt(_price(4.20, epoch, epoch)), "Few left")
            )
        else:
            rows.append(
                ("Limited Hazelnut Syrup 500ml", _fmt(_price(7.10, epoch, epoch)), "Few left")
            )
    return rows


def _about(name: str) -> str:
    if name == "alpha":
        return (
            "Alpha Cocoa crafts chocolate in small batches using single origin beans "
            "sourced from grower cooperatives. Every bar is stone ground for a minimum "
            "of forty eight hours to develop a smooth texture and rich flavor profile, "
            "and the finished product ships in plastic free packaging. The company "
            "publishes an annual transparency report covering its sourcing prices."
        )
    return (
        "Beta Beverages roasts and packages coffee in house at a facility that runs on "
        "renewable energy. The sourcing team buys direct from farms in Central America "
        "and East Africa and posts the contract prices online. Cold brew and concentrate "
        "lines are produced in small batches each week and distributed to retail partners "
        "across the region with a freshness date printed on every bottle."
    )


def render_page(name: str, epoch: int) -> str:
    """Deterministic HTML for a competitor page at a given market tick."""
    title = "Alpha Cocoa" if name == "alpha" else "Beta Beverages"
    sub = "Bean to bar chocolate makers" if name == "alpha" else "Direct trade coffee roasters"
    rows = _product_rows(name, epoch)
    table = "".join(
        f"<tr><td>{html.escape(p)}</td><td>{html.escape(price)} USD</td>"
        f"<td>{html.escape(stock)}</td></tr>"
        for p, price, stock in rows
    )
    ts = f"market tick {epoch}"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>{_CSS}</style></head><body>
<h1>{title}</h1>
<p>{sub}. Updated at {ts}.</p>
<p class="promo">{_promo(name, epoch)}</p>
<h2>Products</h2>
<table>
<tr><th>Product</th><th>Price</th><th>Stock</th></tr>
{table}
</table>
<h2>About</h2>
<p>{_about(name)}</p>
</body></html>"""


app = FastAPI(title="Mock Competitor Site")


@app.get("/", response_class=HTMLResponse)
def index():
    return "<h1>Mock competitor site</h1><ul><li><a href='/alpha'>Alpha</a></li><li><a href='/beta'>Beta</a></li></ul>"


@app.get("/alpha", response_class=HTMLResponse)
def alpha():
    return render_page("alpha", _now_epoch())


@app.get("/beta", response_class=HTMLResponse)
def beta():
    return render_page("beta", _now_epoch())
