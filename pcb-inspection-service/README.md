# PCB Missing Component Detection

Proyek ini memeriksa apakah komponen penting pada PCB masih terpasang.

| Board | Mode | Cara kerja |
|---|---|---|
| Arduino UNO | Kamera | Alignment PCB + deteksi komponen YOLO + pencocokan ke slot reference |
| ESP32-WROOM | Kamera | Alignment PCB + deteksi komponen YOLO + pencocokan ke slot reference |
| Arduino Nano | Database | Alignment ke foto normal + perbandingan per-slot |
| Orange Pi 3B V1.2 | Database | Alignment ke foto normal + perbandingan per-slot |
| Raspberry Pi 4 Model B | Database | Alignment ke foto normal + perbandingan per-slot |

## Instalasi

Gunakan Python 3.10 atau lebih baru. Untuk inspeksi database, OpenCV dan NumPy
sudah cukup. Untuk mode kamera, install seluruh dependensi agar `best.pt` dapat
dijalankan.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Menjalankan inspeksi

### Mode menu interaktif

Cara paling mudah untuk mencoba gambar yang tersedia:

```powershell
python run_inspection.py
```

Pilih board, kemudian pilih gambar normal atau missing yang ditampilkan dari
folder `inspection_image`. Tidak perlu mengetik path gambar panjang.

### Kamera: Arduino UNO atau ESP32

```powershell
python run_inspection.py --board arduino_uno --camera 0
python run_inspection.py --board esp32 --camera 0
```

Kontrol jendela kamera: `I`/`Space` untuk inspeksi, `S` untuk menyimpan preview,
dan `Q` untuk keluar. Jika index kamera berbeda, coba `--camera 1` atau `--camera 2`.

Untuk uji tanpa membuka kamera:

```powershell
python run_inspection.py --board arduino_uno --image path\frame.jpg --no-display
python run_inspection.py --board esp32 --image path\frame.jpg --no-display
```

### Database: Arduino Nano, Orange Pi, Raspberry Pi

Mode ini memang menggunakan gambar input, bukan webcam dan bukan YOLO:

```powershell
python run_inspection.py --board arduino_nano --image inspection_image\ArduinoNano.png
python run_inspection.py --board orange_pi --image inspection_image\Orange_missingV2.png
python run_inspection.py --board raspberry_pi --image inspection_image\Rapsberry_missing.png
```

Foto normal yang disertakan dapat dipakai sebagai baseline PASS. Foto dengan
komponen ditutup/dihilangkan akan menghasilkan FAIL dan lokasi komponen diberi
kotak merah. Hasil dan laporan JSON tersimpan di `runs/`.

Threshold database dapat disetel jika kondisi kamera/pencahayaan berubah:

```powershell
$env:PCB_DB_MISSING_THRESHOLD = "0.50"
python run_inspection.py --board orange_pi --image path\frame.jpg
```

## API demo

```powershell
uvicorn backend.main:app --reload
```

Endpoint:

- `GET /api/boards` — daftar board dan mode inspeksi.
- `POST /api/inspect/{board_id}` — upload satu gambar (`multipart/form-data`, field `file`).

Contoh PowerShell:

```powershell
curl.exe -X POST -F "file=@inspection_image\Orange_missingV2.png" `
  http://127.0.0.1:8000/api/inspect/orange_pi
```

## Catatan setup kamera

Letakkan PCB rata, seluruh papan terlihat, dan gunakan pencahayaan yang stabil.
ESP32 mencoba alignment kontur PCB terlebih dahulu, lalu ORB dan ArUco sebagai
fallback. Arduino UNO menggunakan ORB/reference dan fallback kontur. Untuk
produksi, marker ArUco pada jig dapat meningkatkan repeatability.

`models/best.pt` adalah model yang sudah disertakan di paket. Jika ingin
mengganti model, pertahankan nama file atau sesuaikan `MODEL_PATH` di
`backend/inspection_service.py`.

## Docker Compose (recommended for hackathon demo)

Backend dapat dijalankan sebagai satu service sinkron menggunakan Docker Compose.
Tidak ada background worker, queue, distributed database, atau automated data-logging
pipeline pada deployment ini. Container hanya menjalankan API FastAPI dan pipeline
inspeksi yang sudah ada.

Pastikan Docker Desktop sudah aktif, lalu dari folder proyek jalankan:

```powershell
docker compose up --build
```

Setelah container `backend` aktif, buka:

```text
http://127.0.0.1:8000
```

Untuk menampilkan log runtime secara langsung saat demo, gunakan terminal lain:

```powershell
docker compose logs -f backend
```

Saat tombol `INSPECT BOARD` ditekan dari web UI, terminal akan menampilkan access log
Uvicorn dan output runtime dari pipeline inspeksi yang sudah ada, sehingga juri dapat
melihat bahwa request benar-benar masuk ke backend dan diproses secara sinkron.

Untuk menghentikan service:

```powershell
docker compose down
```

### Alur deployment demo

```text
Browser Web UI
      |
      | POST /api/inspect/{board_id}
      v
Docker Compose
      |
      v
FastAPI Backend
      |
      +--> Alignment / Reference Matching
      |
      +--> YOLO Inference (Arduino UNO / ESP32)
      |
      v
Inspection Result (JSON)
      |
      v
Web UI
```

> Catatan: `run_web.py` dan seluruh pipeline AI tetap dapat dijalankan dengan cara
> lokal Python seperti sebelumnya. Docker Compose hanya menyediakan cara deployment
> tambahan untuk kebutuhan demonstrasi dan penilaian hackathon.

