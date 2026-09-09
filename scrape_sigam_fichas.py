#!/usr/bin/env python3
"""
Scrape SEGEMAR / SIGAM deposit fact sheets (dp<N>.html) into a clean, structured
JSONL file plus a raw-HTML cache.

Deposit ids come from the SIGAM "Listado de Yacimientos" index
(https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/index.html),
which links every dp<N>.html. Override with --ids.

Output (under --outdir, default ./sigam_fichas):
  sigam_fichas.jsonl   one JSON object per deposit (append, resumable)
  html/dp<N>.html      raw page cache
  scrape.log           progress

Politeness: serial, ~0.4 s gap, 3 retries with backoff, resumes (skips ids
already in the JSONL).

Parsing uses lxml.html (lenient) so nested tables (grades, dimensions) and the
mildly-malformed page header are handled correctly.

Usage:
  python scrape_sigam_fichas.py --outdir ./sigam_fichas
  python scrape_sigam_fichas.py --ids 1,92,3114 --limit 10
"""
from __future__ import annotations
import argparse, json, os, re, time, unicodedata, urllib.request, urllib.error
import lxml.html as LH

BASE = "https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos"
INDEX_URL = f"{BASE}/index.html"
UA = "sigam-deposit-research/1.0 (contact: dean@atamaianalytics.com; one-off enrichment)"
GAP_S = 0.4

# ---------------------------------------------------------------- fetch


def fetch(url: str, tries: int = 3) -> tuple[int, bytes]:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return getattr(r, "status", 200), r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, b""
            last = e
        except Exception as e:
            last = e
        time.sleep(1.5 * (i + 1))
    raise last


def decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


# ---------------------------------------------------------------- html -> tree

_WS = re.compile(r"\s+")


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    return _WS.sub(" ", s.replace("\xa0", " ")).strip()


def to_tree(page: str):
    """Return the parsed <html> element (lxml), or None."""
    try:
        return LH.fromstring(page.replace("\xa0", " "))
    except Exception:
        return None


def el_text(el) -> str:
    """All text under el, with <br> -> newline."""
    out = []

    def walk(e):
        if e.text:
            out.append(e.text)
        for c in e:
            tag = c.tag if isinstance(c.tag, str) else ""
            if tag.lower() == "br":
                out.append("\n")
            else:
                walk(c)
            if c.tail:
                out.append(c.tail)

    walk(el)
    txt = "".join(out).replace("\xa0", " ")
    return "\n".join(clean_text(ln) for ln in txt.split("\n")).strip("\n ")


def kv_from_text(s: str) -> dict:
    """`Key: value; Key2: value2` -> {key: value}. Keys are the SIGAM underlined labels."""
    d = {}
    for m in re.finditer(r"([A-Za-zÁÉÍÓÚÑáéíóúñ ?/]+?)\s*:\s*(.*?)(?=;?\s*[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ ?/]*\s*:|$)", s):
        k = clean_text(m.group(1)).rstrip(":").lower()
        k = "".join(c for c in unicodedata.normalize("NFKD", k) if not unicodedata.combining(c))
        k = k.replace(" ", "_").strip("_?")
        v = clean_text(m.group(2)).rstrip(";")
        if k and v:
            d[k] = v
    return d


GRADE_UNIT = re.compile(r"^(%|g\s*/\s*t|ppm|ppb|kg\s*/\s*t|oz\s*/\s*t|mg/l|kg|tonelada|libra|mill[oó]n|onza|carat|quilate)", re.I)


def parse_leyes(s: str) -> list[dict]:
    out = []
    for line in s.split("\n"):
        m = re.match(r"^([A-Za-z][A-Za-z0-9]{0,3})\s*:\s*([\d][\d.,]*)\s*(.*?)$", line.strip())
        if not m:
            continue
        comm, val, rest = m.group(1), m.group(2).replace(",", ""), m.group(3).strip()
        if re.match(r"^[A-Z][a-z]?[0-9]?$", comm) or comm in ("REE", "PGE") or GRADE_UNIT.match(rest):
            out.append({"commodity": comm, "value": val, "unit_note": rest})
    return out


LABEL_MAP = {
    "nombre de yacimiento": "nombre_yacimiento",
    "ubicacion politica": "ubicacion_politica",
    "fecha de actualizacion": "fecha_actualizacion",
    "clan (tipo o agrupamiento) de deposito": "clan_deposito",
    "tipo de deposito": "tipo_deposito",
    "estado del deposito": "estado_deposito",
    "provincia geologica": "provincia_geologica",
    "subprovincia geologica": "subprovincia_geologica",
    "distrito geologico": "distrito_geologico",
    "objeto ubicado del deposito": "objeto_ubicado",
    "commodities": "commodities",
    "estilos de mineralizacion": "estilos_mineralizacion",
    "edades geologicas": "edades_geologicas",
    "edades radimetricas": "edades_radimetricas",
    "marco tectonico": "marco_tectonico",
    "caracteristica coincidente": "caracteristica_coincidente",
    "estructura tectonica regional": "estructura_tectonica_regional",
    "rocas de caja": "rocas_de_caja",
    "rocas igneas relacionadas": "rocas_igneas_relacionadas",
    "rocas del entorno": "rocas_del_entorno",
    "asociacion caracteristica metalogenica": "asociacion_metalogenica",
    "asociaciones caracteristicas de la alteracion": "alteracion",
    "mineralogia": "mineralogia",
    "forma del deposito": "forma_deposito",
    "dpcomment": "dpcomment",
    "dpgeosig": "dpgeosig",
    "referencias": "referencias",
    "datos de produccion": "datos_produccion",
    "datos del recurso": "datos_recurso",
    "minas asociadas": "minas_asociadas",
    "ley cutoff del commodity": "ley_cutoff",
    "dphstrat": "dphstrat",
}


_AGE_LABELS = ("Objeto datado", "Edad - Ma", "Metodo de datacion", "Método de datación",
               "Concentrado", "Origen de la roca", "Nombre formal", "Evento datado",
               "Relacion estratigrafica", "Referencia")
_AGE_RE = re.compile(
    r"(" + "|".join(re.escape(l) for l in _AGE_LABELS) + r")\s*:\s*(.*?)(?=\s*(?:" +
    "|".join(re.escape(l) for l in _AGE_LABELS) + r")\s*:|$)", re.S)


def parse_radiometric(blob: str) -> list[dict]:
    """Split the 'Edades radimétricas' cell into one dict per dated sample."""
    recs = []
    for chunk in re.split(r"\n\s*\n+", blob):
        chunk = chunk.replace("\n", " ").strip()
        if not chunk:
            continue
        d = {}
        for m in _AGE_RE.finditer(chunk):
            k = norm_label(m.group(1)).replace(" ", "_").replace("-", "").replace("__", "_").strip("_")
            v = clean_text(m.group(2)).rstrip(";")
            if k:
                d[k] = v
        if "edad_ma" in d:
            parts = [p.strip() for p in d["edad_ma"].split(";")]
            d["age_ma"] = parts[0]
            errs = [p for p in parts[1:] if p]
            if errs:
                d["age_uncertainty"] = " ".join(errs)
        if d:
            recs.append(d)
    return recs


def norm_label(s: str) -> str:
    s = clean_text(s).rstrip(":").lower()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def parse_refs(cell: ET.Element) -> list[dict]:
    refs = []
    for tbl in cell.findall(".//table"):
        rows = [el_text(td) for tr in tbl.findall("tr") for td in tr.findall("td")]
        rows = [r for r in rows if r]
        if rows:
            refs.append({"authors_year": rows[0],
                         "title": rows[1] if len(rows) > 1 else "",
                         "publication": rows[2] if len(rows) > 2 else ""})
    return refs


def parse_endowment(cell: ET.Element) -> dict:
    # direct text of the cell (before any nested table) = the summary line
    summary_parts = [cell.text or ""]
    for c in cell:
        if c.tag.lower() == "table":
            break
        summary_parts.append(el_text(c))
        if c.tail:
            summary_parts.append(c.tail)
    summary = clean_text(" ".join(summary_parts))
    grades, amounts = [], []
    for tbl in cell.findall(".//table"):
        for tr in tbl.findall("tr"):
            tds = tr.findall("td")
            if len(tds) != 2:
                continue
            lab = norm_label(el_text(tds[0]))
            vals = parse_leyes(el_text(tds[1]))
            if "ley" in lab or "grade" in lab:
                grades += vals
            elif "recurso" in lab or "commodit" in lab:
                amounts += vals
    return {"summary": summary, "grades": grades, "commodity_amounts": amounts,
            "text": el_text(cell)}


def parse_forma(cell: ET.Element) -> tuple[str, dict]:
    dims = {}
    forma = clean_text(cell.text or "")
    for tbl in cell.findall(".//table"):
        for tr in tbl.findall("tr"):
            tds = tr.findall("td")
            if len(tds) == 2 and "dimension" in norm_label(el_text(tds[0])):
                for ln in el_text(tds[1]).split("\n"):
                    m = re.match(r"(.+?):\s*([\d.,]+)\s*(\w+)?", ln.strip())
                    if m:
                        dims[m.group(1).strip().lower()] = clean_text(f"{m.group(2)} {m.group(3) or ''}")
    return forma, dims


def parse_mineralogia(cell: ET.Element) -> list | str:
    zones = []
    for ln in el_text(cell).split("\n"):
        m = re.match(r"\((.*?)\)\s*:?\s*(.*)$", ln.strip())
        if m:
            zones.append({"zona": m.group(1).strip(),
                          "minerales": [x.strip() for x in re.split(r"[;,]", m.group(2)) if x.strip()]})
    return zones or el_text(cell)


def parse_ficha(depno: int, page: str) -> dict:
    rec: dict = {"depno": depno}
    body = to_tree(page)
    if body is None:
        rec["_parse_error"] = True
        return rec

    tables = body.findall(".//table")
    # header summary table = first with a "Nombre" header cell
    for t in tables:
        cells = [el_text(td) for tr in t.findall("tr") for td in tr.findall("td")]
        if "Nombre" in cells and len(cells) >= 10:
            rec["numero"], rec["pais"] = cells[5], cells[6]
            loc, rec["nombre"], rec["commodities_hdr"] = cells[7], cells[8], cells[9]
            mm = re.findall(r"-?\d+\.\d+", loc)
            if len(mm) >= 2:
                rec["lat"], rec["lon"] = float(mm[0]), float(mm[1])
            break

    # detail rows: any <tr> whose first <td> class contains 'righttop' with a <b> label
    for tr in body.findall(".//tr"):
        tds = tr.findall("td")
        if len(tds) != 2:
            continue
        if "righttop" not in (tds[0].get("class") or ""):
            continue
        b = tds[0].find("b")
        if b is None:
            continue
        key = LABEL_MAP.get(norm_label(el_text(b)))
        if not key:
            continue
        val = tds[1]
        if key == "referencias":
            rec["referencias"] = parse_refs(val)
        elif key == "edades_radimetricas":
            rec["edades_radimetricas"] = parse_radiometric(el_text(val))
            rec["edades_radimetricas_text"] = el_text(val)
        elif key in ("datos_produccion", "datos_recurso"):
            rec[key] = parse_endowment(val)
        elif key == "forma_deposito":
            forma, dims = parse_forma(val)
            rec["forma_deposito"] = forma
            if dims:
                rec["dimensiones"] = dims
        elif key == "mineralogia":
            rec["mineralogia"] = parse_mineralogia(val)
        else:
            rec[key] = el_text(val)

    rec["_ok"] = bool(rec.get("numero") or rec.get("nombre_yacimiento"))
    return rec


# ---------------------------------------------------------------- driver


def discover_ids() -> list[int]:
    _, raw = fetch(INDEX_URL)
    return sorted({int(x) for x in re.findall(r"dp(\d+)\.html", decode(raw))})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="./sigam_fichas")
    ap.add_argument("--ids", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-html", action="store_true")
    args = ap.parse_args()

    os.makedirs(os.path.join(args.outdir, "html"), exist_ok=True)
    jsonl = os.path.join(args.outdir, "sigam_fichas.jsonl")
    logf = open(os.path.join(args.outdir, "scrape.log"), "a", encoding="utf-8")

    def log(m):
        line = f"{time.strftime('%H:%M:%S')} {m}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    done = set()
    if os.path.exists(jsonl):
        for ln in open(jsonl, encoding="utf-8"):
            try:
                done.add(json.loads(ln)["depno"])
            except Exception:
                pass
    log(f"resume: {len(done)} fichas already in {jsonl}")

    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    else:
        log("discovering ids from SIGAM index ...")
        ids = discover_ids()
        log(f"index lists {len(ids)} deposits (dp{ids[0]}..dp{ids[-1]})")

    todo = [i for i in ids if i not in done]
    if args.limit:
        todo = todo[: args.limit]
    log(f"{len(todo)} to fetch")

    out = open(jsonl, "a", encoding="utf-8")
    n_ok = n_404 = n_err = n_parsefail = 0
    for k, depno in enumerate(todo, 1):
        url = f"{BASE}/dp{depno}.html"
        try:
            st, raw = fetch(url)
        except Exception as e:
            n_err += 1
            out.write(json.dumps({"depno": depno, "http_status": -1, "error": str(e)[:200],
                                  "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
            out.flush()
            log(f"[{k}/{len(todo)}] dp{depno} ERROR {e}")
            time.sleep(GAP_S)
            continue
        if st == 404:
            n_404 += 1
            out.write(json.dumps({"depno": depno, "http_status": 404,
                                  "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        else:
            page = decode(raw)
            if not args.no_html:
                open(os.path.join(args.outdir, "html", f"dp{depno}.html"), "w",
                     encoding="utf-8").write(page)
            rec = parse_ficha(depno, page)
            rec["http_status"] = st
            rec["url"] = url
            rec["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if rec.get("_parse_error") or not rec.get("_ok"):
                n_parsefail += 1
            else:
                n_ok += 1
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        if k % 100 == 0:
            log(f"[{k}/{len(todo)}] ok={n_ok} 404={n_404} parsefail={n_parsefail} err={n_err}")
        time.sleep(GAP_S)

    log(f"DONE ok={n_ok} 404={n_404} parsefail={n_parsefail} err={n_err} "
        f"total_now={len(done) + n_ok + n_404 + n_parsefail}")
    out.close()
    logf.close()


if __name__ == "__main__":
    main()
