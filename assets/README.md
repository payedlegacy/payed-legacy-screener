# Folder aset — Screener Payed Legacy

## DuitNow QR (slot sumbangan)

Fail semasa: `assets/duitnow-qr.png` — kod QR DuitNow BSN atas nama **Mohamad Farid Bin Mat**
(sumber asal: `D:\MFM\DESK DAESH\Hermes File\saham\QR Duit Now.jpeg`, 414x519 px, ditukar ke PNG).

Untuk menukar QR: ganti fail ini dengan PNG baharu (nama fail mesti kekal sama).
Kod akan memaparkannya di:
- seksyen `#rujukan` → blok "Sokong Kami / Support Us" (gambar penuh, boleh klik untuk buka saiz penuh)
- modal sumbangan (`donationModal`, butang "Sokong Web" di nav)

Status slot di kad "DuitNow QR / TNG eWallet" akan bertukar kepada AKTIF apabila imej berjaya dimuat
(fungsi `initDuitNow()` / `duitnowQrLoaded()` / `duitnowQrFallback()` dalam index.html).

Pilihan: isi `const DUITNOW_ID = "..."` dalam blok skrip utama index.html untuk memaparkan
butang "Salin DuitNow ID" dalam modal sumbangan.
