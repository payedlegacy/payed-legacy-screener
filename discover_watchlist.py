#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
discover_watchlist.py — Penemuan calon saham (MINGGUAN) untuk screener.payedlegacy.my
=====================================================================================
Masalah yang diselesaikan: sebelum ini `watchlist.json` ialah senarai TETAP (41 kaunter),
jadi laman memaparkan saham yang SAMA setiap hari walaupun harganya dikemas kini.
Skrip ini memilih semula senarai itu daripada SELURUH pasaran setiap minggu, mengikut
kriteria enjin laman ("Global Mega-Breakout & Volume Surge"):

    * volum melonjak      : relative_volume_10d_calc  >= 1.0
    * kecairan            : average_volume_10d_calc   >= 150k (Bursa) / 1j (US)
    * saiz                : market_cap_basic          >= RM150j (Bursa) / USD2b (US)
    * bukan saham sen        : close                  >= RM0.20 / USD3.00
    * momentum & breakout dinilai dalam skor (EMA7>EMA21>EMA50, jarak ke puncak 52 minggu)

Sumber calon : TradingView scanner awam (scanner.tradingview.com/<pasaran>/scan)
Penyelesai kod Bursa : Yahoo Finance search (TradingView memberi MYX:GAMUDA, tetapi
                       yfinance memerlukan kod angka 5398.KL, dan senarai Syariah SC
                       juga berkunci pada kod angka itu)

Penggunaan:
  python discover_watchlist.py --dry-run          # tunjuk senarai, TIDAK tulis fail
  python discover_watchlist.py                    # tulis watchlist.json
  python discover_watchlist.py --top-klse 55 --top-us 25 --anchors-klse MAYBANK,TENAGA

Nota: `anchors` = kaunter besar yang DIKEKALKAN setiap minggu (supaya laman masih ada
nama yang dikenali ramai); selebihnya dipilih semula setiap minggu. Set --anchors-* ""
untuk senarai 100% dinamik.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

MYT = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

TV_MARKET = {"KLSE": "malaysia", "US": "america"}
TV_COLUMNS = [
    "name", "description", "close", "change", "volume",
    "average_volume_10d_calc", "relative_volume_10d_calc", "market_cap_basic",
    "sector", "EMA7", "EMA21", "EMA50", "price_52_week_high", "High.All",
    "dividend_yield_recent", "price_earnings_ttm",
]

# Tapisan minimum (kecairan & saiz) — elak saham sen/illikuid masuk senarai
GATES = {
    "KLSE": {"close": 0.20, "market_cap_basic": 150_000_000,
             "average_volume_10d_calc": 150_000, "relative_volume_10d_calc": 1.0},
    "US": {"close": 3.0, "market_cap_basic": 2_000_000_000,
           "average_volume_10d_calc": 1_000_000, "relative_volume_10d_calc": 1.0},
}
US_EXCHANGES = ["NASDAQ", "NYSE", "AMEX"]   # langkau OTC/pink sheet

# Kaunter besar yang dikekalkan setiap minggu (boleh ubah melalui CLI)
ANCHOR_KLSE = ("MAYBANK,TENAGA,CIMB,PBBANK,GAMUDA,SUNWAY,IHH,MAXIS,MISC,"
               "NESTLE,IOICORP,KLK,RHBBANK,HLBANK")
ANCHOR_US = "NVDA,AAPL,TSLA,MSFT,GOOGL,AMZN,META,AMD"

NOTA = ("Watchlist screener.payedlegacy.my — dipilih SEMULA secara automatik setiap minggu "
        "oleh discover_watchlist.py (enjin Global Mega-Breakout & Volume Surge). "
        "Kaunter besar dalam 'anchors' dikekalkan; selebihnya ialah calon terbaik minggu ini. "
        "PENTING: kaunter Bursa Malaysia guna KOD ANGKA Yahoo Finance (cth 5398.KL = Gamuda). "
        "'sector' ialah label untuk penapis di index.html. 'bursaCode' untuk padanan senarai Syariah SC.")


def http_json(url: str, body: dict | None = None, timeout: int = 40, origin: str | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# --------------------------------------------------------------------------
# 1) Calon daripada TradingView scanner
# --------------------------------------------------------------------------
def tv_scan(market: str, gates: dict, limit: int = 250) -> list[dict]:
    """Pulangkan baris calon (disusun ikut lonjakan volum) untuk satu pasaran."""
    filters = [{"left": "type", "operation": "equal", "right": "stock"}]
    for col, val in gates.items():
        filters.append({"left": col, "operation": "greater", "right": val})
    if market == "US":
        filters.append({"left": "exchange", "operation": "in_range", "right": US_EXCHANGES})
    body = {
        "filter": filters,
        "options": {"lang": "en"},
        "columns": TV_COLUMNS,
        "sort": {"sortBy": "relative_volume_10d_calc", "sortOrder": "desc"},
        "range": [0, limit],
    }
    out = http_json(f"https://scanner.tradingview.com/{TV_MARKET[market]}/scan", body,
                    origin="https://screener.payedlegacy.my")
    rows = []
    for r in out.get("data", []) or []:
        d = r.get("d") or []
        if len(d) < len(TV_COLUMNS):
            continue
        rec = dict(zip(TV_COLUMNS, d))
        rec["tv"] = r.get("s")            # cth MYX:GAMUDA / NASDAQ:NVDA
        rows.append(rec)
    return rows


def skor(rec: dict) -> float:
    """Skor calon: lonjakan volum + kedekatan puncak 52 minggu + momentum EMA + perubahan hari."""
    def num(x):
        try:
            f = float(x)
            return f if f == f and abs(f) != float("inf") else None
        except (TypeError, ValueError):
            return None

    rel = num(rec.get("relative_volume_10d_calc")) or 0.0
    close = num(rec.get("close")) or 0.0
    high52 = num(rec.get("price_52_week_high")) or 0.0
    e7, e21, e50 = (num(rec.get("EMA7")), num(rec.get("EMA21")), num(rec.get("EMA50")))
    chg = num(rec.get("change")) or 0.0

    kedekatan = (close / high52) if high52 > 0 else 0.0          # 1.00 = pada puncak 52 minggu
    momo = 0.0
    if e7 and e21 and e50:
        if e7 > e21 > e50:
            momo = 1.0                                            # susunan penuh (bullish)
        elif e7 > e21:
            momo = 0.5
    return 1.2 * min(rel, 6.0) + 3.0 * kedekatan + 1.0 * momo + 0.08 * max(min(chg, 12.0), -12.0)


# --------------------------------------------------------------------------
# 2) Kod angka Bursa (Yahoo) — wajib untuk yfinance + senarai Syariah SC
# --------------------------------------------------------------------------
def _normal(x: str) -> str:
    return "".join(ch for ch in str(x or "").upper() if ch.isalnum())


def _cari_satu(q: str) -> list[tuple]:
    """Carian Yahoo mentah -> [(symbol, shortname, exch)]."""
    url = (f"https://query1.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(q)}"
           f"&quotesCount=10&newsCount=0&listsCount=0")
    d = http_json(url, timeout=25)
    return [(str(x.get("symbol") or ""), x.get("shortname") or "", x.get("exchange") or "")
            for x in (d.get("quotes") or [])]


def yahoo_cari(nama: str, pasaran: str, cache: dict, simbol: str | None = None, cuba: int = 3) -> str | None:
    """Cari ticker Yahoo. Bursa: '5398.KL' · US: 'NVDA'.

    Strategi (penting untuk ketepatan): Yahoo lemah untuk carian NAMA PENUH kaunter Bursa,
    tetapi tepat untuk KOD RINGKAS. Jadi:
      1) cari ikut kod ringkas, dan SAHKAN `shortname` sepadan dengan kod itu (elak salah kaunter);
      2) jika gagal, cari ikut nama penuh syarikat dan terima .KL pertama yang munasabah.
    """
    kunci = f"{pasaran}:{simbol or nama}"
    if kunci in cache:
        return cache[kunci]

    hasil = None
    for i in range(cuba):
        try:
            if simbol:
                for sym, short, _ex in _cari_satu(simbol):
                    if pasaran == "KLSE":
                        if sym.endswith(".KL") and _normal(short) == _normal(simbol):
                            hasil = sym
                            break
                    elif _normal(short) == _normal(simbol) and "." not in sym:
                        hasil = sym
                        break
            if not hasil:
                for sym, short, _ex in _cari_satu(nama):
                    if pasaran == "KLSE":
                        if sym.endswith(".KL") and sym[:-3].isdigit():
                            hasil = sym
                            break
                    elif "." not in sym and "^" not in sym and _normal(short):
                        hasil = sym
                        break
            break
        except Exception as exc:  # noqa: BLE001
            if i == cuba - 1:
                print(f"  [warn] Yahoo cari gagal ({simbol or nama}): {exc}", file=sys.stderr)
            time.sleep(1.0 + i)
    cache[kunci] = hasil
    return hasil


# --------------------------------------------------------------------------
# 3) Sektor TradingView (Inggeris) -> label penapis index.html
# --------------------------------------------------------------------------
def label_sektor(tv_sector: str | None) -> str:
    s = (tv_sector or "").lower()
    table = [
        (("finance", "insurance"), "Finance"),
        (("technolog", "communication", "semiconductor", "electronic"), "Technology"),
        (("real estate", "property"), "Property"),
        (("utilit", "energy minerals"), "Energy"),
        (("health", "pharmaceutical"), "Healthcare"),
        (("oil", "gas", "fuel", "energy"), "Energy"),
        (("chemical", "mining", "non-energy minerals", "forest", "paper"), "Materials"),
        (("industrial", "producer manufacturing", "commercial services", "transportation",
          "distribution services", "business services"), "Industrials"),
        (("consumer", "retail", "food", "beverage", "tobacco", "apparel"), "Consumer"),
        (("communications", "telecom"), "Telco"),
    ]
    for keys, val in table:
        if any(k in s for k in keys):
            return val
    return "Lain-lain"


# --------------------------------------------------------------------------
# 4) Bina watchlist
# --------------------------------------------------------------------------
def bina(args) -> tuple[list[dict], dict]:
    with open(args.watchlist, encoding="utf-8") as fh:
        lama = json.load(fh)
    lama_list = lama["stocks"] if isinstance(lama, dict) else lama
    ikut_symbol = {str(s.get("symbol", "")).upper(): s for s in lama_list}

    anchors = {
        "KLSE": [x.strip().upper() for x in args.anchors_klse.split(",") if x.strip()],
        "US": [x.strip().upper() for x in args.anchors_us.split(",") if x.strip()],
    }

    akhir: list[dict] = []
    ringkas: dict = {}

    for pasaran, sasaran in (("KLSE", args.top_klse), ("US", args.top_us)):
        baris = tv_scan(pasaran, GATES[pasaran], limit=args.scan_limit)
        if not baris:
            print(f"  [warn] {pasaran}: scanner pulangkan 0 calon — kekalkan senarai lama", file=sys.stderr)
            akhir.extend([s for s in lama_list if s.get("market") == pasaran])
            ringkas[pasaran] = {"calon": 0, "dipilih": 0}
            continue

        # buang duplikat ikut simbol ringkas, susun ikut skor
        terbaik: dict[str, dict] = {}
        for rec in baris:
            sym = str(rec.get("name") or "").upper()
            if not sym:
                continue
            if sym not in terbaik or skor(rec) > skor(terbaik[sym]):
                terbaik[sym] = rec
        calon = sorted(terbaik.values(), key=skor, reverse=True)
        print(f"  [info] {pasaran}: {len(calon)} calon lulus tapisan "
              f"(dari {len(baris)} baris scanner)")

        dipilih: list[dict] = []
        dipakai: set[str] = set()

        # (a) anchors — guna semula entri lama (tvSymbol & kod telah disahkan)
        for sym in anchors[pasaran]:
            ent = ikut_symbol.get(sym)
            if ent:
                dipilih.append(dict(ent))
                dipakai.add(sym)

        # (b) calon terbaik minggu ini
        cache_yahoo: dict = {}
        for rec in calon:
            if len(dipilih) >= sasaran:
                break
            sym = str(rec.get("name") or "").upper()
            if not sym or sym in dipakai:
                continue
            tv = rec.get("tv") or ""
            nama_penuh = rec.get("description") or sym
            if pasaran == "KLSE":
                ticker = yahoo_cari(nama_penuh, "KLSE", cache_yahoo, simbol=sym)
                if not ticker:
                    print(f"  [skip] {sym}: kod angka Yahoo tidak dijumpai")
                    continue
                bursa = ticker.split(".")[0]
            else:
                ticker = sym
                bursa = None
            dipilih.append({
                "symbol": sym,
                "ticker": ticker,
                "tvSymbol": tv,
                "market": pasaran,
                "sector": label_sektor(rec.get("sector")),
            })
            if bursa:
                dipilih[-1]["bursaCode"] = bursa
            dipakai.add(sym)
            time.sleep(0.25)          # sopan kepada Yahoo

        akhir.extend(dipilih)
        ringkas[pasaran] = {"calon": len(calon), "dipilih": len(dipilih),
                            "anchors": len([s for s in anchors[pasaran] if s in dipakai])}

    # susun: KLSE anchors dahulu, kemudian calon skor tertinggi (susunan akhir:
    # semua KLSE kemudian semua US, mengikut skema asal laman)
    akhir.sort(key=lambda s: (0 if s.get("market") == "KLSE" else 1))

    lama_set = {str(s.get("symbol", "")).upper() for s in lama_list}
    baharu_set = {str(s.get("symbol", "")).upper() for s in akhir}
    ringkas["masuk"] = sorted(baharu_set - lama_set)
    ringkas["keluar"] = sorted(lama_set - baharu_set)
    return akhir, ringkas


def main() -> int:
    ap = argparse.ArgumentParser(description="Pilih semula watchlist screener (mingguan)")
    ap.add_argument("--watchlist", default=os.path.join(ROOT, "watchlist.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "watchlist.json"))
    ap.add_argument("--top-klse", type=int, default=55, help="bilangan kaunter Bursa dalam senarai akhir")
    ap.add_argument("--top-us", type=int, default=25, help="bilangan kaunter US dalam senarai akhir")
    ap.add_argument("--scan-limit", type=int, default=250, help="had baris diminta dari scanner")
    ap.add_argument("--anchors-klse", default=ANCHOR_KLSE)
    ap.add_argument("--anchors-us", default=ANCHOR_US)
    ap.add_argument("--dry-run", action="store_true", help="jangan tulis fail")
    args = ap.parse_args()

    mula = datetime.now(MYT)
    print(f"[{mula.isoformat(timespec='seconds')}] Penemuan watchlist mula")
    stocks, ringkas = bina(args)

    print(f"  [info] senarai akhir: {len(stocks)} kaunter "
          f"(KLSE {sum(1 for s in stocks if s['market']=='KLSE')} / "
          f"US {sum(1 for s in stocks if s['market']=='US')})")
    print(f"  [info] MASUK: {len(ringkas.get('masuk', []))} -> {ringkas.get('masuk')[:18]}")
    print(f"  [info] KELUAR: {len(ringkas.get('keluar', []))} -> {ringkas.get('keluar')[:18]}")
    for s in stocks[:8]:
        print(f"    - {s['symbol']:<10} {s['ticker']:<10} {s.get('tvSymbol',''):<14} {s.get('sector','')}")

    if args.dry_run:
        print("  [dry-run] tiada fail ditulis.")
        return 0

    payload = {
        "_nota": NOTA,
        "updated": mula.strftime("%Y-%m-%d"),
        "generatedBy": "discover_watchlist.py (mingguan)",
        "generatedAtMYT": mula.strftime("%d %b %Y, %I:%M %p (MYT)"),
        "anchors": {"KLSE": [x for x in args.anchors_klse.split(",") if x.strip()],
                    "US": [x for x in args.anchors_us.split(",") if x.strip()]},
        "ringkasan": {k: v for k, v in ringkas.items() if k in ("KLSE", "US")},
        "stocks": stocks,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"  [ok] {args.out} ditulis ({len(stocks)} kaunter)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
