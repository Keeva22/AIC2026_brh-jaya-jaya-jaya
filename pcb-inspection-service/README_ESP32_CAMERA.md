# Inspeksi ESP32-WROOM dengan kamera

Pipeline ESP32 menggunakan `models/best.pt`, alignment PCB, lalu mencocokkan
deteksi komponen dengan `reference_database/ESP32_WROOM_camera.json`.

## Menjalankan kamera

Dari folder project:

```powershell
python esp32_camera_inspection.py --camera 2
```

Kontrol:

- `I` atau `Space`: jalankan inspeksi pada frame saat ini
- `S`: simpan frame mentah
- `Q`: keluar

Jika kamera DroidCam berada pada index berbeda, gunakan `--camera 0`, `--camera 1`,
dan seterusnya. Index default dapat diubah dengan environment variable:

```powershell
$env:PCB_CAMERA_INDEX = "2"
python esp32_camera_inspection.py
```

## Menguji tanpa kamera

Mode gambar membantu memeriksa instalasi dan pipeline:

```powershell
python esp32_camera_inspection.py --image path\\ke\\frame_esp32.jpg --no-display
```

Setiap inspeksi disimpan di `runs/camera_inspection/` sebagai frame input,
gambar hasil, dan laporan JSON. Alignment membutuhkan seluruh papan ESP32
terlihat. Posisi, skala, dan pencahayaan boleh berubah karena sistem mencari
kontur PCB secara langsung; hindari kondisi ketika tepi papan tertutup atau
menyatu total dengan latar belakang.

## Dependensi

Install dependensi dari `requirements.txt` pada environment Python yang akan
digunakan untuk menjalankan project. Minimal untuk runner ini adalah OpenCV,
NumPy, dan Ultralytics/PyTorch sesuai versi model.

## Alignment langsung dari PCB, ORB, dan fallback ArUco

Pipeline sekarang mendeteksi empat sudut PCB langsung dari bentuk papan,
kemudian melakukan perspective transform ke koordinat canonical. Dengan
demikian posisi, skala, dan pencahayaan tidak perlu sama dengan foto
reference. ORB terhadap `reference_database/ESP32_WROOM_reference.jpg` hanya
menjadi cadangan jika tepi PCB tidak terbaca; ArUco adalah cadangan terakhir.

1. Install dependency karena ArUco membutuhkan `opencv-contrib-python`:

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. Opsional, buat lembar marker untuk fallback:

   ```powershell
   python tools/generate_aruco_markers.py
   ```

3. Jika memakai fallback ArUco, cetak `aruco_markers/esp32_jig_markers.png`
   pada kertas matte. Pasang
   marker pada jig kaku dengan susunan `0 = TL`, `1 = TR`, `2 = BR`, dan
   `3 = BL`. PCB harus berada di dalam empat marker, tetapi tidak perlu
   ditempatkan pada posisi piksel yang sama seperti kamera reference.

4. Jalankan inspeksi seperti biasa. Gambar debug akan menampilkan
   `Alignment: direct_pcb` jika sistem memakai kontur PCB, yaitu mode normal
   yang diharapkan. `Alignment: orb_reference` berarti fitur reference dipakai
   sebagai cadangan.
   `Alignment: aruco_fallback` berarti sistem memakai marker.

ID marker dapat diganti tanpa mengubah kode:

```powershell
$env:PCB_ARUCO_IDS = "10,11,12,13"
python esp32_camera_inspection.py --camera 2
```
