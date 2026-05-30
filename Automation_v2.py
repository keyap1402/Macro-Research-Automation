"""
Macro Research Intelligence Tool
---------------------------------
Scrapes macro research from NBER, Federal Reserve, IMF, World Bank,
arXiv (econ), and news feeds. Summarizes each result via Claude API
and outputs a styled HTML report.
"""

import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import json
import re
import time
import anthropic

# ── CONFIG ────────────────────────────────────────────────────────────────────

KEYWORDS = [
    "inflation", "monetary policy", "interest rates", "federal reserve",
    "GDP", "recession", "credit markets", "emerging markets",
    "fiscal policy", "yield curve", "central bank", "debt"
]

SOURCES = {
    "ECB": "https://www.ecb.europa.eu/rss/press.html",
    "BIS": "https://www.bis.org/doclist/bis_fsr/index.htm?cblist=9&cblist=56&cblist=6&cblist=7&cblist=30&cblist=31&cblist=32&cblist=16&cblist=33&cblist=34&cblist=35&cblist=36&cblist=37&cblist=55&cblist=38&cblist=11&cblist=39&cblist=40&cblist=41&cblist=42&cblist=43&cblist=44&cblist=45&cblist=46&cblist=47&cblist=48&cblist=49&cblist=50&cblist=51&cblist=52&cblist=53&cblist=54&rss=1",
    "VoxEU": "https://cepr.org/rss.xml",
    "Brookings Economy": "https://www.brookings.edu/topic/economy/feed/",
    "Peterson IIE": "https://www.piie.com/rss/publications.xml",
    "St. Louis Fed (FRED)": "https://research.stlouisfed.org/publications/review/rss",
    "Dallas Fed": "https://www.dallasfed.org/research/rss",
    "NY Fed": "https://www.newyorkfed.org/rss/research",
}

NEWS_FEEDS = {
    "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
    "Seeking Alpha Macro": "https://seekingalpha.com/feed/tag/macro-economy.xml",
    "The Economist": "https://www.economist.com/finance-and-economics/rss.xml",
    "Bloomberg Economics": "https://feeds.bloomberg.com/economics/news.rss",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "Investopedia": "https://www.investopedia.com/feedbuilder/feed/getfeed/?feedName=rss_headline",
}

MAX_ITEMS_PER_SOURCE = 6
MAX_ITEMS_TO_SUMMARIZE = 20  # Claude API calls, keeps cost low

# ── SIGNAL CLASSIFIER ─────────────────────────────────────────────────────────

SIGNAL_RULES = {
    "Policy Signal": ["federal reserve", "fed", "ecb", "central bank", "rate decision",
                      "monetary policy", "interest rate", "fomc", "beige book"],
    "New Data": ["gdp", "cpi", "inflation", "employment", "jobs report", "pce",
                 "retail sales", "trade balance", "pmi", "data", "report", "survey"],
    "Academic Research": ["nber", "arxiv", "ssrn", "working paper", "journal",
                          "econometric", "model", "regression", "empirical"],
    "Market Commentary": ["market", "rally", "selloff", "yield", "spread",
                          "equity", "bond", "dollar", "commodity", "outlook"],
}

def classify_signal(title: str, summary: str) -> str:
    text = (title + " " + summary).lower()
    for label, keywords in SIGNAL_RULES.items():
        if any(k in text for k in keywords):
            return label
    return "General Macro"

# ── KEYWORD FILTER ────────────────────────────────────────────────────────────

def is_relevant(title: str, summary: str) -> bool:
    # Match on title OR summary — and accept anything from research sources
    # even if keywords don't match (macro feeds are inherently relevant)
    text = (title + " " + summary).lower()
    return any(k.lower() in text for k in KEYWORDS) or len(title) > 15

# ── FETCH FEEDS ───────────────────────────────────────────────────────────────

def fetch_feed(name: str, url: str) -> list[dict]:
    results = []
    try:
        feed = feedparser.parse(url, agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        for entry in feed.entries[:MAX_ITEMS_PER_SOURCE]:
            title = entry.get("title", "").strip()
            summary = BeautifulSoup(
                entry.get("summary", entry.get("description", "")), "html.parser"
            ).get_text()[:500]
            link = entry.get("link", "")
            published = entry.get("published", entry.get("updated", ""))

            if not title or not link:
                continue
            if not is_relevant(title, summary):
                continue

            results.append({
                "source": name,
                "title": title,
                "summary_raw": summary.strip(),
                "link": link,
                "published": published,
                "ai_summary": None,
                "signal": classify_signal(title, summary),
            })
    except Exception as e:
        print(f"  [warn] {name}: {e}")
    return results

# ── AI SUMMARIZATION ──────────────────────────────────────────────────────────

def summarize_batch(items: list[dict]) -> list[dict]:
    client = anthropic.Anthropic()
    to_summarize = [i for i in items if i["ai_summary"] is None][:MAX_ITEMS_TO_SUMMARIZE]

    print(f"\nSummarizing {len(to_summarize)} items via Claude API...")

    for idx, item in enumerate(to_summarize):
        prompt = f"""You are a macro research analyst assistant. Summarize the following in exactly 2 sentences:
1. What the paper/article argues or reports
2. Why it matters for macro investors or policymakers

Title: {item['title']}
Raw text: {item['summary_raw']}

Be specific. Avoid filler phrases like "This paper explores..." — lead with the finding."""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}]
            )
            item["ai_summary"] = response.content[0].text.strip()
            print(f"  [{idx+1}/{len(to_summarize)}] ✓ {item['title'][:60]}...")
        except Exception as e:
            item["ai_summary"] = item["summary_raw"][:200] + "..."
            print(f"  [{idx+1}/{len(to_summarize)}] ✗ fallback: {e}")

        time.sleep(0.3)  # gentle rate limiting

    return items

# ── HTML REPORT ───────────────────────────────────────────────────────────────

SIGNAL_COLORS = {
    "Policy Signal":     ("#FF6B35", "#1a0800"),
    "New Data":          ("#00C896", "#001a12"),
    "Academic Research": ("#7B6BFF", "#0a0818"),
    "Market Commentary": ("#FFD166", "#1a1400"),
    "General Macro":     ("#8899AA", "#0d1117"),
}

def build_html(items: list[dict]) -> str:
    now = datetime.now().strftime("%A, %B %d %Y — %H:%M")
    total = len(items)

    by_signal = {}
    for item in items:
        by_signal.setdefault(item["signal"], []).append(item)

    signal_counts = {s: len(v) for s, v in by_signal.items()}

    # Build cards
    cards_html = ""
    for item in items:
        color, _ = SIGNAL_COLORS.get(item["signal"], ("#8899AA", "#0d1117"))
        ai_text = item["ai_summary"] or item["summary_raw"][:200] + "..."
        pub = item["published"][:16] if item["published"] else "—"
        cards_html += f"""
        <article class="card" data-signal="{item['signal']}">
          <div class="card-meta">
            <span class="badge" style="background:{color}20;color:{color};border-color:{color}40">{item['signal']}</span>
            <span class="source-tag">{item['source']}</span>
            <span class="pub-date">{pub}</span>
          </div>
          <h3 class="card-title">
            <a href="{item['link']}" target="_blank" rel="noopener">{item['title']}</a>
          </h3>
          <p class="card-summary">{ai_text}</p>
          <a href="{item['link']}" target="_blank" class="read-link" rel="noopener">
            Read source ↗
          </a>
        </article>"""

    # Filter buttons
    filters_html = '<button class="filter-btn active" data-filter="all">All <span class="count">' + str(total) + '</span></button>'
    for sig, count in signal_counts.items():
        color, _ = SIGNAL_COLORS.get(sig, ("#8899AA", "#0d1117"))
        filters_html += f'<button class="filter-btn" data-filter="{sig}" style="--sig-color:{color};">{sig} <span class="count">{count}</span></button>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Macro Intelligence Digest</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=IBM+Plex+Mono:wght@400;500&family=Literata:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg:        #0B0C10;
      --surface:   #13151C;
      --border:    #1E2130;
      --text:      #E8EAF0;
      --muted:     #5A6070;
      --accent:    #00C896;
      --font-head: 'Syne', sans-serif;
      --font-mono: 'IBM Plex Mono', monospace;
      --font-body: 'Literata', serif;
    }}

    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-body);
      min-height: 100vh;
      padding: 0 0 80px;
    }}

    /* ── HEADER ── */
    header {{
      border-bottom: 1px solid var(--border);
      padding: 40px 60px 32px;
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 24px;
      flex-wrap: wrap;
    }}

    .header-left h1 {{
      font-family: var(--font-head);
      font-size: clamp(28px, 4vw, 48px);
      font-weight: 800;
      letter-spacing: -0.03em;
      line-height: 1;
      color: var(--text);
    }}

    .header-left h1 span {{
      color: var(--accent);
    }}

    .header-sub {{
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--muted);
      margin-top: 8px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}

    .header-right {{
      text-align: right;
    }}

    .run-time {{
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--muted);
      letter-spacing: 0.05em;
    }}

    .total-badge {{
      display: inline-block;
      margin-top: 8px;
      background: var(--accent)18;
      border: 1px solid var(--accent)40;
      color: var(--accent);
      font-family: var(--font-mono);
      font-size: 12px;
      padding: 4px 12px;
      border-radius: 2px;
    }}

    /* ── KEYWORD STRIP ── */
    .keyword-strip {{
      padding: 16px 60px;
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }}

    .kw-label {{
      font-family: var(--font-mono);
      font-size: 10px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.1em;
      margin-right: 4px;
    }}

    .kw-tag {{
      font-family: var(--font-mono);
      font-size: 10px;
      padding: 3px 9px;
      border: 1px solid var(--border);
      color: var(--muted);
      border-radius: 2px;
      letter-spacing: 0.05em;
    }}

    /* ── FILTERS ── */
    .filters {{
      padding: 24px 60px 0;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}

    .filter-btn {{
      font-family: var(--font-mono);
      font-size: 11px;
      padding: 6px 14px;
      border-radius: 2px;
      border: 1px solid var(--border);
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      transition: all 0.15s;
      letter-spacing: 0.04em;
    }}

    .filter-btn:hover {{
      border-color: var(--sig-color, var(--accent));
      color: var(--sig-color, var(--accent));
    }}

    .filter-btn.active {{
      background: var(--accent)18;
      border-color: var(--accent);
      color: var(--accent);
    }}

    .filter-btn .count {{
      opacity: 0.6;
      margin-left: 4px;
    }}

    /* ── GRID ── */
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
      gap: 1px;
      margin-top: 24px;
      border-top: 1px solid var(--border);
      border-left: 1px solid var(--border);
    }}

    /* ── CARD ── */
    .card {{
      background: var(--surface);
      border-right: 1px solid var(--border);
      border-bottom: 1px solid var(--border);
      padding: 28px 32px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      transition: background 0.15s;
    }}

    .card:hover {{
      background: #161820;
    }}

    .card.hidden {{
      display: none;
    }}

    .card-meta {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }}

    .badge {{
      font-family: var(--font-mono);
      font-size: 9px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      padding: 3px 8px;
      border-radius: 2px;
      border: 1px solid;
      font-weight: 500;
    }}

    .source-tag {{
      font-family: var(--font-mono);
      font-size: 10px;
      color: var(--muted);
      letter-spacing: 0.05em;
    }}

    .pub-date {{
      font-family: var(--font-mono);
      font-size: 10px;
      color: var(--muted);
      margin-left: auto;
    }}

    .card-title {{
      font-family: var(--font-head);
      font-size: 15px;
      font-weight: 600;
      line-height: 1.4;
      letter-spacing: -0.01em;
    }}

    .card-title a {{
      color: var(--text);
      text-decoration: none;
      transition: color 0.15s;
    }}

    .card-title a:hover {{
      color: var(--accent);
    }}

    .card-summary {{
      font-size: 13.5px;
      line-height: 1.65;
      color: #9AA0B0;
      font-style: italic;
      flex: 1;
    }}

    .read-link {{
      font-family: var(--font-mono);
      font-size: 10px;
      color: var(--muted);
      text-decoration: none;
      letter-spacing: 0.05em;
      transition: color 0.15s;
      align-self: flex-start;
    }}

    .read-link:hover {{
      color: var(--accent);
    }}

    /* ── FOOTER ── */
    footer {{
      margin-top: 60px;
      padding: 0 60px;
      border-top: 1px solid var(--border);
      padding-top: 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
    }}

    footer p {{
      font-family: var(--font-mono);
      font-size: 10px;
      color: var(--muted);
      letter-spacing: 0.05em;
    }}

    footer a {{
      color: var(--accent);
      text-decoration: none;
    }}

    @media (max-width: 700px) {{
      header, .keyword-strip, .filters {{ padding-left: 20px; padding-right: 20px; }}
      footer {{ padding-left: 20px; padding-right: 20px; }}
      .grid {{ border-left: none; }}
      .card {{ border-right: none; padding: 20px; }}
    }}
  </style>
</head>
<body>

<header>
  <div class="header-left">
    <h1>Macro<span>Intel</span></h1>
    <p class="header-sub">Automated Research Aggregator · AI-Summarized · Live Feed</p>
  </div>
  <div class="header-right">
    <p class="run-time">Generated {now}</p>
    <span class="total-badge">{total} results</span>
  </div>
</header>

<div class="keyword-strip">
  <span class="kw-label">Tracking</span>
  {''.join(f'<span class="kw-tag">{k}</span>' for k in KEYWORDS)}
</div>

<div class="filters">
  {filters_html}
</div>

<div class="grid" id="grid">
  {cards_html}
</div>

<footer>
  <p>Sources: NBER · Federal Reserve · IMF · World Bank · arXiv Econ · SSRN · News Feeds</p>
  <p>Built with Python · feedparser · BeautifulSoup · <a href="https://anthropic.com">Claude API</a></p>
</footer>

<script>
  const btns = document.querySelectorAll('.filter-btn');
  const cards = document.querySelectorAll('.card');

  btns.forEach(btn => {{
    btn.addEventListener('click', () => {{
      btns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const f = btn.dataset.filter;
      cards.forEach(c => {{
        if (f === 'all' || c.dataset.signal === f) {{
          c.classList.remove('hidden');
        }} else {{
          c.classList.add('hidden');
        }}
      }});
    }});
  }});
</script>

</body>
</html>"""

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  MACRO RESEARCH INTELLIGENCE TOOL")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    all_items = []

    print("\nFetching research feeds...")
    for name, url in SOURCES.items():
        print(f"  → {name}")
        items = fetch_feed(name, url)
        print(f"     {len(items)} relevant items found")
        all_items.extend(items)

    print("\nFetching news feeds...")
    for name, url in NEWS_FEEDS.items():
        print(f"  → {name}")
        items = fetch_feed(name, url)
        print(f"     {len(items)} relevant items found")
        all_items.extend(items)

    # Deduplicate by title
    seen = set()
    unique_items = []
    for item in all_items:
        key = item["title"].lower()[:80]
        if key not in seen:
            seen.add(key)
            unique_items.append(item)

    print(f"\nTotal unique relevant items: {len(unique_items)}")

    # Summarize
    unique_items = summarize_batch(unique_items)

    # Build report
    print("\nBuilding HTML report...")
    html = build_html(unique_items)

    output_path = r"C:\Users\keyap\CODES\report.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✓ Report saved to: {output_path}")
    print(f"  {len(unique_items)} items across {len(SOURCES) + len(NEWS_FEEDS)} sources")
    return output_path

if __name__ == "__main__":
    main()