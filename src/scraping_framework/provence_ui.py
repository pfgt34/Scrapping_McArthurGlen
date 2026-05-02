"""Local frontend for browsing McArthurGlen Provence stores."""

from __future__ import annotations

import json
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import PROCESSED_DATA_DIR, ScraperRuntimeConfig, setup_logging
from .mcarthurglen import McArthurGlenScraper, build_center_profile_from_url
from .models import ScrapedStore
from .processor import StoreProcessor

PROVENCE_CENTER_URL = "https://www.mcarthurglen.com/en/outlets/fr/designer-outlet-provence/"
PROVENCE_UI_CACHE = PROCESSED_DATA_DIR / "frontend" / "mcarthurglen_provence.json"


@dataclass(slots=True)
class ProvenceDashboardData:
    """Container for the UI payload."""

    mall_name: str
    crawl_date: str
    total_stores: int
    total_brands: int
    new_openings: int
    categories: list[str]
    stores: list[dict[str, Any]]


def build_provence_dashboard_data(force_refresh: bool = False) -> ProvenceDashboardData:
    """Scrape Provence and prepare the data consumed by the frontend."""

    if not force_refresh and PROVENCE_UI_CACHE.exists():
        cache_age_seconds = time.time() - PROVENCE_UI_CACHE.stat().st_mtime
        if cache_age_seconds < 6 * 60 * 60:
            payload = json.loads(PROVENCE_UI_CACHE.read_text(encoding="utf-8"))
            return ProvenceDashboardData(**payload)

    logger = setup_logging("provence_ui")
    profile = build_center_profile_from_url(PROVENCE_CENTER_URL)
    profile = profile.__class__(
      **{**profile.__dict__, "requires_javascript": True}
    )
    runtime_config = ScraperRuntimeConfig(headless=True, save_raw_html=True)
    scraper = McArthurGlenScraper(profile=profile, runtime_config=runtime_config, logger=logger)

    result = scraper.run(crawl_date=date.today())
    processor = StoreProcessor(brand_aliases=profile.brand_aliases)
    frame = processor.records_to_dataframe(result.records)

    stores = [_store_to_payload(record) for record in result.records]
    categories = _extract_categories(stores)
    data = ProvenceDashboardData(
        mall_name=profile.mall_name,
        crawl_date=result.crawl_date.isoformat(),
        total_stores=len(stores),
        total_brands=int(frame["store_name_normalized"].nunique()) if not frame.empty else 0,
        new_openings=sum(1 for record in result.records if "New opening" in record.badges),
        categories=categories,
        stores=stores,
    )

    PROVENCE_UI_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PROVENCE_UI_CACHE.write_text(json.dumps(asdict(data), ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def run_provence_dashboard(host: str = "127.0.0.1", port: int = 8050, force_refresh: bool = False) -> None:
    """Launch the local Provence dashboard."""

    data = build_provence_dashboard_data(force_refresh=force_refresh)
    server = ThreadingHTTPServer((host, port), lambda *args, **kwargs: ProvenceRequestHandler(data, *args, **kwargs))
    url = f"http://{host}:{port}/"
    print(f"McArthurGlen Provence dashboard available at {url}")
    threading.Timer(0.75, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


class ProvenceRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler serving the Provence frontend."""

    def __init__(self, dashboard_data: ProvenceDashboardData, *args: Any, **kwargs: Any) -> None:
        self.dashboard_data = dashboard_data
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/stores"):
            self._send_json(asdict(self.dashboard_data))
            return

        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        html = render_dashboard_html(self.dashboard_data)
        self._send_html(html)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def render_dashboard_html(data: ProvenceDashboardData) -> str:
    """Render the frontend HTML for Provence."""

    store_data = json.dumps(data.stores, ensure_ascii=False)
    category_buttons = "".join(
        f'<button class="chip" data-filter-category="{category}">{category}</button>'
        for category in data.categories[:18]
    )

    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{data.mall_name} | Boutiques</title>
  <style>
    :root {{
      --bg: #f5f2ea;
      --panel: #ffffff;
      --panel-strong: #ffffff;
      --line: rgba(27, 33, 46, 0.12);
      --text: #141414;
      --muted: #5e6470;
      --accent: #c28d2c;
      --accent-2: #3d6fb4;
      --success: #217a57;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(194, 141, 44, 0.11), transparent 28%),
        radial-gradient(circle at 85% 10%, rgba(61, 111, 180, 0.08), transparent 20%),
        linear-gradient(180deg, #faf8f2 0%, #f5f2ea 42%, #f7f4ec 100%);
      min-height: 100vh;
    }}
    .shell {{ max-width: 1360px; margin: 0 auto; padding: 24px 18px 44px; }}
    .hero {{
      position: relative;
      overflow: hidden;
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(251, 249, 243, 0.98));
      border-radius: 18px;
      padding: 24px 26px 22px;
      box-shadow: 0 14px 36px rgba(34, 31, 26, 0.08);
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -64px -60px auto;
      width: 210px;
      height: 210px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(194, 141, 44, 0.12), transparent 65%);
      pointer-events: none;
    }}
    .kicker {{ text-transform: uppercase; letter-spacing: 0.22em; color: var(--accent); font-size: 0.74rem; font-weight: 700; }}
    h1 {{ margin: 10px 0 10px; font-size: clamp(2rem, 3vw, 3.15rem); line-height: 1.02; letter-spacing: -0.03em; }}
    .hero p {{ margin: 0; color: var(--muted); max-width: 840px; font-size: 0.98rem; line-height: 1.6; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 20px 0 0; }}
    .stat {{
      background: rgba(255, 255, 255, 0.9);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px 16px 14px;
    }}
    .stat .value {{ font-size: 1.8rem; font-weight: 800; }}
    .stat .label {{ color: var(--muted); font-size: 0.86rem; margin-top: 4px; }}
    .toolbar {{
      margin: 18px 0 14px;
      display: grid;
      grid-template-columns: 1.7fr 0.8fr auto;
      gap: 12px;
      align-items: center;
    }}
    .search, .select {{
      width: 100%;
      border: 1px solid var(--line);
      background: #ffffff;
      color: var(--text);
      border-radius: 14px;
      padding: 14px 16px;
      outline: none;
      box-shadow: 0 6px 18px rgba(31, 31, 31, 0.05);
    }}
    .search::placeholder {{ color: #828a96; }}
    .chips {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-start; }}
    .chip {{
      border: 1px solid var(--line);
      background: #ffffff;
      color: var(--text);
      border-radius: 999px;
      padding: 10px 13px;
      font-size: 0.84rem;
      cursor: pointer;
      box-shadow: 0 5px 15px rgba(31, 31, 31, 0.04);
    }}
    .chip.active {{ background: #1f2937; color: #ffffff; border-color: #1f2937; }}
    .layout {{ display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 14px; margin-top: 16px; }}
    .alphabet {{ position: sticky; top: 18px; align-self: start; display: grid; gap: 7px; }}
    .alpha-link {{
      display: grid;
      place-items: center;
      width: 42px;
      height: 42px;
      border-radius: 12px;
      border: 1px solid var(--line);
      color: var(--muted);
      text-decoration: none;
      background: #ffffff;
      font-weight: 700;
      box-shadow: 0 4px 14px rgba(31, 31, 31, 0.04);
    }}
    .section {{ margin-bottom: 26px; }}
    .section h2 {{
      margin: 0 0 12px;
      font-size: 1rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: #5a5f67;
      border-bottom: 1px solid var(--line);
      padding-bottom: 8px;
    }}
    .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #ffffff;
      padding: 18px;
      min-height: 176px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
      box-shadow: 0 8px 22px rgba(31, 31, 31, 0.05);
    }}
    .card:hover {{ transform: translateY(-2px); border-color: rgba(31, 41, 55, 0.18); box-shadow: 0 12px 28px rgba(31, 31, 31, 0.08); }}
    .card-head {{ display: flex; gap: 14px; align-items: flex-start; }}
    .badge {{
      width: 42px;
      height: 42px;
      border-radius: 12px;
      display: grid;
      place-items: center;
      background: linear-gradient(135deg, rgba(194, 141, 44, 0.16), rgba(61, 111, 180, 0.12));
      color: #1f2937;
      font-weight: 800;
      flex: 0 0 auto;
    }}
    .name {{ font-size: 1.03rem; font-weight: 800; margin: 0; }}
    .meta {{ color: var(--muted); font-size: 0.85rem; margin-top: 4px; }}
    .description {{ color: #2d2f34; line-height: 1.55; font-size: 0.93rem; margin: 0; }}
    .pills {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: auto; }}
    .pill {{
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fbfaf7;
      color: var(--muted);
      padding: 7px 10px;
      font-size: 0.78rem;
    }}
    .pill.success {{ color: #0e4b34; background: rgba(33, 122, 87, 0.12); border-color: rgba(33, 122, 87, 0.16); }}
    .pill.warn {{ color: #7d560b; background: rgba(194, 141, 44, 0.14); border-color: rgba(194, 141, 44, 0.2); }}
    .empty {{ display: none; color: var(--muted); padding: 28px; border: 1px dashed var(--line); border-radius: 16px; margin-top: 16px; background: rgba(255, 255, 255, 0.8); }}
    .topbar {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; margin: 8px 2px 4px; color: var(--muted); font-size: 0.94rem; }}
    .topbar strong {{ color: var(--text); }}
    @media (max-width: 1100px) {{
      .stats, .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .toolbar {{ grid-template-columns: 1fr; }}
      .layout {{ grid-template-columns: 1fr; }}
      .alphabet {{ position: static; grid-template-columns: repeat(14, minmax(0, 1fr)); }}
    }}
    @media (max-width: 640px) {{
      .shell {{ padding: 14px; }}
      .hero {{ padding: 18px; border-radius: 16px; }}
      .stats, .grid {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 2rem; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="kicker">McArthurGlen Provence</div>
      <h1>Boutiques du centre Provence</h1>
      <p>Annuaire des boutiques présentes à Designer Outlet Provence, avec recherche, filtres et navigation alphabétique dans une présentation plus classique.</p>
      <div class="stats">
        <div class="stat"><div class="value">{data.total_stores}</div><div class="label">boutiques détectées</div></div>
        <div class="stat"><div class="value">{data.total_brands}</div><div class="label">marques normalisées</div></div>
        <div class="stat"><div class="value">{data.new_openings}</div><div class="label">nouvelles ouvertures</div></div>
        <div class="stat"><div class="value">{data.crawl_date}</div><div class="label">crawl daté</div></div>
      </div>
    </section>

    <div class="toolbar">
      <input id="search" class="search" type="search" placeholder="Rechercher une boutique, une catégorie ou un badge" />
      <select id="categoryFilter" class="select">
        <option value="">Toutes les catégories</option>
      </select>
      <div class="chips">
        <button class="chip active" data-filter-category="">Tout</button>
        {category_buttons}
      </div>
    </div>

    <div class="topbar">
      <div><strong id="visibleCount">0</strong> boutique(s) affichée(s)</div>
      <div>Source: <strong>McArthurGlen Provence /stores/</strong></div>
    </div>

    <div class="layout">
      <nav class="alphabet" id="alphabetNav"></nav>
      <main id="content"></main>
    </div>
    <div id="empty" class="empty">Aucune boutique ne correspond à votre recherche.</div>
  </div>

  <script>
    const stores = {store_data};
    const state = {{ query: '', category: '' }};
    const content = document.getElementById('content');
    const emptyState = document.getElementById('empty');
    const visibleCount = document.getElementById('visibleCount');
    const search = document.getElementById('search');
    const categoryFilter = document.getElementById('categoryFilter');
    const alphabetNav = document.getElementById('alphabetNav');

    const alphabet = Array.from(new Set(stores.map(store => (store.store_name_normalized || store.store_name_raw || '#')[0].toUpperCase())))
      .filter(Boolean)
      .sort();

    alphabetNav.innerHTML = alphabet.map(letter => `<a class="alpha-link" href="#section-${{letter}}">${{letter}}</a>`).join('');

    const categories = Array.from(new Set(stores.flatMap(store => store.categories || []))).sort((a, b) => a.localeCompare(b));
    for (const category of categories) {{
      const option = document.createElement('option');
      option.value = category;
      option.textContent = category;
      categoryFilter.appendChild(option);
    }}

    function matches(store) {{
      const haystack = [
        store.store_name_raw,
        store.store_name_normalized,
        store.description,
        (store.categories || []).join(' '),
        (store.badges || []).join(' '),
        store.card_text,
      ].join(' ').toLowerCase();
      const queryOk = !state.query || haystack.includes(state.query.toLowerCase());
      const categoryOk = !state.category || (store.categories || []).some(category => category === state.category);
      return queryOk && categoryOk;
    }}

    function cardTemplate(store) {{
      const letter = (store.store_name_normalized || store.store_name_raw || '#')[0].toUpperCase();
      const categories = (store.categories || []).map(category => `<span class="pill">${{category}}</span>`).join('');
      const badges = (store.badges || []).map(badge => `<span class="pill ${{badge === 'New opening' ? 'warn' : 'success'}}">${{badge}}</span>`).join('');
      const description = store.description || store.card_text || 'Boutique McArthurGlen.';
      return `
        <article class="card" data-store-card data-letter="${{letter}}">
          <div class="card-head">
            <div class="badge">${{letter}}</div>
            <div>
              <h3 class="name">${{store.store_name_raw}}</h3>
              <div class="meta">${{store.store_name_normalized}} · <a href="${{store.store_url}}" target="_blank" rel="noreferrer" style="color:#9cc2ff">ouvrir la fiche</a></div>
            </div>
          </div>
          <p class="description">${{description}}</p>
          <div class="pills">${{badges}}${{categories}}</div>
        </article>`;
    }}

    function render() {{
      const grouped = new Map();
      const filtered = stores.filter(matches);
      for (const store of filtered) {{
        const letter = (store.store_name_normalized || store.store_name_raw || '#')[0].toUpperCase();
        if (!grouped.has(letter)) grouped.set(letter, []);
        grouped.get(letter).push(store);
      }}

      const sortedLetters = Array.from(grouped.keys()).sort();
      content.innerHTML = sortedLetters.map(letter => `
        <section class="section" id="section-${{letter}}">
          <h2>${{letter}}</h2>
          <div class="grid">
            ${{grouped.get(letter).map(cardTemplate).join('')}}
          </div>
        </section>`).join('');

      visibleCount.textContent = filtered.length;
      emptyState.style.display = filtered.length ? 'none' : 'block';
    }}

    search.addEventListener('input', event => {{ state.query = event.target.value.trim(); render(); }});
    categoryFilter.addEventListener('change', event => {{ state.category = event.target.value; render(); }});
    document.querySelectorAll('[data-filter-category]').forEach(button => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('[data-filter-category]').forEach(item => item.classList.remove('active'));
        button.classList.add('active');
        state.category = button.dataset.filterCategory || '';
        categoryFilter.value = state.category;
        render();
      }});
    }});

    render();
  </script>
</body>
</html>"""


def _store_to_payload(store: ScrapedStore) -> dict[str, Any]:
    """Convert a scraped store into a JSON-ready payload."""

    return {
        "mall_id": store.mall_id,
        "mall_name": store.mall_name,
        "crawl_date": store.crawl_date.isoformat(),
        "store_name_raw": store.store_name_raw,
        "store_name_normalized": store.store_name_normalized,
        "source_url": store.source_url,
        "store_url": store.store_url or "",
        "source_mode": store.source_mode,
        "description": store.description,
        "categories": store.categories,
        "badges": store.badges,
        "card_text": store.card_text,
    }


def _extract_categories(stores: list[dict[str, Any]]) -> list[str]:
    """Return the sorted unique categories used by the stores."""

    categories: set[str] = set()
    for store in stores:
        for category in store.get("categories", []):
            if category:
                categories.add(category)
    return sorted(categories, key=lambda value: value.lower())