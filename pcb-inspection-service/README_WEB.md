# PCB Vision Web Demo

Web UI interaktif untuk demo hackathon PCB Missing Component Detection.

## Menjalankan di localhost

Buka PowerShell di folder proyek ini, lalu jalankan:

```powershell
python -m pip install -r requirements.txt
python run_web.py
```

Buka `http://127.0.0.1:8000` di browser.

Alternatif dengan auto-reload saat mengembangkan UI:

```powershell
python -m uvicorn backend.main:app --reload
```

## Alur demo

- **Arduino UNO** dan **ESP32-WROOM** memakai kamera browser. Saat board dipilih, browser otomatis meminta izin kamera. Tekan `INSPECT BOARD` untuk mengirim satu frame ke pipeline alignment + YOLO.
- **Arduino Nano**, **Orange Pi 3B V1.2**, dan **Raspberry Pi 4 Model B** menampilkan reference normal serta sample normal/missing. Pilih sample, lalu tekan `INSPECT BOARD` untuk membandingkan slot komponen.
- Hasil akan menampilkan status `PASS` atau `FAIL`, annotated image, jumlah slot missing, dan koordinat lokasi yang ditandai.

## Catatan kamera

Kamera membutuhkan izin browser dan biasanya bekerja pada `localhost` atau `127.0.0.1`. Jika akses kamera tidak tersedia, tombol `UPLOAD FRAME` dapat dipakai untuk mengirim foto PCB.

Model kamera (`models/best.pt`) membutuhkan dependency PyTorch dan Ultralytics pada `requirements.txt`. Alur database tetap dapat digunakan dengan dependency OpenCV dan NumPy.
