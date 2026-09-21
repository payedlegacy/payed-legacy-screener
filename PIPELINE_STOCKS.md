# Auto-Data Pipeline — screener.payedlegacy.my

Sistem kemas kini automatik data saham. **Tiada muat naik manual** — data ditarik,
ditulis ke `stocks.json`, di-commit dan di-push ke `main` oleh GitHub Actions.
Push ke `main` mencetuskan auto-deploy Vercel.

## Aliran kerja

```
Yahoo Finance (harga, RSI, MACD, MA, PE, dividen)   SC Malaysia (PDF senarai Syariah)
                 |                                                  |
                 +--------------- fetch_live_data.py ---------------+
                                       |
                                 stocks.json  (repo root)
                                       |
                        git commit + push  ->  Vercel deploy
                                       |
                        index.html (fetch stocks.json) -> paparan + timestamp
```

## Fail

| Fail | Fungsi |
|---|---|
| `fetch_live_data.py` | Skrip penarik data (yfinance + senarai Syariah SC). Tulis `stocks.json`. |
| `watchlist.json` | Senarai kaunter yang dipantau (tambah/buang kaunter di sini sahaja). |
| `shariah_overrides.json` | Sandaran status Syariah Bursa jika PDF SC gagal dimuat turun. |
| `requirements-stocks.txt` | Kebergantungan Python (`yfinance`, `pypdf`). |
| `.github/workflows/update-stocks.yml` | Penjadual: Mon–Fri 17:45 MYT & 06:00 MYT. |
| `stocks.json` | Output — dibaca oleh `index.html`. |

## Jadual (GitHub Actions, cron UTC)

| Cron | Masa Malaysia | Sebab |
|---|---|---|
| `45 9 * * 1-5` | 17:45 (Isnin–Jumaat) | Selepas Bursa Malaysia tutup (17:00 MYT) |
| `0 22 * * 1-5` | 06:00 keesokan (Selasa–Sabtu) | Selepas US Market tutup (16:00 ET) |
| `workflow_dispatch` | Manual | Butang "Run workflow" di tab Actions |
| `push` pada fail pipeline | — | Menguji perubahan skrip serta-merta |

## Data yang ditarik setiap kali

- **Symbol & nama syarikat** — nama diambil terus dari sumber data, jadi penjenamaan
  semula adalah automatik (contoh: `MYEG` kini dipaparkan sebagai **Zetrix AI Berhad**).
  Perubahan nama direkod dalam `meta.notes`.
- **Harga penutup & perubahan %** (berserta OHLC, 52-minggu tinggi/rendah, volum purata).
- **Teknikal** — RSI(14) Wilder, MA20/MA50/MA200, MACD(12,26,9) + signal/histogram,
  corak candlestick (Doji, Hammer, Shooting Star, Engulfing, Marubozu, dll).
- **Fundamental** — PE (trailing), kadar dividen (TTM/dividen sebenar ÷ harga), sektor.
- **Status Syariah** — untuk kaunter Bursa Malaysia: senarai rasmi SC
  ("List of Shariah-compliant Securities", dikemas kini setiap hujung Jumaat terakhir
  Mei & November). Kod kaunter yang tiada dalam senarai = tidak patuh Syariah.
  Untuk saham US: heuristik AAOIFI (anggaran) — ditanda dalam `shariahSource`.

## Ujian manual (PC)

```bash
pip install -r requirements-stocks.txt
python fetch_live_data.py                        # kemas kini penuh 24 kaunter
python fetch_live_data.py --symbols NVDA,AAPL    # uji pantas
python fetch_live_data.py --offline-shariah      # tanpa muat turun PDF SC
```

## Nota operasi

- Repositori mesti mempunyai **Actions diaktifkan**. Workflow berjadual dilumpuhkan
  automatik oleh GitHub selepas ~60 hari tiada aktiviti repo — buka tab Actions dan
  klik "Enable workflow" jika perlu, atau buat sebarang commit.
- `GITHUB_TOKEN` (diberikan automatik) mempunyai `contents: write` melalui blok
  `permissions` — tidak perlu token tambahan.
- Jika Yahoo Finance gagal bagi sesetengah simbol, rekod simbol itu **dikekalkan**
  dari `stocks.json` sebelum ini dan dicatat dalam `meta.notes` / `meta.failedSymbols`.
- Bursa Malaysia mengumumkan senarai Syariah pada hujung Jumaat terakhir Mei/November;
  pipeline akan menangkap senarai baharu secara automatik pada run berikutnya.
