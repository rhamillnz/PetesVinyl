# Pete's Vinyl 🎵

A friendly, jukebox-styled app for photographing, identifying, valuing and selling a vinyl record
collection. It runs on a Windows PC at <http://localhost:8000> (nothing is sent anywhere except the lookups and
listings you ask for) and backs itself up to Google Drive.

**What Pete does for each record:**

1. **Add a Record**: hold up the front cover, back cover and both labels to the webcam and press the big red button (or the Space bar) four times. Double albums and extras get their own photos: **Another record in the cover**, **Poster, insert or artwork**, **Inner sleeve**, and **Close-up of a scratch or crease**.
2. **Check details**: the AI fills in the artist, album, **year this copy was pressed**, **where it was pressed**, label and catalogue number. Pete fixes anything wrong, says how many records are in the cover, leaves "I'm the first owner" ticked (or says how many owners it's had), and answers simple questions about **scratches, how it plays, and creases**.
3. **Price**: the app checks Discogs, past auction results (Popsike) and eBay (when reachable), and suggests a price. Pete can type his own.
4. **Sell**: the best 1-4 sites are already ticked. **Get it listed!** posts automatically where the APIs are set up, and everywhere else shows a **copy-and-paste helper** (Copy Title / Copy Price / Copy Description, Open the site, Show the photos, "Fill it in for me").
5. When it sells, he presses **💰 It sold!**, and the app reminds him to take it off the other sites.

The home screen is a Wurlitzer-style wall of all his records in A-Z order with their covers, where they're listed,
what they're worth, and a red **SOLD $45** stamp on the ones that have gone.

---

## Setting it up on Windows 10 or 11 (one-time, about 20 minutes)

**You need:** a Windows 10 or 11 PC, an internet connection, a USB webcam, **Python 3.12** (step 1) and Google Chrome
(Microsoft Edge also works). Optional but recommended: Google Drive for Desktop (backups), a Discogs token and an
OpenRouter key (step 5).

### 1. Install Python 3.12 (not the newest Python!)

> ⚠️ **Don't download "the latest Python" from the python.org front page.** The newest versions (3.14 and up at the
> time of writing) don't have ready-made Windows packages for some of the libraries this app uses yet, so the
> installation fails with pages of red text (*"Failed building wheel for pydantic-core"*, *"Rust"*, *"Microsoft Visual
> C++ 14.0 or greater is required"*). Pete's Vinyl needs **Python 3.12** (3.10 to 3.13 also work).

1. Go to <https://www.python.org/downloads/release/python-3128/>.
2. Scroll down to **Files** and download **Windows installer (64-bit)**.
3. Run it. **On the very first screen, tick "Add python.exe to PATH"** (bottom of the window), then click **Install Now**.

Already have a newer Python? Keep it. You can have several, and the installer finds 3.12 by itself.
(To see what's installed, open Command Prompt and type `py -0p`.)

### 2. Get the app onto the PC

Put it in a simple folder such as **`C:\PetesVinyl`**. Not in *Downloads*, *Desktop*, *OneDrive* or *Program Files*:
Windows can block the app from saving its records in some of those.

**Option A, ZIP (simplest):**
1. On the GitHub page click the green **Code** button, then **Download ZIP**.
2. Right-click the downloaded ZIP, choose **Extract All...**, type **`C:\`** as the destination and click *Extract*.
3. You now have `C:\PetesVinyl-main`. Rename it to **`C:\PetesVinyl`**.
4. Open it. You should see `Install_PetesVinyl.bat`, `main.py` and a `static` folder **directly inside**. (Windows
   sometimes makes a folder inside a folder with the same name. If you only see one folder, open that one. The
   installer copes with this, but it's tidier to move everything up a level.)

**Option B, Git (best, because updating is one command):**
1. Install **Git for Windows** from <https://git-scm.com/download/win> (the default options are fine).
2. Open **PowerShell** and run:
   ```
   cd C:\
   git clone https://github.com/rhamillnz/PetesVinyl.git
   ```
   (If the repository is private, a browser window opens so you can sign in to GitHub once.)

### 3. Run the installer

Double-click **`Install_PetesVinyl.bat`**.

- If Windows says **"Windows protected your PC"**, click **More info**, then **Run anyway**. (It's a file from the internet that Windows doesn't know yet.)
- A black window opens and text scrolls past for **3 to 10 minutes**. That's normal. **Don't close it.** It finishes with *"All done!"*.

What it does for you:
- finds Python 3.12 (and refuses to carry on with one that is too new, telling you what to do)
- creates a private Python environment (the `venv` folder) and installs everything the app needs
- downloads a backup browser for the Facebook/Gumtree helper (optional; Chrome is used if installed)
- copies `.env.example` to `.env`
- puts two shortcuts on the desktop: **Pete's Vinyl** (a vinyl-record icon) to start the app, and **Update Pete's Vinyl** (the record with a green arrow) to get the latest version

The Update icon needs **Git for Windows** (<https://git-scm.com/download/win>, free, default options). If it isn't installed, the installer says so, and the Update icon tells you when you first use it.

The installer is **safe to run again** at any time. It repairs a broken or half-finished install and keeps your records.

<details><summary>Doing it by hand instead (PowerShell)</summary>

```
cd C:\PetesVinyl
py -3.12 -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m playwright install chromium
copy .env.example .env
venv\Scripts\python.exe run.py
```
</details>

### 4. Start it

Double-click **Pete's Vinyl** on the desktop (or `Start_PetesVinyl.bat`). The server starts quietly in the background
(there's no black window to close by accident) and the app opens in its own Chrome window.

- The first time, Chrome asks to use the camera: click **Allow**.
- Double-clicking again while it's running just reopens the window.
- **To close it, press the red ⏻ Stop button** at the top right. It saves a backup first, then shuts everything down.
  (`Stop_PetesVinyl.bat` does the same if the window is ever unreachable.)
- **To keep it on the taskbar:** right-click the **desktop shortcut**, choose **Show more options** (Windows 11), then
  **Pin to taskbar**. *Don't* pin it from the running window: Windows then pins plain Chrome and you lose the
  record icon.

### 5. Add the keys (⚙️ Settings in the app)
Everything works without keys (Pete can type details, and all sites use the copy-and-paste helper), but these make it much smarter:

| Setting | What it does | How to get it | Cost |
|---|---|---|---|
| **OpenRouter API key** | Reads the photos to identify the pressing (Gemini Flash by default) | <https://openrouter.ai/keys>, then add credit | Roughly a cent or less per record. The log page shows the real cost of every call. |
| **Discogs token** | Finds the exact pressing, Discogs price suggestions, posts Discogs listings automatically | <https://www.discogs.com/settings/developers> → *Generate new token* | Free |
| TradeMe keys | Posts TradeMe listings automatically | Register an app at <https://developer.trademe.co.nz> (approval can take a while) | Free |
| eBay keys | Posts eBay listings automatically | <https://developer.ebay.com>: user token, business policies, inventory location | Free |

Tips:
- Use **🔌 Test my keys** (Settings → *What has the app been doing?*) to check the Discogs and OpenRouter keys really work.
- For Discogs price suggestions and Discogs listings, fill in the **seller settings** on the Discogs account first (<https://www.discogs.com/settings/seller>).
- Discogs listings are created as **Draft** by default so they can be checked before going live. Change `DISCOGS_LISTING_STATUS` to `For Sale` once you trust it.
- TradeMe and eBay default to their **sandbox** (test) sites. Set `TRADEME_SANDBOX` / `EBAY_SANDBOX` to `false` when ready.
- You can change the AI model in Settings. It must be one that accepts images (see <https://openrouter.ai/models>).
- **Free models and a backup:** you can set **AI model** to a free one (names end in `:free`) to save money, but free models are rate-limited and sometimes "busy upstream". Set **Backup AI model** (default `google/gemini-2.5-flash`) and the app quietly uses it for that one request whenever the main model is busy, removed or gives an unusable answer. The log page shows each switch and what the paid call cost. Free models allow 50 requests a day until the OpenRouter account has bought $10 of credit in total, then 1,000 a day.

### 6. Backups to Google Drive
1. Install **Google Drive for Desktop**: <https://www.google.com/drive/download/>, and sign in with the Google account.
2. That's it. The app finds the `My Drive` folder automatically (usually `G:\My Drive`) and copies everything into
   **`My Drive\PetesVinyl Backup`**, which Google then uploads.

What gets backed up: the database, a dated copy each day (last 30 kept, in `history\`), every photo, and
`collection.csv`, a readable list of the whole collection that opens in Google Sheets or Excel.
Backups happen automatically (within 15 minutes of any change, and at least every 6 hours), when Pete presses **Back Up**, and when he presses **Stop**.
Every backup is checked after it's made and recorded in **⚙️ Settings → 📜 What has the app been doing? → Backups**, with when it ran and whether it worked.

**Restoring on a new PC:** install the app as above (and Google Drive for Desktop), then go to **⚙️ Settings → 📚 Your
library → Find an old library on this computer**. It finds the Google Drive backup; press **Load this library**.

### Where the records are kept (and why updates can't lose them)
The records, photos, settings and API keys live in **one fixed folder per Windows user**:
**`%LOCALAPPDATA%\PetesVinyl`** (for example `C:\Users\Pete\AppData\Local\PetesVinyl`), *not* in the app folder.
So updating, reinstalling, or downloading the app again into a different folder always finds the same library.

- Older versions kept the library inside the app folder. The first time the new version starts, it **moves it automatically** (the old files are left where they are, with a note).
- **Safety copies** are made automatically once a day, after every update, and before loading another library, in `%LOCALAPPDATA%\PetesVinyl\safety copies` (the last 30 are kept).
- **Lost track of a library?** ⚙️ Settings → 📚 *Your library* → **Find an old library on this computer** searches old app folders, the Google Drive backup and the safety copies, shows how many records each has, and loads the one you pick (your current library is safety-copied first, so it can always be undone). An empty home screen also shows a **"Had records before? Find your old library"** button.

---

## Troubleshooting

**First, look at the logs.** In the app folder: `logs\server.log` (why the app didn't start) and, inside the app,
⚙️ Settings → 📜 *What has the app been doing?* (every Discogs/OpenRouter/eBay/Popsike call and every backup).

| What you see | What it means and how to fix it |
|---|---|
| Installer shows lots of red text mentioning **wheel**, **pydantic-core**, **Rust** or **Visual C++** | Python is too new. Install **Python 3.12** (step 1), delete the `venv` folder, run `Install_PetesVinyl.bat` again. |
| Installer says **"I couldn't find a suitable Python"**, or typing `python` opens the **Microsoft Store** | Real Python isn't installed (Windows has a fake `python` shortcut that opens the Store). Install Python 3.12 from python.org (step 1). |
| Installer says it can't find **main.py**, or the files seem to be one folder too deep | The ZIP extracted into `PetesVinyl-main\PetesVinyl-main`. Open the inner folder and run the installer from there (or move its contents up). |
| Installer says not to use **Program Files** | Move the whole folder to `C:\PetesVinyl` and run it again. |
| Double-clicking `Install_PetesVinyl.bat` just flashes and closes | Run it from PowerShell so you can read the message: `cd C:\PetesVinyl` then `.\Install_PetesVinyl.bat` |
| Clicking the shortcut does nothing, and `logs\server.log` says **No module named 'uvicorn'** | The install never finished. Run `Install_PetesVinyl.bat` again (`Start_PetesVinyl.bat` also tries to repair it by itself). |
| A page says **"Not Found"**, or a red bar says the app **needs a restart** | The running copy is older than the files on disk (usually after an update). Double-click the desktop shortcut again. If it persists, run `Stop_PetesVinyl.bat`, then start the app. |
| Photos are **blurry** or out of focus | On the photo step, watch the **Focus** bar under the picture: move the record slowly closer or further until it turns green and says *Sharp*. Open **🎛️ Focus and light controls** to use **Auto-focus**, **Focus now**, a **focus slider** and **brightness**, if your camera allows it (many USB webcams do, some don't, and the app says which). Your choices are remembered per camera. Good light on the cover helps most, and most webcams can't focus closer than about 10 to 15 cm. The app also warns after a photo that looked blurry. |
| The camera doesn't start | Click **Allow** when Chrome asks (the padlock in the window lets you change it). Choose the right camera in ⚙️ Settings → *Which camera to use*. Close other programs using the webcam (Zoom, Teams). In Windows *Settings → Privacy & security → Camera*, make sure camera access is on. |
| The taskbar button shows the **Chrome logo** instead of the record | Unpin it, then pin the **desktop shortcut** (right-click → *Show more options* → *Pin to taskbar*), not the running window. |
| The app won't stop, or port 8000 seems busy | Press ⏻ Stop in the app, or run `Stop_PetesVinyl.bat`. If it was ever started as Administrator, stop it once from an Administrator PowerShell, then always start it normally. |
| Popsike log says **"0 sale prices found"** | The page loaded but no prices could be read. The log line now shows what Popsike returned, and `logs\popsike_last.png` / `popsike_last.txt` hold a screenshot and the page text. Most often the **Popsike search address** (Settings) is wrong: search for a record on Popsike yourself, copy the address from the browser, put `{query}` where the artist and album words were, and paste it into **Settings → Popsike login → Popsike search address**. If the page asks you to log in, use *Log in to Popsike* again. |
| The **Update** icon says Git isn't installed, or couldn't reach GitHub | Install **Git for Windows** from <https://git-scm.com/download/win> (default options), check the internet connection, and try again. If a GitHub sign-in window opens, sign in there. |
| **Records or API keys missing** after an update or reinstall | Nothing is deleted: the app was probably started from a different folder. Go to ⚙️ Settings → 📚 *Your library* → **Find an old library on this computer**, and load the one with your records. (From this version on, the library is kept outside the app folder, so this can't happen again.) |
| Discogs says **"You must fill out your seller settings first"** | Complete <https://www.discogs.com/settings/seller>. Until then the app uses the cheapest copy for sale instead of Discogs' suggested price. |

**Starting over without losing records:** delete the `venv` folder (or even the whole app folder) and install again. The
records, photos and keys live in `%LOCALAPPDATA%\PetesVinyl`, which the installer and updates never touch.

**A brand-new Windows install** needs nothing special beyond the steps above. (Run Windows Update first, and install your
graphics driver from the manufacturer if the screen looks wrong. That has nothing to do with this app.)

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
run.py                  Windows launcher (background server + Chrome/Edge app window; restarts a stale copy)
petesvinyl/
  config.py             settings: .env, overridden by values saved in the Settings screen
  db.py                 SQLite (vinyl_collection.db), auto-migrating schema
  ai.py                 OpenRouter: photo identification + web price research
  discogs.py            Discogs search / price suggestions / marketplace listings
  valuation.py          combines Discogs + Popsike + eBay sold scrape + AI + heuristic fallback
  popsike.py            Popsike past-auction prices (logs in once in Chrome, then reads results)
  browser.py            finds Chrome (or Edge) and manages the app's private browser windows
  activity.py           the in-app log of every outside call
  version.py            lets the launcher tell the running copy is out of date
  listings.py           per-site titles, descriptions, prices, currency; site recommendations
  publishers.py         TradeMe (OAuth1), eBay Inventory API, Discogs, Playwright browser helper
  backup.py             Google Drive for Desktop backup
  library.py            where the library lives, safety copies, finding and loading old libraries
  currency.py           exchange rates (open.er-api.com, offline fallback)
static/                 index.html + app.css + app.js + vinyl.ico (no frameworks, no build step)
tools/make_icon.py      draws static/vinyl.ico and update.ico (pure Python)
tools/make_shortcuts.ps1  creates the two desktop shortcuts
Update_PetesVinyl.bat   the desktop "Update" icon: git pull + install new parts + restart
%LOCALAPPDATA%\PetesVinyl\   the library: vinyl_collection.db, images\record_<id>\, safety copies\, Popsike login
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

**The easy way: double-click the green-arrow icon "Update Pete's Vinyl" on the desktop.** It closes the app, gets the
latest version from GitHub (`git pull origin main`), shows what changed, installs any new parts the update needs, and
opens the app again. Your records, photos and keys are never touched.

- It needs **Git for Windows** (free). If it's missing, the window tells you where to get it.
- If the app was installed from a ZIP file, the first update links it to GitHub automatically (once).
- If some program files were changed by hand so the update can't be applied cleanly, it asks whether to replace them
  with the latest version (Y/N). Your records, photos and keys are unaffected either way.
- Older installs don't have the icon yet. Double-click `Update_PetesVinyl.bat` in the app folder once (or run
  `Install_PetesVinyl.bat` again) and it puts the icon on the desktop.

**By hand instead:** open PowerShell, run `cd C:\PetesVinyl` then `git pull origin main`. (If you installed from a ZIP and
don't want to use the Update icon, download a fresh ZIP and copy its files over the app folder. Don't delete
`vinyl_collection.db`, `images`, `.env` or `venv`; the ZIP doesn't contain them, so they stay put.)

Then just double-click **Pete's Vinyl** on the desktop again. The launcher compares the code on disk with the code the
running copy started with, and if they differ it restarts the app automatically. If a page ever shows **"Not Found"** or
a red *"needs a restart"* bar, the running copy is older than the files on disk: run `Stop_PetesVinyl.bat`, then start
the app again. (If it was started as Administrator, a normal launch cannot stop it. Stop it once from an Administrator
PowerShell, then always start it normally.)

---

## Popsike (past auction prices)

[Popsike](https://www.popsike.com/) archives what records really sold for on eBay auctions, which is the best
guide for rare records. It has no API, so the app reads it the way a person would:

1. **Settings -> Popsike login -> Log in to Popsike.** A normal Chrome window opens on Popsike; use *Log in with
   Google* there (your Google password is only ever typed into Google's own page, never into this app).
   Close the window and press **I've logged in**. The login is kept in the private `popsike_profile` folder.
2. Press **Test Popsike**. It looks up a well-known record and tells you whether prices could be read.
3. From then on, every price check quietly loads Popsike's results for the record and adds a
   **Popsike past auctions** figure (weighted heavily, since it's real sold prices). The **Price** step also has
   one-tap buttons to open Popsike, eBay sold items and Discogs so you can check the numbers yourself.

Good to know:
- The lookup makes one page load per price check and never tries to get around a CAPTCHA or "verify you are
  human" page. If one appears, the log page says so. Popsike's own terms apply to your use of it, so check them.
- The reading step uses the AI (OpenRouter) on the page *text*, a fraction of a cent. Without an AI key it falls
  back to a simpler price-spotting method.
- If Popsike changes its search address, edit **Popsike search address** in Settings (`{query}` is replaced by the
  artist and album). Turn Popsike off with **Use Popsike prices = false**.
