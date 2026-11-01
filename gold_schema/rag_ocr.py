# OCR for image-only PDFs going into the document library: writes ocr_<name>.json (page -> text, column-aware) into OCR_CACHE.
# Usage: python rag_ocr.py <pdf> <name> [pages|all]
import sys, os, json, time, re
import numpy as np
import pymupdf
from rapidocr_onnxruntime import RapidOCR

SP = os.environ.get("OCR_CACHE", "C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/1de38d20-e452-45b6-a85d-8f80b8fca969/scratchpad")
ocr = RapidOCR()
WATERMARK = re.compile(r"^(dean|smith|dean smith|smith dean|downloaded|on|'?m|by)$", re.I)


def boxes_of(page, dpi=200):
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    res, _ = ocr(img)
    out = []
    for box, txt, sc in (res or []):
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        if WATERMARK.match(txt.strip()):
            continue
        out.append({"x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys), "t": txt, "s": float(sc)})
    return pix.width, out


def lines_from(items):
    """Group boxes into lines by vertical overlap, left to right inside a line."""
    items = sorted(items, key=lambda b: ((b["y0"] + b["y1"]) / 2, b["x0"]))
    lines, cur, cur_y, cur_h = [], [], None, 0
    for b in items:
        yc = (b["y0"] + b["y1"]) / 2; h = b["y1"] - b["y0"]
        if cur_y is None or abs(yc - cur_y) <= max(8, 0.55 * max(h, cur_h)):
            cur.append(b); cur_y = yc if cur_y is None else (cur_y + yc) / 2; cur_h = max(cur_h, h)
        else:
            lines.append(cur); cur, cur_y, cur_h = [b], yc, h
    if cur:
        lines.append(cur)
    return [" ".join(x["t"] for x in sorted(l, key=lambda b: b["x0"])) for l in lines]


def column_edges(W, boxes):
    """Return sorted x positions of vertical gutters (empty list = single column)."""
    narrow = [b for b in boxes if (b["x1"] - b["x0"]) < 0.5 * W]
    if len(narrow) < 12:
        return []
    nb = 400
    occ = np.zeros(nb, dtype=int)
    for b in narrow:
        a = max(0, int(b["x0"] / W * nb)); z = min(nb - 1, int(b["x1"] / W * nb))
        occ[a:z + 1] += 1
    gutters, i = [], 0
    min_gap = max(3, int(0.012 * nb))
    while i < nb:
        if occ[i] == 0:
            j = i
            while j + 1 < nb and occ[j + 1] == 0:
                j += 1
            if i > 0 and j < nb - 1 and (j - i + 1) >= min_gap:
                gutters.append(((i + j) / 2.0) / nb * W)
            i = j + 1
        else:
            i += 1
    # keep only gutters that leave >= 10% of narrow boxes on each side of every neighbour
    keep = []
    for g in gutters:
        left = sum(1 for b in narrow if b["x1"] <= g and (not keep or b["x0"] >= keep[-1]))
        if left >= 0.1 * len(narrow):
            keep.append(g)
    last = keep[-1] if keep else None
    if last is not None and sum(1 for b in narrow if b["x0"] >= last) < 0.1 * len(narrow):
        keep.pop()
    return keep


def ordered_text(W, boxes):
    if not boxes:
        return ""
    gutters = column_edges(W, boxes)
    if not gutters:
        return "\n".join(lines_from(boxes))
    edges = [0.0] + gutters + [float(W) + 1]

    def col_of(b):
        c = (b["x0"] + b["x1"]) / 2
        for k in range(len(edges) - 1):
            if edges[k] <= c < edges[k + 1]:
                return k
        return len(edges) - 2

    spanning = sorted([b for b in boxes if any(b["x0"] < g < b["x1"] for g in gutters) and (b["x1"] - b["x0"]) >= 0.5 * W], key=lambda b: b["y0"])
    span_ids = set(id(b) for b in spanning)
    cols = [b for b in boxes if id(b) not in span_ids]
    out, top = [], -1
    for sp in spanning + [None]:
        bottom = sp["y0"] if sp else 10 ** 9
        seg = [b for b in cols if top <= (b["y0"] + b["y1"]) / 2 < bottom]
        for k in range(len(edges) - 1):
            out.extend(lines_from([b for b in seg if col_of(b) == k]))
        if sp:
            out.append(sp["t"]); top = sp["y1"]
    return "\n".join(out)


def run(path, name, pages=None):
    cache = os.path.join(SP, f"ocr_{name}.json")
    data = json.load(open(cache, encoding="utf-8")) if os.path.exists(cache) else {}
    doc = pymupdf.open(path)
    todo = pages if pages else range(1, len(doc) + 1)
    t0 = time.time(); n = 0
    for p in todo:
        if str(p) in data:
            continue
        W, boxes = boxes_of(doc[p - 1])
        data[str(p)] = ordered_text(W, boxes); n += 1
        if n % 10 == 0:
            json.dump(data, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"{name}: {len(data)}/{len(doc)} pages, {(time.time()-t0)/n:.1f}s/page", flush=True)
    json.dump(data, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{name}: done {len(data)}/{len(doc)} pages in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    path, name = sys.argv[1], sys.argv[2]
    pages = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 and sys.argv[3] != "all" else None
    run(path, name, pages)
