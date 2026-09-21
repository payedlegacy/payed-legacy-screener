#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_live_data.py — Auto-Data Pipeline untuk screener.payedlegacy.my
=====================================================================
Tujuan: menarik data pasaran (Bursa Malaysia + US) secara AUTOMATIK dan menulis
`stocks.json` yang dibaca oleh index.html. Dijalankan oleh GitHub Actions
(.github/workflows/update-stocks.yml) setiap hari bekerja selepas pasaran tutup —
tiada muat naik manual diperlukan.

Sumber data:
  * Harga / volum / penunjuk teknikal / fundamental : Yahoo Finance (perpustakaan `yfinance`)
  * Status Syariah (Bursa Malaysia)                 : Suruhanjaya Sekuriti Malaysia (SC),
      "List of Shariah-compliant Securities" — PDF rasmi dikesan & dimuat turun automatik
      (senarai dikemas kini setiap hujung Jumaat terakhir Mei & November).
  * Status Syariah (US)                             : heuristik AAOIFI (anggaran; ditanda dalam JSON)

Penggunaan:
  python fetch_live_data.py                      # tulis stocks.json (default)
  python fetch_live_data.py --symbols NVDA,AAPL  # hanya simbol terpilih
  python fetch_live_data.py --offline-shariah    # langkau muat turun senarai SC
  python fetch_live_data.py --out stocks.json --watchlist watchlist.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

MYT = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

SC_LIST_PAGE = "https://www.sc.com.my/development/icm/shariah-compliant-securities/list-of-shariah-compliant-securities"

MONTHS_BM = {1: "Jan", 2: "Feb", 3: "Mac", 4: "Apr", 5: "Mei", 6: "Jun",
             7: "Jul", 8: "Ogo", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Dis"}


# --------------------------------------------------------------------------
# Utiliti HTTP
# --------------------------------------------------------------------------
def http_get(url: str, timeout: int = 60, binary: bool = False, attempts: int = 3):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9,ms;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            return data if binary else data.decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 + 3 * i)
    print(f"  [warn] gagal muat turun {url[:90]} -> {last}", file=sys.stderr)
    return None


# --------------------------------------------------------------------------
# Penunjuk teknikal
# --------------------------------------------------------------------------
def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values, period):
    if not values:
        return []
    k = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes, period: int = 14):
    """RSI Wilder (14)."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))


def macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    line = [a - b for a, b in zip(ef, es)]
    sig = ema_series(line, signal)
    hist = [a - b for a, b in zip(line, sig)]
    state = "BULLISH" if hist[-1] >= 0 else "BEARISH"
    if len(hist) >= 2:
        if hist[-2] < 0 <= hist[-1]:
            state = "GOLDEN CROSS"
        elif hist[-2] > 0 >= hist[-1]:
            state = "DEATH CROSS"
    return {
        "macd": round(line[-1], 4),
        "macdSignal": round(sig[-1], 4),
        "macdHist": round(hist[-1], 4),
        "macdState": state,
    }


def candle_patterns(o, h, l, c, po, pc):
    """Corak candlestick bar terakhir (+ corak 2 bar dgn bar sebelumnya)."""
    pats = []
    rng = h - l
    if rng <= 0:
        return pats
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    bull = c >= o
    prev_bull = pc >= po
    prev_body = abs(pc - po)

    if body <= 0.10 * rng:
        pats.append("Doji")
    if body >= 0.90 * rng:
        pats.append("Bullish Marubozu" if bull else "Bearish Marubozu")
    if body > 0 and lower >= 2.0 * body and upper <= 0.6 * body:
        pats.append("Hammer" if bull else "Hanging Man")
    if body > 0 and upper >= 2.0 * body and lower <= 0.6 * body:
        pats.append("Shooting Star" if not bull else "Inverted Hammer")
    if (not prev_bull) and bull and c >= po and o <= pc and body > prev_body:
        pats.append("Bullish Engulfing")
    if prev_bull and (not bull) and c <= po and o >= pc and body > prev_body:
        pats.append("Bearish Engulfing")
    return pats


def fmt_volume(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if v >= div:
            return f"{v / div:.1f}{unit}"
    return f"{v:.0f}"


def map_sector(yahoo_sector: str | None, override: str | None = None) -> str:
    if override:
        return override
    s = (yahoo_sector or "").lower()
    table = [
        (("financial", "insurance"), "Finance"),
        (("technolog", "communication", "semiconductor"), "Technology"),
        (("real estate", "property"), "Property"),
        (("utilit",), "Utilities"),
        (("health",), "Healthcare"),
        (("energy", "oil"), "Energy"),
        (("basic material", "chem", "mining"), "Materials"),
        (("industrial",), "Industrials"),
        (("consumer",), "Consumer"),
    ]
    for keys, val in table:
        if any(k in s for k in keys):
            return val
    return "Lain-lain"


# --------------------------------------------------------------------------
# Status Syariah
# --------------------------------------------------------------------------
def fetch_sc_shariah_list() -> tuple[dict | None, str | None, int]:
    """Kesan senarai patuh Syariah SC terkini, muat turun PDF, pulangkan {kod: nama}."""
    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        print("  [warn] pypdf tiada — langkau senarai SC rasmi")
        return None, None, 0

    page = http_get(SC_LIST_PAGE)
    if not page:
        return None, None, 0
    entries = re.findall(r'\{"name":"(.*?)","file_path":"(.*?)","date_published":"(.*?)"', page)
    if not entries:
        print("  [warn] struktur halaman SC berubah — guna override")
        return None, None, 0

    def parse_date(d):
        for f in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(d.strip(), f)
            except ValueError:
                continue
        return datetime(1970, 1, 1)

    name, path, pub = max(entries, key=lambda e: parse_date(e[2]))
    print(f"  [info] senarai SC terkini: {name.strip()[:70]} ({pub})")
    pdf_bytes = http_get(path, binary=True, timeout=120)
    if not pdf_bytes:
        return None, None, 0

    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".sc_shariah_tmp.pdf")
    with open(tmp, "wb") as fh:
        fh.write(pdf_bytes)
    try:
        reader = PdfReader(tmp)
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    text = text.replace("\u00ad", "")
    heads = list(re.finditer(
        r"LIST OF SHARIAH-COMPLIANT SECURITIES\s*[-\u2013]\s*(MAY|NOV|MEI|NOVEMBER)\s*(\d{4})",
        text, re.I))
    if not heads:
        print("  [warn] jadual lampiran tidak dijumpai dlm PDF SC")
        return None, None, 0
    body = text[heads[-1].start():]

    codes = []
    for m in re.finditer(r"(?<![\dA-Za-z])(\d{4})(?![\dA-Za-z%])", body):
        code = m.group(1)
        if code[:2] in ("19", "20"):      # buang angka tahun (2019..2026)
            continue
        codes.append(code)
    uniq = {}
    for c in codes:
        uniq.setdefault(c, None)
    iso = parse_date(pub).strftime("%Y-%m-%d")
    print(f"  [info] {len(uniq)} kod patuh Syariah diekstrak (kuatkuasa {iso})")
    return uniq, iso, len(uniq)


def shariah_us(sector: str, total_debt, market_cap) -> tuple[bool, str]:
    """Heuristik AAOIFI (anggaran) untuk saham US."""
    src = "Heuristik AAOIFI (anggaran)"
    if sector == "Finance":
        return False, src
    try:
        if total_debt and market_cap and (float(total_debt) / float(market_cap)) > 0.33:
            return False, src
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return True, src


# --------------------------------------------------------------------------
# Tarikan data saham
# --------------------------------------------------------------------------
def fetch_symbol(cfg: dict, retries: int = 3) -> dict:
    import yfinance as yf  # noqa: PLC0415

    ticker = cfg["ticker"]
    last_err = None
    for attempt in range(retries):
        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(period="max", interval="1d", auto_adjust=False)
            if hist is None or len(hist) < 30:
                raise RuntimeError("sejarah harga tidak mencukupi")
            try:
                info = tk.info or {}
            except Exception:  # noqa: BLE001
                info = {}

            o = [float(x) for x in hist["Open"].tolist()]
            h = [float(x) for x in hist["High"].tolist()]
            l = [float(x) for x in hist["Low"].tolist()]
            c = [float(x) for x in hist["Close"].tolist()]
            v = [float(x or 0) for x in hist["Volume"].tolist()]
            divs = [float(x) for x in hist["Dividends"].tolist()] if "Dividends" in hist else []

            price = c[-1]
            prev = c[-2] if len(c) > 1 else price
            change = ((price - prev) / prev * 100.0) if prev else 0.0

            name = (info.get("longName") or info.get("shortName")
                    or cfg.get("name") or ticker)
            short = info.get("shortName") or cfg.get("shortName") or cfg.get("symbol", ticker)
            sector = map_sector(info.get("sector"), cfg.get("sector"))

            pe = info.get("trailingPE") or info.get("forwardPE")
            if pe is not None:
                try:
                    pe = round(float(pe), 2)
                    if pe <= 0 or pe > 5000:
                        pe = None
                except (TypeError, ValueError):
                    pe = None

            div_ttm = sum(divs[-252:]) if divs else 0.0
            if div_ttm > 0 and price:
                div_yield = round(div_ttm / price * 100.0, 2)
            else:
                dy = info.get("dividendYield")
                div_yield = round(float(dy), 2) if isinstance(dy, (int, float)) else 0.0

            rsi_val = rsi(c, 14)
            macd_vals = macd(c) or {}
            ma20, ma50, ma200 = sma(c, 20), sma(c, 50), sma(c, 200)

            # --- EMA (7/21 & 20/50) + bendera preset screener -----------------
            def _last(seq):
                return seq[-1] if seq else None

            e7, e21 = _last(ema_series(c, 7)), _last(ema_series(c, 21))
            e20, e50, e200 = _last(ema_series(c, 20)), _last(ema_series(c, 50)), _last(ema_series(c, 200))
            ema7_21 = bool(e7 and e21 and e7 > e21)
            ema20_50 = bool(e20 and e50 and e20 > e50)
            ema_support = bool(price and e50 and e200 and price > e50 and e50 > e200)

            trend = "NEUTRAL"
            if ma20 and ma50 and ma200:
                if price > ma20 > ma50 > ma200:
                    trend = "BULLISH KUAT"
                elif price > ma50 and ma50 > ma200:
                    trend = "BULLISH"
                elif price < ma20 < ma50 and ma50 < ma200:
                    trend = "BEARISH"
                elif price < ma200:
                    trend = "LEMAH"
            avg_vol = sma(v, 20) or 0
            vol_ratio = (v[-1] / avg_vol) if avg_vol else 0

            hi52 = max(h[-252:]) if len(h) >= 252 else max(h)
            lo52 = min(l[-252:]) if len(l) >= 252 else min(l)
            high_all = max(h)                      # puncak tertinggi sejarah penuh (ATH sebenar)
            high52w = bool(hi52 and price >= hi52 * 0.97)
            ath = bool(high_all and price >= high_all * 0.995)
            pct_high52 = round((price / hi52 - 1.0) * 100.0, 2) if hi52 else None

            pats = candle_patterns(o[-1], h[-1], l[-1], c[-1], o[-2], c[-2])

            # ---- Enjin Global Mega-Breakout & Volume Surge -------------------
            # ID: global_breakout_momentum_scanner
            # Isyarat pergerakan besar (breakout/volume surge) untuk Bursa Malaysia
            # dan pasaran US. Semua nilai dikira daripada sejarah harga sebenar.
            e7s, e21s = ema_series(c, 7), ema_series(c, 21)
            ema_cross = bool(len(e7s) > 1 and len(e21s) > 1
                             and e7s[-1] > e21s[-1] and e7s[-2] <= e21s[-2])
            vol_spike = bool(avg_vol and v[-1] >= avg_vol * 1.5)
            momentum = bool(change >= 1.5)
            near_high = bool(hi52 and price >= hi52 * 0.97)
            rsi_healthy = bool(rsi_val is not None and 45.0 <= rsi_val <= 70.0)
            breakout_score = ((35 if vol_spike else 0) + (30 if momentum else 0)
                              + (25 if ema_cross else 0) + (10 if near_high else 0)
                              + (5 if rsi_healthy else 0))
            if vol_spike and (ema_cross or momentum):
                breakout_state = "🚀 VOLUME SPIKE & BREAKOUT"
            elif vol_spike:
                breakout_state = "📊 VOLUME SURGE"
            elif ema_cross:
                breakout_state = "⚡ EMA 7/21 CROSSOVER"
            elif momentum:
                breakout_state = "📈 MOMENTUM NAIK"
            else:
                breakout_state = "—"

            exch = str(info.get("exchange") or "").upper()
            _sym = cfg.get("symbol") or ticker.split(".")[0]
            if cfg["market"] == "KLSE":
                tv_symbol = f"MYX:{_sym}"
            elif exch in ("NYQ", "NYS"):
                tv_symbol = f"NYSE:{_sym}"
            elif exch in ("ASE", "AMX", "PCX"):
                tv_symbol = f"AMEX:{_sym}"
            else:
                tv_symbol = f"NASDAQ:{_sym}"

            # ---- isyarat hybrid (kunci dikekalkan utk preset screener) ----
            signal = "NEUTRAL"
            state = macd_vals.get("macdState", "")
            if vol_spike and (ema_cross or momentum):
                signal = "🚀 Volum Spike & Breakout"
            elif rsi_val is not None and rsi_val < 35:
                signal = "🟢 Buy On Dip (Oversold)"
            elif ema_cross:
                signal = "⚡ EMA 7/21 Crossover"
            elif state == "GOLDEN CROSS" or (trend in ("BULLISH KUAT", "BULLISH")
                                            and state == "BULLISH" and price >= hi52 * 0.97):
                signal = "✨ GOLDEN CROSS"
            elif change >= 2.0 and vol_ratio >= 1.5:
                signal = "🚀 BREAKOUT"
            elif div_yield >= 5.0:
                signal = "💰 RAJA DIVIDEN"
            elif price >= hi52 * 0.98 and vol_ratio >= 1.2:
                signal = "🚀 BREAKOUT"
            elif div_yield >= 3.0:
                signal = "💰 RAJA DIVIDEN"
            elif momentum:
                signal = "📈 Trend Pemulihan"

            data = {
                "symbol": cfg.get("symbol") or ticker.split(".")[0],
                "ticker": ticker,
                "name": name,
                "shortName": short,
                "market": cfg["market"],
                "currency": info.get("currency") or ("MYR" if cfg["market"] == "KLSE" else "USD"),
                "sector": sector,
                # harga
                "price": round(price, 4),
                "prevClose": round(prev, 4),
                "change": round(change, 2),
                "open": round(o[-1], 4),
                "dayHigh": round(h[-1], 4),
                "dayLow": round(l[-1], 4),
                "high52": round(hi52, 4),
                "low52": round(lo52, 4),
                "highAll": round(high_all, 4),
                "high52w": high52w,
                "ath": ath,
                "pctHigh52": pct_high52,
                "volume": fmt_volume(v[-1]),
                "avgVolume": fmt_volume(avg_vol),
                "volumeRatio": round(vol_ratio, 2),
                # teknikal
                "rsi": round(rsi_val, 1) if rsi_val is not None else None,
                "ma20": round(ma20, 4) if ma20 else None,
                "ma50": round(ma50, 4) if ma50 else None,
                "ma200": round(ma200, 4) if ma200 else None,
                "trend": trend,
                # EMA & bendera preset (dikira drpd sejarah harga sebenar)
                "ema7": round(e7, 4) if e7 else None,
                "ema21": round(e21, 4) if e21 else None,
                "ema20": round(e20, 4) if e20 else None,
                "ema50": round(e50, 4) if e50 else None,
                "ema200": round(e200, 4) if e200 else None,
                "ema7_21": ema7_21,
                "ema20_50": ema20_50,
                "emaSupport": ema_support,
                "macd": macd_vals.get("macd"),
                "macdSignal": macd_vals.get("macdSignal"),
                "macdHist": macd_vals.get("macdHist"),
                "macdState": state or None,
                "patterns": pats,
                "patternSummary": ", ".join(pats) if pats else "",
                # fundamental
                "pe": pe,
                "divYield": div_yield,
                "dividendTTM": round(div_ttm, 4),
                "totalDebt": info.get("totalDebt"),
                "marketCap": info.get("marketCap"),
                # isyarat & kemas kini
                "signal": signal,
                # ---- Global Mega-Breakout & Volume Surge (global_breakout_momentum_scanner) ----
                "scannerId": "global_breakout_momentum_scanner",
                "tvSymbol": tv_symbol,
                "breakoutState": breakout_state,
                "breakoutScore": int(breakout_score),
                "volSpikeFlag": vol_spike,
                "momentumFlag": momentum,
                "emaCross7_21": ema_cross,
                "breakout": {
                    "volSpike": vol_spike,
                    "momentum": momentum,
                    "emaCross": ema_cross,
                    "nearHigh52": near_high,
                    "rsiHealthy": rsi_healthy,
                    "score": int(breakout_score),
                    "state": breakout_state,
                    "volRatio": round(vol_ratio, 2),
                },
                "sampleDate": str(hist.index[-1].date()),
                "updatedAt": datetime.now(MYT).isoformat(timespec="seconds"),
            }
            return data
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{ticker}: {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Auto-update data saham -> stocks.json")
    ap.add_argument("--watchlist", default=os.path.join(ROOT, "watchlist.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "stocks.json"))
    ap.add_argument("--overrides", default=os.path.join(ROOT, "shariah_overrides.json"))
    ap.add_argument("--symbols", default="", help="Senarai simbol dipisah koma (uji pantas)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--offline-shariah", action="store_true",
                    help="Jangan muat turun senarai SC; guna override/state sebelum")
    args = ap.parse_args()

    started = datetime.now(MYT)
    print(f"[{started.isoformat(timespec='seconds')}] Auto-data pipeline mula")

    with open(args.watchlist, encoding="utf-8") as fh:
        wl = json.load(fh)
    watch = wl["stocks"] if isinstance(wl, dict) else wl
    if args.symbols:
        want = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        watch = [w for w in watch if w["symbol"].upper() in want or w["ticker"].upper() in want]
    print(f"  [info] {len(watch)} simbol dalam watchlist")

    # --- state sebelum (utk kekalkan simbol yg gagal) ---
    prev_stocks = {}
    prev_meta = {}
    if os.path.exists(args.out):
        try:
            with open(args.out, encoding="utf-8") as fh:
                old = json.load(fh)
            prev_stocks = {s["symbol"]: s for s in old.get("stocks", [])}
            prev_meta = old.get("meta", {})
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] stocks.json lama tidak boleh dibaca: {exc}")

    # --- senarai Syariah SC ---
    overrides = {}
    if os.path.exists(args.overrides):
        with open(args.overrides, encoding="utf-8") as fh:
            ov_raw = json.load(fh)
        if isinstance(ov_raw, dict):
            overrides = ov_raw.get("codes", ov_raw)
        if not isinstance(overrides, dict):
            overrides = {}
        overrides = {k: v for k, v in overrides.items() if not k.startswith("_")}
    sc_codes, sc_date, sc_count = (None, None, 0)
    if not args.offline_shariah:
        sc_codes, sc_date, sc_count = fetch_sc_shariah_list()
    if sc_codes is None:
        sc_date = prev_meta.get("shariahListDate")
        sc_count = prev_meta.get("shariahListCount", 0)

    # --- tarik data harga ---
    results, failed = {}, []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(fetch_symbol, cfg): cfg for cfg in watch}
        for fut in as_completed(futs):
            cfg = futs[fut]
            try:
                res = fut.result()
                results[res["symbol"]] = res
                print(f"  [ok]   {res['symbol']:<9} {res['price']:>10.3f} "
                      f"({res['change']:+.2f}%) RSI {res['rsi']}")
            except Exception as exc:  # noqa: BLE001
                failed.append(cfg["symbol"])
                print(f"  [FAIL] {cfg['symbol']}: {exc}", file=sys.stderr)

    # --- kedudukan Syariah + gabung simbol gagal ---
    notes = []
    out_stocks = []
    for cfg in watch:
        sym = cfg["symbol"]
        rec = results.get(sym)
        if rec is None:
            old = prev_stocks.get(sym)
            if old:
                out_stocks.append(old)
                notes.append(f"{sym}: data lama dikekalkan (tarikan gagal)")
            continue
        code = (cfg.get("bursaCode") or cfg["ticker"].split(".")[0]).strip()
        if cfg["market"] == "KLSE" and sc_codes is not None:
            rec["shariah"] = code in sc_codes
            rec["shariahSource"] = f"SC — Senarai Sekuriti Patuh Syariah ({sc_date})"
        elif cfg["market"] == "KLSE" and code in overrides:
            val = overrides[code]
            rec["shariah"] = bool(val.get("shariah")) if isinstance(val, dict) else bool(val)
            src = val.get("source", "SC") if isinstance(val, dict) else "SC"
            rec["shariahSource"] = f"Override manual ({src})"
        elif cfg["market"] == "KLSE":
            rec["shariah"] = bool(cfg.get("shariahFallback", False))
            rec["shariahSource"] = "Anggaran (senarai SC tidak tersedia)"
        else:
            ok, src = shariah_us(rec["sector"], rec.get("totalDebt"), rec.get("marketCap"))
            rec["shariah"] = ok
            rec["shariahSource"] = src
        rec["shariahListDate"] = sc_date
        prev_name = (prev_stocks.get(sym) or {}).get("name")
        if prev_name and prev_name != rec["name"]:
            notes.append(f"{sym}: nama syarikat dikemas kini — '{prev_name}' -> '{rec['name']}'")
        out_stocks.append(rec)

    order = {c["symbol"]: i for i, c in enumerate(watch)}
    out_stocks.sort(key=lambda s: order.get(s["symbol"], 999))

    now = datetime.now(MYT)
    klse = [s for s in out_stocks if s["market"] == "KLSE"]
    us = [s for s in out_stocks if s["market"] == "US"]
    payload = {
        "meta": {
            "generatedAt": now.isoformat(timespec="seconds"),
            "generatedAtMYT": (f"{now.day:02d} {MONTHS_BM[now.month]} {now.year}, "
                               f"{now.strftime('%I:%M %p').lstrip('0')} (MYT)"),
            "generatedAtUTC": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "symbolCount": len(out_stocks),
            "klseCount": len(klse),
            "usCount": len(us),
            "mySessionDate": max([s.get("sampleDate", "") for s in klse], default=None),
            "usSessionDate": max([s.get("sampleDate", "") for s in us], default=None),
            "shariahSource": "Suruhanjaya Sekuriti Malaysia (SC)",
            "shariahListDate": sc_date,
            "shariahListCount": sc_count,
            "priceSource": "Yahoo Finance (yfinance)",
            "scanner": "Global Mega-Breakout & Volume Surge Screener",
            "scannerId": "global_breakout_momentum_scanner",
            "breakoutCount": sum(
                1 for s in out_stocks
                if (s.get("breakout") or {}).get("volSpike")
                and ((s.get("breakout") or {}).get("momentum") or (s.get("breakout") or {}).get("emaCross"))
            ),
            "volSpikeCount": sum(1 for s in out_stocks if (s.get("breakout") or {}).get("volSpike")),
            "topBreakouts": [
                {
                    "symbol": s.get("symbol"),
                    "market": s.get("market"),
                    "state": (s.get("breakout") or {}).get("state"),
                    "score": (s.get("breakout") or {}).get("score"),
                    "change": s.get("change"),
                    "volumeRatio": s.get("volumeRatio"),
                }
                for s in sorted(
                    [x for x in out_stocks if (x.get("breakout") or {}).get("score", 0) > 0],
                    key=lambda x: -((x.get("breakout") or {}).get("score") or 0),
                )[:8]
            ],
            "failedSymbols": failed,
            "notes": notes,
        },
        "stocks": out_stocks,
    }

    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    dur = (datetime.now(MYT) - started).total_seconds()
    print(f"[ok] {args.out} ditulis — {len(out_stocks)} simbol, gagal: {failed or 'tiada'} ({dur:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
