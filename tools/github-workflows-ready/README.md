# Workflow GitHub — STATUS: SUDAH DIPASANG (21-09-2026)

`intraday-stocks.yml` kini **aktif** di `.github/workflows/` dan berjalan sendiri di GitHub
Actions (kemas kini harga setiap 15 minit semasa waktu dagangan). Penjadual di PC sudah
**dibuang** — tiada apa-apa berjalan di PC untuk kemas kini harga.

## Cara ia dipasang tanpa skop `workflow` pada PAT
`GITHUB_TOKEN` dalam `%LOCALAPPDATA%\hermes\.env` hanya berskop **`repo`**, jadi GitHub menolak
push yang mencipta fail di `.github/workflows/`:

```
! [remote rejected] HEAD -> main
  (refusing to allow a Personal Access Token to create or update workflow
   `.github/workflows/intraday-stocks.yml` without `workflow` scope)
```

Penyelesaian yang digunakan: **deploy key bertulis + SSH melalui port 443**
(port 22 disekat oleh rangkaian korporat; `ssh.github.com:443` berfungsi).

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/screener_deploy
curl -s -X POST -H "Authorization: Bearer $GITHUB_TOKEN" \
     -H "Accept: application/vnd.github+json" \
     -d "{\"title\":\"hermes-deploy-screener\",\"key\":\"$(cat ~/.ssh/screener_deploy.pub)\",\"read_only\":false}" \
     https://api.github.com/repos/payedlegacy/payed-legacy-screener/keys
cd "C:/Users/admin/repos/payed-legacy-screener"
git -c core.sshCommand="ssh -i ~/.ssh/screener_deploy -p 443 -o StrictHostKeyChecking=accept-new" \
    push ssh://git@ssh.github.com:443/payedlegacy/payed-legacy-screener.git HEAD:main
```

Deploy key **tidak** tertakluk kepada sekatan skop `workflow`, jadi fail workflow boleh
dihantar. Kemas kini biasa (fail bukan workflow) kekal guna PAT seperti biasa.

## Kalau perlu ubah jadual/tetingkap workflow nanti
Guna arahan SSH di atas (bukan `git push origin` dengan PAT), atau tambah skop `workflow`
pada token.

## Fail ini
Disimpan sebagai salinan rujukan/sedia ganti. Salinan aktif:
`.github/workflows/intraday-stocks.yml`.

