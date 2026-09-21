# Workflow GitHub sedia dipasang (perlu skop `workflow`)

Fail di folder ini **belum aktif** — ia salinan workflow "Kemas Kini Intraday stocks.json
(15 minit)" yang boleh dipasang ke `.github/workflows/` bila-bila masa.

## Kenapa belum dipasang?
`GITHUB_TOKEN` dalam `%LOCALAPPDATA%\hermes\.env` hanya mempunyai skop **`repo`**.
GitHub menolak sebarang push yang mencipta/mengubah fail di bawah `.github/workflows/`:

```
! [remote rejected] HEAD -> main
  (refusing to allow a Personal Access Token to create or update workflow
   `.github/workflows/intraday-stocks.yml` without `workflow` scope)
```

## Cara memasang (pilih satu)

### Pilihan A — tambah skop `workflow` pada token (disyorkan untuk jangka panjang)
1. Buka https://github.com/settings/tokens → token klasik yang digunakan → **Edit**
2. Tanda skop **`workflow`** (biarkan `repo`), simpan
3. Kemudian:
   ```bash
   cd "C:/Users/admin/repos/payed-legacy-screener"
   cp tools/github-workflows-ready/intraday-stocks.yml .github/workflows/intraday-stocks.yml
   git add .github/workflows/intraday-stocks.yml
   git commit -m "Aktifkan workflow intraday 15 minit (cabang data)"
   git push origin main
   ```
4. Setelah ini, kemas kini intraday berjalan di awan (GitHub Actions) walaupun PC dimatikan.

### Pilihan B — kekal dengan penjadual di PC (sedang berjalan)
Skrip `%LOCALAPPDATA%\hermes\scripts\screener-intraday.sh` (cron Hermes, setiap 15 minit)
sudah melakukan kerja yang sama: menjana stocks.json dan menerbitkannya ke cabang `data`.
Kelebihannya tiada token baharu diperlukan; kelemahannya PC mesti hidup dan berinternet.

## Hasil kedua-dua pilihan
Cabang `data` menerima satu commit sahaja (force-push) yang mengandungi `stocks.json`
terkini. Laman web membacanya melalui
`https://raw.githubusercontent.com/payedlegacy/payed-legacy-screener/data/stocks.json`
dan memilih sumber yang paling baharu antara salinan itu dengan fail yang di-deploy.
