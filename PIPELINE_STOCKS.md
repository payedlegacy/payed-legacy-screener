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
- **Teknikal** — RSI(14) Wilder, MA20/MA50/MA200, EMA7/EMA21/EMA20/EMA50/EMA200,
  MACD(12,26,9) + signal/histogram, corak candlestick (Doji, Hammer, Shooting Star,
  Engulfing, Marubozu, dll).
  Bendera siap-pakai untuk preset screener: `ema7_21`, `ema20_50`, `emaSupport`,
  `high52w`, `ath` (paras tertinggi **sejarah penuh** — sejarah harga ditarik
  `period="max"`), `pctHigh52`, `volumeRatio`.
- **Fundamental** — PE (trailing), kadar dividen (TTM/dividen sebenar ÷ harga), sektor.
- **Status Syariah** — untuk kaunter Bursa Malaysia: senarai rasmi SC
  ("List of Shariah-compliant Securities", dikemas kini setiap hujung Jumaat terakhir
  Mei & November). Kod kaunter yang tiada dalam senarai = tidak patuh Syariah.
  Untuk saham US: heuristik AAOIFI (anggaran) — ditanda dalam `shariahSource`.

## Kontrak data dengan `index.html` (PENTING)

`index.html` **tidak menyimpan angka lalai**. Ia membaca `/stocks.json` setiap kali
dibuka (dan menyemak semula setiap 5 minit) lalu memetakan medan melalui `adaptStock()`:

| Medan `stocks.json` | Dipetakan kepada | Nota |
|---|---|---|
| `market` = `KLSE` / `US` | `malaysia` / `america` | Penapis halaman guna `malaysia`/`america` |
| `divYield` | `div` | Kadar dividen % |
| `symbol` + `market` | `tvSymbol` | `MYX:<SYMBOL>` untuk Bursa, simbol biasa untuk US |
| `ema7_21`, `ema20_50`, `emaSupport`, `high52w`, `ath`, `volumeRatio` | bendera preset | Tiada nilai → halaman kira dari MACD/MA |
| `patterns` | chip corak candlestick | Lajur "Status EMA / Reversal" |
| `meta.generatedAtMYT`, `meta.mySessionDate`, `meta.usSessionDate` | panel "Data setakat" | + amaran amber jika data > 24 jam |
| `meta.priceSource`, `meta.shariahListDate`, `meta.symbolCount` | nota sumber | Ditulis jujur (Yahoo Finance + TradingView) |

Jika `stocks.json` gagal dimuatkan, halaman memaparkan **amaran merah dan jadual kosong** —
ia TIDAK memaparkan harga lama. Kekalkan sifat ini semasa menyunting `index.html`.

Ticker pasaran dan carta dibina secara dinamik daripada senarai kaunter `stocks.json`
menggunakan widget rasmi TradingView (`embed-widget-ticker-tape.js`,
`embed-widget-advanced-chart.js`) — bukan lagi `tv.js` lama atau simbol hardcoded.

## Auto-push dari PC (cron Hermes)

Skrip `%LOCALAPPDATA%\hermes\scripts\git-auto-push.sh` (cron harian 07:00) commit + push
perubahan tempatan untuk kedua-dua repo (`payed-legacy-web`, `payed-legacy-screener`)
guna `GITHUB_TOKEN` dalam `.env`. Ia **membuang** perubahan tempatan pada `stocks.json`
sebelum commit supaya data lama tidak menimpa data baharu yang dijana GitHub Actions.
Jika token tamat (HTTP 401 pada `https://api.github.com/user`), jana PAT baharu
(skop `repo`) dan ganti baris `GITHUB_TOKEN=` dalam `.env`.

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

## Enjin Global Mega-Breakout & Volume Surge (`global_breakout_momentum_scanner`)

Ditambah 2026-09-21. Tujuan: mengesan kaunter yang bakal membuat **pergerakan besar**
(volume surge / breakout) merentasi **Bursa Malaysia dan pasaran US** — bukan sekadar
menyaring trend.

### Apa yang dikira (setiap simbol, daripada sejarah harga sebenar)
| Medan JSON | Maksud | Ambang |
|---|---|---|
| `breakout.volSpike` | Volum hari ini vs purata 20 hari | `>= 1.5x` |
| `breakout.momentum` | Perubahan harga hari ini | `>= +1.5%` |
| `breakout.emaCross` | EMA 7 **baru** silang naik melepasi EMA 21 (bar semalam di bawah) | silang hari ini |
| `breakout.nearHigh52` | Harga hampir puncak 52 minggu | dalam 3% |
| `breakout.rsiHealthy` | RSI dalam zon sihat (bukan terlebih beli/jual) | 45–70 |
| `breakout.score` | Skor 0–100: volum 35 + momentum 30 + silang 25 + hampir puncak 10 + RSI 5 | — |
| `breakoutState` | `🚀 VOLUME SPIKE & BREAKOUT` / `📊 VOLUME SURGE` / `⚡ EMA 7/21 CROSSOVER` / `📈 MOMENTUM NAIK` / `—` | — |
| `signal` | Isyarat utama: Breakout > Buy On Dip (RSI<35) > EMA 7/21 Crossover > isyarat lama | — |
| `tvSymbol` | Simbol carta TradingView (`MYX:` / `NASDAQ:` / `NYSE:` / `AMEX:`) | — |

### Meta tambahan dalam `stocks.json`
`meta.scanner`, `meta.scannerId`, `meta.breakoutCount`, `meta.volSpikeCount`,
`meta.topBreakouts[]` (8 teratas: symbol, market, state, score, change, volumeRatio).

### Di pihak laman web (`index.html`)
- Chip tapisan baharu **🚀 Breakout global (volum + momentum)** — `PRESETS.breakout`,
  dihitung daripada `breakout.volSpike && (breakout.momentum || breakout.emaCross)`.
- Badge **🚀** pada baris jadual dan kad mudah alih untuk kaunter breakout.
- Baris status menyenaraikan breakout yang dipantau (kedua-dua pasaran) daripada `meta.topBreakouts`.

### ATURAN PENTING — kod kaunter Bursa Malaysia
Kaunter Bursa **mesti** guna kod angka Yahoo Finance (`1155.KL`, `5398.KL`, `4677.KL`).
Kod huruf seperti `MAYBANK.KL`, `TENAGA.KL`, `GAMUDA.KL` **tidak berfungsi** (Yahoo pulangkan
kosong → simbol dilangkau senyap). Tambah kaunter baharu dalam `watchlist.json` sahaja;
`market` mesti `KLSE` atau `US`, dan `bursaCode` diisi untuk kaunter Bursa (rujukan Syariah SC).

### Ujian manual di PC (tanpa pasang apa-apa ke dalam sistem)
```bash
cd "C:/Users/admin/repos/payed-legacy-screener"
uv run --quiet --with "yfinance>=1.7,<2" --with "pypdf>=6,<7" python fetch_live_data.py --out stocks.json
```
Kemudian semak `meta.breakoutCount`, `meta.topBreakouts`, dan medan `breakout` bagi setiap rekod.

