# Inspeksi Arduino UNO dengan kamera

Pipeline Arduino UNO menggunakan `models/best.pt`, alignment terhadap
`reference_database/ArduinoUno_reference.jpg`, lalu mencocokkan deteksi YOLO
dengan slot komponen di `reference_database/ArduinoUno.json`.

## Menjalankan kamera

Dari folder project:

```powershell
python arduino_uno_camera_inspection.py --camera 2
```

Kontrol:

- `I` atau `Space`: inspeksi frame saat ini
- `S`: simpan frame mentah
- `Q`: keluar

## Menguji dengan gambar

```powershell
python arduino_uno_camera_inspection.py --image path\ke\gambar_uno.jpg --no-display
```

Contoh memakai reference yang disertakan:

```powershell
python arduino_uno_camera_inspection.py --image reference_database\ArduinoUno_reference.jpg --no-display
```

Setiap inspeksi disimpan sebagai input, hasil beranotasi, dan laporan JSON di
`runs/camera_inspection/`. Gambar debug alignment disimpan di
`runs/web_inspection/`.

Pipeline mencoba `orb_reference` untuk mengoreksi perubahan posisi/skala/sudut,
`reference_identity` hanya sebagai fallback untuk gambar canonical, dan
`direct_pcb` sebagai fallback berbasis kontur PCB.

Untuk UNO, database reference dipakai sebagai daftar kelas dan jumlah komponen,
bukan sebagai batas koordinat yang kaku. Pencocokan bersifat fleksibel terhadap
pergeseran posisi dan inspeksi menggunakan confidence lebih rendah untuk membantu
mendeteksi komponen kecil pada pencahayaan yang berubah. Namun, komponen dari
area lain tidak boleh menggantikan komponen yang tertutup: deteksi kelas yang
sama tetap harus berada di sekitar region lokal komponen tersebut.

## Dependensi

```powershell
python -m pip install -r requirements.txt
```
