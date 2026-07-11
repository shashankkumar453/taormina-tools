# taormina-tools

Buying and selling tools for Taormina Motorsport — find underpriced exotics, then cross-post inventory to sell.

> **Weekly focus:** the buying tools and weekly report now default to five target cars —
> **Ferrari F355, 360, F430, 575M, and 599** (coupes + Spider variants). In the report,
> each car's Spider variant is rolled into its base model (e.g. F430 Spider → F430). Pass
> `--models` to any tool to search other cars ad-hoc; the full catalog is still available.

## Buying Tools

### 1. Price Compare
Finds dealer listings priced below BaT market value. Scores by discount, mileage, title status, owner history, and days on lot.

```bash
python -m taormina_tools.buying.price_compare
python -m taormina_tools.buying.price_compare --models "F430" "360 Modena" "Gallardo"
python -m taormina_tools.buying.price_compare --swap-only
python -m taormina_tools.buying.price_compare --zip 94065 --radius 200
python -m taormina_tools.buying.price_compare --discount 15
```

### 2. Copart/IAA Salvage Search
Searches salvage auctions for mechanically-damaged exotics.

```bash
python -m taormina_tools.buying.copart_search
python -m taormina_tools.buying.copart_search --models "Ferrari F430" "Lamborghini Gallardo"
```

### 3. Project Car Search
Searches eBay, Facebook Marketplace, and Craigslist for "needs work" / "as-is" / "mechanic special" listings + F1/e-gear manual-swap candidates.

```bash
python -m taormina_tools.buying.project_car_search
python -m taormina_tools.buying.project_car_search --models "Ferrari F430" "Lamborghini Gallardo"
```

### 4. Forum Search
Scans enthusiast forums (FerrariChat, Rennlist, Lamborghini Talk, etc.) for cars being sold with problems.

```bash
python -m taormina_tools.buying.forum_search
python -m taormina_tools.buying.forum_search --models "F430" "Gallardo" "911"
```

### 5. Facebook Marketplace Deals
Searches Facebook Marketplace for the target cars and scores each listing against the **same**
Bring a Trailer + Cars & Bids baseline as Price Compare (mileage + year adjusted). Price, mileage,
and year are parsed from the listing snippet — Google indexes Marketplace inconsistently, so
expect a modest number of fully-scored hits.

```bash
python -m taormina_tools.buying.fb_marketplace
python -m taormina_tools.buying.fb_marketplace --models "F430" "599 GTB"
python -m taormina_tools.buying.fb_marketplace --max-queries 12
```

## Selling Tools

### Cross-Post
Generates listing feeds from DealerCenter inventory exports for Google, Facebook, and Craigslist.

```bash
python -m taormina_tools.selling.cross_post --input inventory.csv
python -m taormina_tools.selling.cross_post --input inventory.csv --platform google --platform fb-catalog
```

See `docs/selling-usage.md` for full setup and platform instructions.

## Weekly Runner

Run all buying scripts and generate HTML report pages in one command:

```bash
python -m taormina_tools.run_weekly
python -m taormina_tools.run_weekly --skip-swaps
python -m taormina_tools.run_weekly --max-queries 30
```

## HTML Reports

Generate browsable HTML pages from any CSV output:

```bash
python -m taormina_tools.generate_reports out/2026-05-05-deals.csv
python -m taormina_tools.generate_reports out/*.csv
```

Reports are written to `docs/` with clickable links to every listing.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add to `.env`:
- `SERPER_API_KEY` — free at https://serper.dev (2,500 queries/month)
- `MARKETCHECK_API_KEY` — free at https://universe.marketcheck.com (500 calls/month)

## Output

CSVs written to `out/` with columns like score, model, price, market median, discount %, miles, days on market, title status, dealer contact info, listing URL, and VIN.

Sort by score descending. Work top-down. Mark `contacted` column when you reach out.
