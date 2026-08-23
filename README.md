# PCBVISION — PCB Missing Component QC Inspection System

Sistem QC inspection otomatis untuk mendeteksi komponen pcb yang hilang/tidak
terpasang pada PCB, dikembangkan untuk AIC 2026. Sistem terdiri dari 3 bagian
utama yang bekerja sama secara end-to-end:

1. **CV AI Detection Module** — mendeteksi komponen PCB via kamera (YOLO) atau
   perbandingan database, lalu menentukan status FAIL/PASS.
2. **Backend API** — menerima hasil deteksi dari AI, menyimpan ke database
   (PostgreSQL), dan menyajikan data ke frontend.
3. **Web Dashboard** — menampilkan hasil inspeksi secara real-time untuk
   monitoring QC.
   
# A Hardware QC Inspection API

Backend buat sistem QC Inspection lomba AIC 2026, intinya menerima hasil scan dari sistem AI (worthy/not worthy) terus disimpan ke database (postgresql) dan ditampilkan ke dashboard frontend. Backend tidak menentukan keputusan lulus/gagalnya sendiri karena itu tugas AI/CV, disini hanya menerima, menyimpan, dan menyaji datanya.

## Code Contributors

Kontributor kode pada repository ini untuk tim BRH jaya jaya jaya, AIC 2026.

- **Backend** (FastAPI, PostgreSQL, Docker) — dikembangkan oleh Keeva Ravendra Iman ([@Keeva22](https://github.com/Keeva22))
- **CV AI Detection Module** (`pcb-inspection-service/`) — dikembangkan secara independen oleh Bagja Faishal Ramdani ([@BagjaFaishal](https://github.com/BagjaFaishal))
> **Catatan:** Modul CV AI dikembangkan secara terpisah dan diintegrasikan ke repository ini untuk keperluan submission akhir lomba.

## Cara jalanin
**Yang dibutuhkan**: Docker Desktop.
tidak perlu install python manual, semua udah dibungkus di container.

```bash
docker compose up --build
```
Setelah run command di atas, tunggu sampai muncul baris seperti ini 
di terminal: 

api-1  | INFO:     Application startup complete.

Selanjutnya buka:
- **http://localhost:8000/docs** — test semua endpoint langsung dari browser
- **http://localhost:8000** — base URL buat API calls

Matiin service:
```bash
docker compose down
```
**Troubleshooting**
- kalau Docker Desktop belum diaktifkan muncul error di Windows, cek apakah virtualization udah di enable atau belum. cara ceknya di task manager -> performances -> CPU ( lihat "Virtualization: Enabled/Disabled").
- kalau masih Disabled, harus diaktifkan manual lewat BIOS (biasanya di tab Security atau Advanced

## Endpoints

| Method | Path | Fungsi |
|---|---|---|
| `GET` | `/health` | Cek backend hidup |
| `POST` | `/scans` | Kirim hasil scan baru |
| `GET` | `/scans` | List scan, bisa difilter + pagination |
| `GET` | `/scans/latest` | Scan terbaru (buat live feed, di-polling frontend) |
| `GET` | `/stats/summary` | Statistik ringkasan (total, pass rate, dll) |

### `POST /scans`

```json
{
  "object_type": "PCB",
  "verdict": "worthy",
  "confidence": 0.97,
  "image_url": "https://storage.example.com/scans/abc123.jpg"
}
```
- `object_type` (string, wajib), `verdict` (`"worthy"`/`"not_worthy"`, wajib), 
  `confidence` (float 0.0-1.0, wajib), `image_url` (opsional)

### `GET /scans` — query params

`verdict`, `date_from`, `date_to` (YYYY-MM-DD), `page` (default 1), `page_size` (default 20, max 200)

### `GET /scans/latest` — query params

`limit` (default 10)

### `GET /stats/summary` — query params

`date_from`, `date_to`, `group_by_day` (bool)

Detail lengkap request/response tiap endpoint ada di http://localhost:8000/docs 

## Struktur Folder
backend-service/
├── app/
│ ├── main.py # setup FastAPI, router, CORS
│ ├── database.py # koneksi PostgreSQL
│ ├── models.py # struktur tabel 'scans'
│ ├── schemas.py # validasi request/response
│ └── routers/
│ ├── scans.py # endpoint /scans
│ └── stats.py # endpoint /stats
├── .env.example # contoh format env variable
├── docker-compose.yml # FastAPI + PostgreSQL
├── Dockerfile
└── requirements.txt


