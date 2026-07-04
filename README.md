# Maguro

Homemade bento order tracker for two-person use. Notion is the database; this app is the mobile-friendly UI for entering orders, editing them, and viewing the day summary before make/deliver runs.

## Features

- **Orders** — list by date, grouped by round (Lunch / Afternoon / Dinner)
- **Add / edit** — customer, boxes, round, delivery vs pick-up, address, notes, paid, status
- **Day summary** — total orders & boxes, revenue estimate (฿1,350/box + delivery fees), delivery & pick-up lists per round with notes
- **Status** — `Open` while active, mark `Done` when delivered (payment tracked separately via `Paid`)

## Notion setup

Add these properties to your existing database (keep your current columns):

| Property | Type | Options / notes |
|----------|------|-----------------|
| Name | Title | (existing) |
| Date | Date | (existing) |
| Amount | Number | (existing) |
| Paid | Checkbox | (existing) |
| Delivery Time | Select | `01_Lunch`, `02_Afternoon`, `03_Dinner` |
| Note | Text | (existing) |
| **Status** | Select | `Open`, `Done` |
| **Fulfillment** | Select | `Delivery`, `Pick-up` |
| **Address** | Text | optional |
| **Delivery Fee** | Number | ฿, separate from box price |

### Notion integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) → **New integration**
2. Copy the **Internal Integration Secret** (`secret_…`)
3. Open your orders database → **⋯** → **Connections** → add your integration
4. Copy the database ID from the URL:  
   `notion.so/workspace/DATABASE_ID?v=…`

## Local development

```bash
cd maguro
python3.12 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env
# Edit .env with NOTION_TOKEN, NOTION_DATABASE_ID, APP_PASSWORD
./venv/bin/uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080

Health check: `GET /api/health`

## Deploy on Render (free tier)

1. Push this repo to GitHub
2. [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint** (or Web Service)
3. Connect repo; Render reads `render.yaml`
4. Set env vars: `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `APP_PASSWORD`
5. Deploy

**Note:** Free tier sleeps after ~15 min idle; first load may take 30–60 seconds.

## Environment variables

| Variable | Required | Default |
|----------|----------|---------|
| `NOTION_TOKEN` | Yes | — |
| `NOTION_DATABASE_ID` | Yes | — |
| `APP_PASSWORD` | Yes | — |
| `SECRET_KEY` | Yes | random (auto on Render) |
| `BOX_PRICE` | No | `1350` |
| `TIMEZONE` | No | `Asia/Bangkok` |

Optional `NOTION_PROP_*` overrides if your column names differ — see `.env.example`.

## Roadmap

- Phase 2: Customer address book (separate Notion database)
- Phase 3: IG link field, delivery fee helpers
