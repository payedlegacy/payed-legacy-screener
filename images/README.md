# Folder imej — Screener Payed Legacy

## DuitNow QR (slot sumbangan)

Letakkan imej QR DuitNow anda di sini dengan nama tepat:

    images/duitnow-qr.png

Keperluan:
- Format PNG (latar putih), segi empat sama, ~600x600 px.
- Ambil tangkapan skrin / eksport QR dari aplikasi bank (Maybank2u, CIMB, TNG eWallet, dll) — QR statik DuitNow.
- Selepas fail ini wujud, kad "Slot QR DuitNow" akan bertukar status kepada AKTIF secara automatik
  (fungsi `duitnowQrLoaded()` / `duitnowQrFallback()` dalam index.html) dan modal sumbangan akan memaparkan QR.

Pilihan tambahan: isi nilai `DUITNOW_ID` dalam blok skrip utama index.html (cth "0199514983")
untuk memaparkan butang "Salin DuitNow ID" dalam modal sumbangan.
