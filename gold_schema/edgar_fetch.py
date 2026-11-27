"""Fetch SEC EDGAR data (public US government data) with the User-Agent the user set in lithosurfer-work/.env as SEC_USER_AGENT.
SEC fair-access rules: identify yourself, stay well under 10 requests per second. Responses are cached so each file is fetched once.

Usage: python edgar_fetch.py tickers                -> cache company_tickers.json
       python edgar_fetch.py facts <CIK> [<CIK> ...] -> cache companyfacts/CIK##########.json
"""
import json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", "..", "edgar_cache")
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
UA = ENV.get("SEC_USER_AGENT")
if not UA: sys.exit("SEC_USER_AGENT is not set in lithosurfer-work/.env")


def get(url, path):
    if os.path.exists(path): return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    json.loads(data)  # must be JSON
    open(path, "wb").write(data)
    time.sleep(0.25)  # about 4 requests per second at most
    return path


if __name__ == "__main__":
    if sys.argv[1] == "tickers":
        print(get("https://www.sec.gov/files/company_tickers.json", os.path.join(CACHE, "company_tickers.json")))
    elif sys.argv[1] == "facts":
        for cik in sys.argv[2:]:
            c = f"{int(cik):010d}"
            print(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c}.json", os.path.join(CACHE, "companyfacts", f"CIK{c}.json")))
