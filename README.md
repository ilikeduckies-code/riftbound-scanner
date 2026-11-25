# Riftbound Scanner

Scan Riftbound cards with a webcam or phone camera, count them in chaos-sort batches, and keep one shared inventory in a Google Sheet.


## How it recognises cards

1. **Motion check (every ~55 ms).** It waits until the card in the box is still.
2. **Image match (~5–30 ms).** A colour fingerprint of the card is compared with every card image in `fp.json`.
3. **Printed code (OCR, only when needed).** About 29% of printings share their art with another printing (alt rarities, promos, overnumbered). For those it reads the code at the bottom, e.g. `UNL025/219`. If the code can't be read, it adds the most likely printing, plays a low beep, and shows a printing dropdown so you can correct it.
4. **Text fallback.** If the image isn't recognised for about 1 second, it reads the name and code as text.

In simulated tests (blur, glare, colour cast, cards placed up to 6% off-centre), the image match identified the right card art every time in normal conditions. Under heavy glare it was right about 93% of the time, and weaker matches wait for a second agreeing frame. It hasn't been tested with a real camera yet.

## One-time setup

### 1. Connect the Google Sheet (about 3 minutes)
1. Open the sheet, then **Extensions > Apps Script**.
2. Delete what's there, paste everything from `apps-script/Code.gs`, and save.
3. **Deploy > New deployment**, choose the gear icon, then **Web app**.
   - Execute as: **Me**
   - Who has access: **Anyone**
4. Approve the permissions and copy the **Web app URL** (ends in `/exec`).
5. In the scanner, open **Settings** and paste it into *Web app URL*. Paste the sheet link too, so the *Open sheet* button works.

Anyone with the web app URL can add rows to your sheet, so keep it private. To share the collection, share the **sheet** as Viewer.

If you edit `Code.gs` later, use **Deploy > Manage deployments > Edit > New version** to keep the same URL.

### 2. Run it on the PC
```
python -m http.server 8765
```
Then open http://localhost:8765.

### 3. Run it on a phone
Phones only allow the camera on HTTPS pages, so the folder needs free hosting, for example GitHub Pages or Cloudflare Pages. The page contains no private data; your sync URL is stored only on each device. Once it's hosted, open **Settings > Show QR code** on the PC and scan it with the phone. That opens the scanner with sync already set up.

## Using it

- **Mode: hand (default):** hold each card up in the box. It counts once, however much your hand wobbles. To count another copy of the same card, take it out of the box first (or tap **+1** / press `Space`). A different card counts straight away.
- **Mode: stack (fastest with a stand):** fix the camera above a spot on the table, size the guide box to one card (Settings), then lay each card on top of the last one. A new copy of the same card laid on top counts; a hand passing over without a new card doesn't. Switch with the *Mode* button.
- **Shortcuts:** `Space` adds another copy of the last card, `Z` undoes, `F` turns foil on or off, `P` pauses, `/` jumps to search.
- **Foil:** turn on Foil mode and scan all foils together. Neither method can reliably tell foil from non-foil on camera.
- **Batches:** each card goes into the current batch (B0001, B0002, ...). When a batch reaches the batch size (50 by default), the scanner beeps twice, shows a banner, and starts the next batch. Put the stack in a box and write the code on it. Batch size, prefix and numbering are in Settings and are shared through the sheet. *Set code* fills a named location such as `BINDER-3`.
- **Removing cards** (sold, traded, moved to a deck): press − in the inventory or on the last-card panel. This logs a −1 against the batch holding the card.

## Learning

Each device learns what its own camera sees, so accuracy improves with use:
- **Your fixes:** when you pick the right printing in the dropdown, or pick the card by search after a "Not sure", it saves that camera view as an extra reference for the card.
- **Confirmed scans:** scans confirmed by the printed code, or weaker image matches, are saved once the next 3 cards go by without an undo or correction.
- **Printing memory:** for cards that share their art, it remembers the printing you chose last and uses it when the code can't be read.
- **Scoreboard:** Settings shows scans, how many were accepted on the first look, code/text reads, guesses, fixes, undos and average seconds per card.

It never keeps a scan you undid or corrected. Storage is capped (about 0.8 MB per device), and *Forget learned cards* in Settings resets it.

## The sheet

| Tab | What it shows |
|---|---|
| Find Card | Type a name, set code or number in B1 to see which batch holds each copy. |
| Inventory | One row per printing and foil, with total quantity and the batches it's in. |
| Locations | Every batch with the cards inside it. |
| Batches | Card count and first/last scan time per batch. |
| Log | Every scan and correction (+1 / −1), and the source for every other tab. Add a row by hand to fix something; don't delete rows. |
| Settings | Batch size, prefix, digits, next batch number, totals. |

## Tests

Serve the folder (`python -m http.server 8765`) and open http://localhost:8765/tests/test.html. It runs the real scanner with its own storage against a fake sheet that behaves like `Code.gs`, and checks code reading, sync, undo, batch numbering and exposure handling. It doesn't touch your real data.

## New sets

When a new set comes out, rebuild the card list and fingerprints, then commit and push:
```
python tools/build_fingerprints.py
git add cards.json fp.json
git commit -m "Add new set"
git push
```
Cards come from Riot's official gallery (new sets show up there first) plus the riftcodex community database for promos and TCGplayer IDs. A set that isn't in `cards.json` can't be scanned at all.

## Handling a growing collection

- **Keep batches the same size and never reuse a code.** When you pull cards out of a batch, log the −1; don't re-sort the box. Chaos sorting works because a card's location never changes after it's scanned.
- **Separate staples from bulk.** Use a different prefix for higher-value boxes (Rares/Epics/Showcase, e.g. `R0001`) and for commons/uncommons (`B0001`). Change the prefix in Settings before scanning that pile.
- **Name decks and binders as batches.** Use *Set code* with `DECK-Kaisa` or `BINDER-1` so cards you've built with stay findable and still count as owned.
- **Log size:** each scan is one row, so 100,000 scans is about 1.3 million cells, well under Google's 10-million-cell limit. Once it gets past roughly 200,000 rows, copy the Log to a new sheet and start fresh with a single "opening balance" row per card.
- **Prices:** the CSV export includes TCGplayer IDs, so you can add prices later from a price feed or a TCGplayer import.
- **Backups:** Google Sheets keeps version history (File > Version history). Also export a CSV after big sessions.
