# Maguro

Homemade bento order tracker for two-person use. Notion is the database; this app is the mobile-friendly UI for entering orders, editing them, and viewing the day summary before make/deliver runs.

## Features

- **Orders** — list by date, grouped by round (Lunch / Afternoon / Dinner)
- **Add / edit** — customer, boxes, round, delivery vs pick-up, address, notes, paid, status
- **Day summary** — total orders & boxes, revenue estimate (฿1,350/box + delivery fees), delivery & pick-up lists per round with notes
- **Status** — `Open` while active, mark `Done` when delivered (payment tracked separately via `Paid`)

- **Inbox** — sync Instagram DMs via Meta Graph API; mark replied, label threads, add order from chat

## Instagram / Meta API setup

Requires an **Instagram Business** or **Creator** account linked to a **Facebook Page**.

### 1. Create a Meta app

1. Go to [developers.facebook.com](https://developers.facebook.com/) → **My Apps** → **Create App**
2. Type: **Business** (or Other → Business)
3. Add products: **Instagram** → **Instagram API setup with Facebook login**
4. Add **Facebook Login for Business** → set **Valid OAuth Redirect URIs**:
   - Local: `http://localhost:8080/api/instagram/callback`
   - Production: `https://YOUR-APP.onrender.com/api/instagram/callback`

### 2. App credentials in `.env`

```bash
META_APP_ID=your-app-id
META_APP_SECRET=your-app-secret
META_REDIRECT_URI=http://localhost:8080/api/instagram/callback
META_VERIFY_TOKEN=pick-a-random-string
```

### 3. Connect in Maguro

1. Log in → **Inbox** tab → **Connect Instagram**
2. Authorize with the Facebook account that manages your Page
3. Maguro stores the Page token + Instagram business account ID in `data/meta_connection.json`

### 4. Webhooks (real-time DM updates)

In Meta App Dashboard → **Instagram** → **Webhooks**:

| Setting | Value |
|---------|--------|
| Callback URL | `https://YOUR-APP.onrender.com/api/instagram/webhook` |
| Verify token | Same as `META_VERIFY_TOKEN` |
| Fields | `messages` |

Subscribe your Instagram account to the webhook after connecting.

### 5. Render production notes

- On **Render free tier**, the filesystem is ephemeral — OAuth tokens saved during connect may be lost on redeploy. Either:
  - Re-connect via **Inbox → Connect Instagram** after each deploy, or
  - Set long-lived `META_PAGE_ACCESS_TOKEN` + `META_IG_USER_ID` in Render env vars (from [Graph API Explorer](https://developers.facebook.com/tools/explorer/))
- Set `META_REDIRECT_URI` to `https://YOUR-APP.onrender.com/api/instagram/callback`

### API endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/instagram/status` | Yes | Connection status |
| GET | `/api/instagram/auth` | Yes | Start OAuth |
| GET | `/api/instagram/callback` | No | OAuth redirect |
| POST | `/api/instagram/disconnect` | Yes | Clear stored tokens |
| GET/POST | `/api/instagram/webhook` | No | Meta webhook verify + events |
| GET | `/api/inbox` | Yes | List DM threads |
| PATCH | `/api/inbox/{id}` | Yes | Update replied / label |

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
| **Phone** | Text | optional, customer phone number |
| **Evidence** | Text | optional — newline-separated links to attached payment slips / screenshots (app manages this field) |

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
| `META_APP_ID` | For IG OAuth | — |
| `META_APP_SECRET` | For IG OAuth | — |
| `META_REDIRECT_URI` | For IG OAuth | — |
| `META_VERIFY_TOKEN` | Webhook verify | `maguro-webhook-verify` |
| `META_PAGE_ACCESS_TOKEN` | Optional direct token | — |
| `META_IG_USER_ID` | Optional direct token | — |
| `DATA_DIR` | Token/label storage | `data` |

Optional `NOTION_PROP_*` overrides if your column names differ — see `.env.example`.

## Instagram DM → order evidence

Orders come in over Instagram DM (chat + payment slip in the same thread), so the inbox can pull
suggestions and evidence straight from a thread:

- **Link an order**: on a thread in the Inbox tab, paste an order's ID into "Order ID to link" → **Link**.
- **Extract from chat**: pulls the thread's messages and suggests a **phone** (regex) and **address**
  (keyword heuristic — no LLM, so it's a suggestion to review/apply, never auto-written into Notion).
  Any payment-slip images found are downloaded immediately (Instagram's CDN links expire fast) and saved
  as evidence on the linked order right away, since that part is safe to automate.
- **Manual orders**: open an existing order to edit it — an **Evidence** section lets you attach a
  screenshot (FB comment, Messenger chat, etc.) directly. Same storage pipeline as Instagram-derived
  slips, just tagged `source: manual`.

Evidence files live on local disk under `DATA_DIR/evidence/` (metadata in `DATA_DIR/evidence_index.json`)
and are served through an authenticated `/api/evidence/{id}` endpoint; Notion's Evidence column only gets
the link text. **Note:** Render's free-tier disk is ephemeral — evidence files won't survive a
redeploy/restart there. Fine for casual use; if that starts to matter, swap `app/evidence/store.py` for
an S3/R2-backed implementation (same function signatures, so nothing else needs to change).

## Roadmap

- Phase 2: Customer address book (separate Notion database)
- Phase 3: Delivery fee helpers
