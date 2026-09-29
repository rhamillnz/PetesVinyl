# Pete's Vinyl 🎵

A friendly, jukebox-styled app for photographing, identifying, valuing and selling a vinyl record
collection. It runs on Pete's own Windows PC at <http://localhost:8000> and backs itself up to Google Drive.

**What Pete does for each record:**

1. **Add a Record** → hold up the front cover, back cover and both labels to the webcam and press the big red button (or the Space bar) four times. Double albums and extras get their own photos: **Another record in the cover**, **Poster, insert or artwork**, **Inner sleeve**, and **Close-up of a scratch or crease**.
2. **Check details** (also: how many records are in the cover, and focused questions on scratches, how it plays, and creases): the AI fills in the artist, album, **year this copy was pressed**, **where it was pressed**, label and catalogue number. Pete fixes anything wrong, leaves "I'm the first owner" ticked (or says how many owners it's had), and taps how worn the record and cover are.
3. **Price**: the app checks Discogs, recent eBay sales and web research, and suggests a price. Pete can type his own.
4. **Sell**: the best 1–4 sites are already ticked. Pressing **Get it listed!** posts automatically where the APIs are set up, and everywhere else shows a **copy-and-paste helper** (Copy Title / Copy Price / Copy Description, Open the site, Show the photos, "Fill it in for me").
5. When it sells, he presses **💰 It sold!**, and the app reminds him to take it off the other sites.

The home screen is a wall of all his records with their covers, where they're listed, what they're worth,
and a red **SOLD $45** stamp on the ones that have gone.

---

## Setting it up on Windows 10 (one-time, about 15 minutes)

### 1. Install Python
1. Go to <https://www.python.org/downloads/windows/> and download the latest **Python 3** installer (3.10 or newer).
2. Run it. **On the first screen, tick "Add python.exe to PATH"**, then click *Install Now*.

### 2. Get the app onto the PC
Download this repository (green **Code** button → *Download ZIP*) and unzip it somewhere permanent,
e.g. `C:\PetesVinyl`. (Or `git clone` it.)

### 3. Run the installer
Double-click **`Install_PetesVinyl.bat`**. It:
- creates a private Python environment (`venv`)
- installs everything in `requirements.txt`
- installs the Chromium browser used by the "Fill it in for me" helper
- copies `.env.example` to `.env`
- puts a **Pete's Vinyl** shortcut on the desktop

<details><summary>Doing it by hand instead</summary>

```bat
cd C:\PetesVinyl
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
uvicorn main:app --port 8000
```
</details>

### 4. Start it
Double-click **Pete's Vinyl** on the desktop (or `Start_PetesVinyl.bat`). The server starts quietly in the
background (no black window to close by accident) and the app opens in Microsoft Edge as its own window.
Double-clicking again while it's running just reopens the window. `Stop_PetesVinyl.bat` stops it; restarting the PC does too.

The first time, the browser will ask to use the camera. Click **Allow**.

### 5. Add the keys (⚙️ Settings in the app)
Everything works without keys (Pete can type details, and all sites use the copy-and-paste helper), but these make it much smarter:

| Setting | What it does | How to get it | Cost |
|---|---|---|---|
| **OpenRouter API key** | Reads the photos to identify the pressing; researches sold prices on the web | <https://openrouter.ai/keys>, then add credit | About 2–4 US cents per record with web search. $5 covers roughly 150+ records |
| **Discogs token** | Finds the exact pressing, Discogs price suggestions, posts Discogs listings automatically | <https://www.discogs.com/settings/developers> → *Generate new token* | Free |
| TradeMe keys | Posts TradeMe listings automatically | Register an app at <https://developer.trademe.co.nz> (approval can take a while) | Free |
| eBay keys | Posts eBay listings automatically | <https://developer.ebay.com>: user token, business policies, inventory location | Free |

Tips:
- For Discogs price suggestions, fill in the **seller settings** on the Discogs account first.
- Discogs listings are created as **Draft** by default so they can be checked before going live. Change `DISCOGS_LISTING_STATUS` to `For Sale` once you trust it.
- TradeMe and eBay default to their **sandbox** (test) sites. Set `TRADEME_SANDBOX` / `EBAY_SANDBOX` to `false` when ready.
- You can change the AI model in Settings. It must be one that accepts images (see <https://openrouter.ai/models>).

### 6. Backups to Google Drive
1. Install **Google Drive for Desktop**: <https://www.google.com/drive/download/>, and sign in with Pete's Google account.
2. That's it. The app finds the `My Drive` folder automatically (usually `G:\My Drive`) and copies everything into
   **`My Drive\PetesVinyl Backup`**, which Google then uploads.

What gets backed up: the database, a dated copy each day (last 30 kept, in `history\`), every photo, and
`collection.csv`, a readable list of the whole collection that opens in Google Sheets or Excel.
Backups happen automatically (within 15 minutes of any change, and at least every 6 hours), and whenever Pete presses **Back Up**.
The dot on the button is green when the last backup worked.

**Restoring on a new PC:** install the app as above, then copy `vinyl_collection.db` and the `images` folder from
`My Drive\PetesVinyl Backup` into the app folder.

---

## Where to sell, and why

| Site | Reach | How the app lists it |
|---|---|---|
| **TradeMe** | New Zealand | API (if keys) or copy & paste |
| **Discogs** | Serious collectors worldwide: USA, UK, Europe | API with a free token |
| **eBay** | USA, UK and Australia (one listing with international shipping) | API (if keys) or copy & paste |
| **Facebook Marketplace** | Local buyers | Copy & paste + "Fill it in for me" browser helper (Facebook has no listing API) |
| **Gumtree** | Australia (mostly local pickup) | Copy & paste + "Fill it in for me" browser helper |

The app recommends sites by value: cheap records go local (TradeMe and Facebook, where postage matters),
mid-value records add Discogs and eBay, and valuable records go to Discogs and eBay first, where overseas collectors pay the most.

"Fill it in for me" opens a real browser window (with its own saved logins, so Pete signs in to each site once),
goes to the site's sell page, and fills in the title, price, description and photos where it can find the boxes.
Pete always checks it and presses *Post* himself. Websites change their layouts, so if it misses a box, the Copy buttons still work.

---

## How it works (for the tech-minded)

```
main.py                 FastAPI app: REST API + serves the UI and photos
run.py                  Windows launcher (background server + Edge app window)
petesvinyl/
  config.py             settings: .env, overridden by values saved in the Settings screen
  db.py                 SQLite (vinyl_collection.db), auto-migrating schema
  ai.py                 OpenRouter: photo identification + web price research
  discogs.py            Discogs search / price suggestions / marketplace listings
  valuation.py          combines Discogs + eBay sold scrape + AI + heuristic fallback
  listings.py           per-site titles, descriptions, prices, currency; site recommendations
  publishers.py         TradeMe (OAuth1), eBay Inventory API, Discogs, Playwright browser helper
  backup.py             Google Drive for Desktop backup
  currency.py           exchange rates (open.er-api.com, offline fallback)
static/                 index.html + app.css + app.js (no frameworks, no build step)
images/record_<id>/     the photos (front, back, disc_a, disc_b)
```

Key endpoints: `POST /api/records` (base64 photos), `POST /api/records/{id}/identify`,
`POST /api/estimate-value`, `POST /api/syndicate`, `POST /api/records/{id}/sold`, `POST /api/backup`.
Interactive API docs are at <http://localhost:8000/docs>.

**Honest caveats:**
- The TradeMe and eBay API publishers follow the documented APIs but haven't been run against live accounts. Try them in sandbox mode first. Any failure falls back to the copy-and-paste helper, so nothing is lost.
- eBay often blocks the sold-listings scrape. When that happens, the AI's web research supplies the eBay figures instead.
- The server only listens on `127.0.0.1`, so nobody else on the network can reach it. API keys are stored in the local database and `.env`, and the database is copied into Pete's own Google Drive by the backup.

---

## Updating, and "the app needs a restart"

After updating the code (`git pull origin main`), just double-click **Pete's Vinyl** on the desktop again.
The launcher compares the code on disk with the code the running copy started with, and if they differ it
restarts the app automatically. If a page ever shows **"Not Found"** or a red *"needs a restart"* bar, the
running copy is older than the files on disk: run `Stop_PetesVinyl.bat`, then start the app again.
(If it was started as Administrator, a normal launch cannot stop it. Stop it once from an Administrator
PowerShell, then always start it normally.)
