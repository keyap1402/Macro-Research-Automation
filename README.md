> Live demo output: [demo_report.html](./demo_report.html)
# Automated Macro Research Aggregator
A Python tool that aggregates macro research from 9 sources simultaneously, filters by relevance, and uses the Claude API to summarize each result into 2-sentence analyst-style digests. Outputs a clean, filterable HTML report.

## Why I Built This

During my time as a Finance Research Fellow at Suffolk University, I was producing bi-weekly macro research reports using Bloomberg and public sources. The analysis was the interesting part, but finding what was worth reading consumed a disproportionate amount of time. I built this to automate the data collection step entirely, so I could spend more time on the actual thinking.

---

## What It Does

- Pulls the latest papers, speeches, data releases, and commentary from:
  - **NBER** — National Bureau of Economic Research working papers
  - **Federal Reserve** — FOMC minutes, speeches, Beige Book
  - **IMF** — World Economic Outlook, working papers
  - **World Bank** — Research publications
  - **arXiv (econ)** — Pre-print economics papers
  - **SSRN** — Finance working papers
  - **FT, Reuters, WSJ** — Markets and economics news

- Filters results by tracked keywords (inflation, monetary policy, yield curve, emerging markets, etc.)

- Classifies each result by signal type: `Policy Signal`, `New Data`, `Academic Research`, `Market Commentary`

- Summarizes each result using Claude API — two sentences: what it argues, why it matters

- Outputs a styled, filterable HTML report you can open in any browser

---

## Setup

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/macrointel.git
cd macrointel

# Install dependencies
pip install requests feedparser beautifulsoup4 anthropic

# Add your Anthropic API key
export ANTHROPIC_API_KEY="your-key-here"

# Run
python scraper.py
```

The report saves to `report.html` — open it in your browser.

---


## Output

A dark-themed HTML report with:
- Results organized in a responsive grid
- Filter buttons by signal type
- Each card: source, date, title (linked), AI summary, signal badge
- Keyword tracking strip showing active filters

---

## Files

```
macrointel/
├── scraper.py          # Main script — fetch, filter, summarize, render
├── demo_report.html    # Sample output with realistic demo data
├── README.md
└── requirements.txt
```

---

## Requirements

```
requests
feedparser
beautifulsoup4
anthropic
```

Python 3.10+. Anthropic API key required
