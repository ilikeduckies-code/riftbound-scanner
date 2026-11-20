"""Build image fingerprints for every Riftbound card (fp.json, used by the scanner's image matching).

Run again whenever a new set comes out:
    python tools/build_fingerprints.py [thumb_cache_dir]

Fingerprint (must stay identical to fingerprint() in index.html):
  card image -> 160x224 RGB (box filter) -> 16x16 block means -> 10x14x3 grid
  -> per-channel z-score -> L2 normalise -> int8 (x SCALE).
"""
import base64, io, json, os, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image

API = "https://api.riftcodex.com/cards"
W, H, B = 160, 224, 16
SCALE = 600
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "riftbound-scanner"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def all_cards():
    first = get_json(f"{API}?size=100&page=1")
    items = first["items"]
    for p in range(2, first["pages"] + 1):
        items += get_json(f"{API}?size=100&page={p}")["items"]
    return items


def fingerprint(img):
    a = np.asarray(img.convert("RGB").resize((W, H), Image.BOX), dtype=np.float64)
    g = a.reshape(H // B, B, W // B, B, 3).mean(axis=(1, 3))  # 14 x 10 x 3
    g = (g - g.mean(axis=(0, 1))) / (g.std(axis=(0, 1)) + 1e-6)
    v = g.reshape(-1)
    return v / (np.linalg.norm(v) + 1e-9)


def fetch_thumb(card, cache):
    url = (card.get("media") or {}).get("image_url")
    if not url:
        return None
    path = os.path.join(cache, card["id"] + ".jpg")
    if not os.path.exists(path):
        req = urllib.request.Request(url.split("?")[0] + "?w=240&fm=jpg", headers={"User-Agent": "riftbound-scanner"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
    return path


def main():
    cache = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, ".thumbs")
    os.makedirs(cache, exist_ok=True)
    cards = all_cards()
    print(f"{len(cards)} cards; downloading thumbnails to {cache}")
    with ThreadPoolExecutor(16) as ex:
        paths = list(ex.map(lambda c: fetch_thumb(c, cache), cards))
    ids, vecs = [], []
    for c, p in zip(cards, paths):
        if not p:
            continue
        img = Image.open(p)
        imgs = [img]
        if img.width > img.height:  # landscape (battlefields): match either rotation
            imgs = [img.rotate(90, expand=True), img.rotate(-90, expand=True)]
        for im in imgs:
            ids.append(c["riftbound_id"])
            vecs.append(fingerprint(im))
    q = np.clip(np.round(np.array(vecs) * SCALE), -127, 127).astype(np.int8)
    out = {"w": W, "h": H, "block": B, "scale": SCALE, "dim": q.shape[1], "ids": ids,
           "data": base64.b64encode(q.tobytes()).decode()}
    with open(os.path.join(ROOT, "fp.json"), "w") as f:
        json.dump(out, f)
    print(f"wrote fp.json: {len(ids)} fingerprints x {q.shape[1]} dims")


if __name__ == "__main__":
    main()
