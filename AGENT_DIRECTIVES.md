# PetesVinyl - Agent Orchestration Directives

**Lead Orchestrator:** Read this document carefully. You will use your Herdr multiplexing capabilities to spawn isolated panes and assign specific tasks to sub-agents (Qwen 2.5 Coder, GLM-4V, and Kimi K2). Do not move to the next phase until the tests for the current phase pass.

## Phase 1: Local State & Backend Setup
* **Assigned Agent:** Qwen 2.5 Coder
* **Task:** Build the core database and local server.
* **Requirements:**
  * Scaffold a lightweight backend (FastAPI or Flask) and a SQLite database.
  * Schema must include: `id`, `artist`, `album_title`, `year_pressed`, `pressing_location`, `is_first_owner` (boolean, default true), and local file paths for 4 images (`cover_front`, `cover_back`, `disc_a`, `disc_b`).
  * Create a local endpoint to receive base64 images from the frontend, save them to a local `/images` directory, and write the row to SQLite.
  * Integrate the Google Drive API to run a background sync of the SQLite file and the `/images` folder.

## Phase 2: Hardware UI & Camera Capture
* **Assigned Agent:** Qwen 2.5 Coder
* **Task:** Build the frictionless ingestion UI.
* **Requirements:**
  * Build a React/TypeScript frontend (or vanilla JS) utilizing the `navigator.mediaDevices.getUserMedia()` API.
  * Implement a single-button state machine: Clicking "Capture" cycles through capturing Front Cover -> Back Cover -> Side A -> Side B.
  * Upon capturing the 4th image, automatically POST the payload to the Phase 1 backend.

## Phase 3: AI Metadata Extraction (Vision)
* **Assigned Agent:** GLM-4V
* **Task:** Automate data entry via visual analysis.
* **Requirements:**
  * Write a script that hooks into the Phase 1 backend. When new images are saved, pass `cover_front` and `cover_back` to the GLM-4V multimodal endpoint.
  * Prompt GLM-4V to extract the Artist, Album Title, Record Label, and Barcode/Matrix numbers.
  * Return this data strictly as a JSON object and update the SQLite record.

## Phase 4: Valuation Engine & Market Scraping
* **Assigned Agent:** Kimi K2
* **Task:** Build the historical pricing engine.
* **Requirements:**
  * Write a Playwright script to query the Discogs API using the metadata from Phase 3 to find the specific pressing and median price.
  * Write a secondary Playwright automation to search eBay "Sold Items" and Popsike for the catalog number, scraping the top 3 recent sale prices.
  * Use Kimi K2's reasoning capabilities to ingest the scraped Discogs/eBay data and output a realistic, calculated "Suggested Listing Price".

## Phase 5: The 3-Click Syndicator
* **Assigned Agent:** Qwen 2.5 Coder (APIs) & Kimi K2 (Web Automation)
* **Task:** Automate cross-platform publishing.
* **Requirements:**
  * **Qwen 2.5:** Build the payload constructors for the TradeMe API and eBay Inventory API using the saved images and the Kimi K2 valuation.
  * **Kimi K2:** Build a headless Playwright script to automate navigating to Gumtree, logging in via session cookies, injecting the listing text into the DOM, uploading the local images, and saving it as a draft.
  * **UI Update:** Add a "Publish Everywhere" button to the frontend that triggers all three syndication channels simultaneously.
