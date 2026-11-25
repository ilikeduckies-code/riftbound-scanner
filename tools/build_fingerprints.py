"""Build the scanner's card list (cards.json) and image fingerprints (fp.json).

Run again whenever a new set comes out, then commit and push both files:
    python tools/build_fingerprints.py [thumb_cache_dir]

Cards come from Riot's official gallery (playriftbound.com, new sets appear there first) merged with
the riftcodex community API (adds promos and TCGplayer IDs).

Fingerprint (must stay identical to fingerprint() in index.html):
  card image -> 160x224 RGB (box filter) -> 16x16 block means -> 10x14x3 grid
  -> per-channel z-score -> L2 normalise -> int8 (x SCALE).
"""
import base64, hashlib, json, os, re, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image

API = "https://api.riftcodex.com/cards"
GALLERY = "https://playriftbound.com/en-us/card-gallery/"
W, H, B = 160, 224, 16
SCALE = 600
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (riftbound-scanner)"}
RID = re.compile(r"^([a-z]+)-(\d+)([^-]*)-(\d+)$", re.I)


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode("utf-8")


def riftcodex_cards():
    first = json.loads(get(f"{API}?size=100&page=1"))
    items = first["items"]
    for p in range(2, first["pages"] + 1):
        items += json.loads(get(f"{API}?size=100&page={p}"))["items"]
    out = []
    for c in items:
        rid = c.get("riftbound_id")
        if not rid:
            continue
        cl, md = c.get("classification") or {}, c.get("metadata") or {}
        out.append(slim(rid, c["name"], (c.get("set") or {}).get("label", ""), (c.get("set") or {}).get("set_id", ""),
                        c.get("collector_number"), cl.get("rarity") or "", cl.get("type") or "", cl.get("domain") or [],
                        (c.get("media") or {}).get("image_url") or "", c.get("tcgplayer_id") or "",
                        bool(md.get("alternate_art") or md.get("overnumbered") or md.get("signature"))))
    return out


def gallery_cards():
    html = get(GALLERY)
    data = json.loads(re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S).group(1))
    blade = next(b for b in data["props"]["pageProps"]["page"]["blades"] if "cards" in b)
    sizes = {s["id"]: s["collectorNumberMax"] for s in blade["sets"]["items"]}
    out = []
    for c in blade["cards"]["items"]:
        s = c["set"]["value"]
        m = RID.match(c["id"])
        num = c.get("collectorNumber")
        variant = bool(m and m.group(3)) or (num or 0) > sizes.get(s["id"], 10**6)
        out.append(slim(c["id"], c["name"], s["label"], s["id"], num, (c.get("rarity") or {}).get("value", {}).get("label", ""),
                        ((c.get("cardType") or {}).get("type") or [{}])[0].get("label", ""),
                        [d["label"] for d in (c.get("domain") or {}).get("values", [])],
                        (c.get("cardImage") or {}).get("url", ""), "", variant, sizes.get(s["id"], 0)))
    return out


def slim(rid, name, set_name, set_id, num, rarity, ctype, domains, img, tcg, variant, set_size=0):
    """Same shape the scanner uses for every card."""
    m = RID.match(rid)
    return {"rid": rid, "name": name, "setName": set_name, "code": (m.group(1) if m else set_id).upper(),
            "num": num if isinstance(num, int) else int(m.group(2)) if m else 0, "suffix": m.group(3) if m else "",
            "setSize": int(m.group(4)) if m else set_size, "rarity": rarity, "type": ctype, "domain": "/".join(domains),
            "img": img, "tcg": str(tcg), "variant": variant}


def merged_cards():
    by = {c["rid"]: c for c in gallery_cards()}
    for c in riftcodex_cards():  # riftcodex adds promos and TCGplayer IDs; official data wins for the rest
        if c["rid"] in by:
            by[c["rid"]]["tcg"] = c["tcg"] or by[c["rid"]]["tcg"]
        else:
            by[c["rid"]] = c
    return sorted(by.values(), key=lambda c: (c["code"], c["num"], c["suffix"]))


def fingerprint(img):
    a = np.asarray(img.convert("RGB").resize((W, H), Image.BOX), dtype=np.float64)
    g = a.reshape(H // B, B, W // B, B, 3).mean(axis=(1, 3))  # 14 x 10 x 3
    g = (g - g.mean(axis=(0, 1))) / (g.std(axis=(0, 1)) + 1e-6)
    v = g.reshape(-1)
    return v / (np.linalg.norm(v) + 1e-9)


def fetch_thumb(card, cache):
    url = card["img"].split("?")[0]
    if not url:
        return None
    path = os.path.join(cache, hashlib.sha1(url.encode()).hexdigest()[:20] + ".jpg")
    if not os.path.exists(path):
        with urllib.request.urlopen(urllib.request.Request(url + "?w=240&fm=jpg", headers=UA), timeout=60) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
    return path


def main():
    cache = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, ".thumbs")
    os.makedirs(cache, exist_ok=True)
    cards = merged_cards()
    assert len(cards) > 1000 and all(c["rid"] and c["name"] for c in cards), "card list looks broken"
    print(f"{len(cards)} cards; downloading thumbnails to {cache}")
    with ThreadPoolExecutor(16) as ex:
        paths = list(ex.map(lambda c: fetch_thumb(c, cache), cards))
    ids, vecs = [], []
    for c, p in zip(cards, paths):
        if not p:
            continue
        img = Image.open(p)
        imgs = [img.rotate(90, expand=True), img.rotate(-90, expand=True)] if img.width > img.height else [img]
        for im in imgs:  # landscape cards (battlefields) match either rotation
            ids.append(c["rid"])
            vecs.append(fingerprint(im))
    q = np.clip(np.round(np.array(vecs) * SCALE), -127, 127).astype(np.int8)
    with open(os.path.join(ROOT, "fp.json"), "w") as f:
        json.dump({"w": W, "h": H, "block": B, "scale": SCALE, "dim": q.shape[1], "ids": ids,
                   "data": base64.b64encode(q.tobytes()).decode()}, f)
    with open(os.path.join(ROOT, "cards.json"), "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, separators=(",", ":"))
    sets = {}
    for c in cards:
        sets[c["setName"]] = sets.get(c["setName"], 0) + 1
    print(f"wrote cards.json ({len(cards)} cards: {sets}) and fp.json ({len(ids)} fingerprints)")


if __name__ == "__main__":
    main()
