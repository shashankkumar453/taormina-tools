# Taormina Seller — Usage Guide

Cross-posting tool that generates listing feeds from your DealerCenter inventory export.

## Quick Start

```bash
cd taormina-seller

# Generate all platform outputs at once
python3 -m taormina_seller.cross_post --input your-export.csv

# Specific platform only
python3 -m taormina_seller.cross_post --input your-export.csv --platform google
python3 -m taormina_seller.cross_post --input your-export.csv --platform fb-catalog
python3 -m taormina_seller.cross_post --input your-export.csv --platform craigslist --cl-region sacramento

# Specific cars only
python3 -m taormina_seller.cross_post --input your-export.csv --vins ZHWGU22T98LA07291 WP0CB29948S780145
```

## Getting Your Inventory CSV

1. Log into DealerCenter
2. Go to Inventory → Export (or Reports → Inventory Export)
3. Export as CSV with all fields
4. Save the file and pass it as `--input`

The parser handles common column name variants automatically (VIN/vin, Price/Selling Price/Internet Price, etc.).

## Outputs

After running, you'll find these in the `out/` folder:

| File | What it is | What to do with it |
|------|-----------|-------------------|
| `google-vehicle-feed-YYYY-MM-DD.tsv` | Google Merchant Center vehicle feed | Upload to Merchant Center (see below) |
| `fb-catalog-feed-YYYY-MM-DD.csv` | Facebook Commerce Manager vehicle catalog | Upload to Commerce Manager (see below) |
| `fb-manual-posts-YYYY-MM-DD.csv` | Copy-paste templates for FB Marketplace | Open, copy title+body per car, post manually from personal account |
| `craigslist-posts-YYYY-MM-DD/` | One .txt file per car | Open each file, copy the body into Craigslist's posting form |
| `posting-log.json` | Tracks what's been posted where | Automatic — prevents duplicates on re-runs |

## Platform Setup (One-Time)

### Google Merchant Center (Free Vehicle Listings)

1. Go to https://merchants.google.com and create an account
2. Verify your business (they'll send a postcard or call)
3. Go to Growth → Manage programs → enroll in "Vehicle listings"
4. Go to Products → Feeds → create a new feed
5. Upload the `google-vehicle-feed-*.tsv` file
6. OR host the file at a URL (e.g., on your website) and tell Merchant Center to fetch it daily

Once set up, your cars appear in Google search results when people search things like "2008 Lamborghini Gallardo for sale near me."

### Facebook Commerce Manager (Marketplace Catalog)

1. Go to https://business.facebook.com/commerce
2. Create a catalog → choose "Vehicles"
3. Upload the `fb-catalog-feed-*.csv` file
4. Cars will appear on Facebook Marketplace under your business page

For better reach: also use the manual posting templates (`fb-manual-posts-*.csv`) and post from your personal account. Dealer page auto-posts get suppressed by the algorithm.

### Craigslist

No setup needed. Just:
1. Go to https://sacramento.craigslist.org/post (or your region)
2. Choose "cars+trucks - by dealer"
3. Open the `.txt` file for the car
4. Copy the title, set the price, paste the HTML body
5. Upload photos (URLs are listed in the file header)

## Re-running / Updating

When you get new inventory or prices change:
1. Export a fresh CSV from DealerCenter
2. Run the script again — it will only generate feeds for cars not already in the posting log
3. To regenerate everything (e.g., after a price change), delete `out/posting-log.json` first

## Options

```
--input FILE        Path to DealerCenter CSV export (required)
--platform NAME     Target platform: google, fb-catalog, fb-manual, craigslist
                    Can specify multiple times. Omit for all platforms.
--cl-region NAME    Craigslist region (default: sfbay)
--vins VIN [VIN]    Only process specific VINs
--output-dir DIR    Output directory (default: out)
```
