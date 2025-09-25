CV Evaluation Engine – Adım 1 Starter

Kurulum:
1) python -m venv .venv
2) source .venv/bin/activate
3) pip install -r requirements.txt
4) uvicorn app.main:app --reload --port 8000

Swagger: http://127.0.0.1:8000/docs

Akış:
- POST /upload : PDF/TXT yükle → metin önizle
- POST /score  : {job_title, weights, cv{...}} → puan
- UI (/ui)     : Dosya yükle, önizle, slider’larla ağırlıkları ayarla, “Skorla” → sonuç

Örnek Kullanım:
1) http://127.0.0.1:8000/ui adresine git
2) CV PDF/TXT yükle → özet metin görünür
3) “Skorla” → TOTAL + Breakdown (skills, experience, education, role) görünür

---

Teknolojiler:
- Python 3.11
- FastAPI (REST API ve arayüz servisleri)
- Uvicorn (ASGI server)
- pdfplumber / PyPDF2 (PDF metin çıkarımı için)
- ORJSON (JSON yanıt performansı için, varsa)
- HTML + Vanilla JavaScript (basit arayüz, slider’lar, butonlar)
- Swagger UI (otomatik endpoint dokümantasyonu)

Hesaplama Mantığı:
- Her CV için name, email, phone, skills, education, experience alanları çıkarılır.
- Education satırlarından en yüksek seviye belirlenir (high_school, bachelor, master, phd).
- Experience satırlarından yıl tahmini yapılır (tarih aralıkları regex ile).
- Skills, role’a özgü must/nice anahtar kelimelerle eşleştirilir.
- Puanlama: skills / experience / education başına 0–5 arası.
- Toplam 15 üzerinden normalize edilir, ağırlıklar (skills, experience, education) slider’larla belirlenir.
- Weighted total = ∑(dimension_score * weight).

Gereksinimler:
- Python 3.11
- pip install -r requirements.txt
  - fastapi
  - uvicorn
  - pdfplumber
  - PyPDF2
  - orjson (opsiyonel)
  - python-multipart

---
