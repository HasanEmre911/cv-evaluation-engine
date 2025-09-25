from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi import Body
from datetime import datetime
from typing import List
from fastapi.responses import JSONResponse, HTMLResponse, ORJSONResponse, RedirectResponse, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles
from app.extract import extract_text_from_pdf_fileobj, extract_text_from_bytes_or_txt
from app.models import CVParsed
from app.scorer import score_cv
import io
import re
from fastapi.encoders import jsonable_encoder

try:
    import orjson
    from fastapi.responses import ORJSONResponse as DefaultResponseClass
except Exception:  # orjson not available
    from fastapi.responses import JSONResponse as DefaultResponseClass

app = FastAPI(
    title="CV Evaluation Engine",
    description="Bir özgeçmiş (CV) yükleyin, otomatik olarak analiz ve puanlama alın! PDF ve TXT dosyalarını destekler.",
    version="0.1.0",
    contact={
        "name": "UK1 CV Eval Ekibi",
        "email": "info@cv-eval.com",
        "url": "https://cv-eval.com",
    },
    openapi_tags=[
        {"name": "health", "description": "Servis sağlık kontrolü"},
        {"name": "upload", "description": "CV dosyası yükle ve önizleme al"},
        {"name": "score", "description": "Yapılandırılmış CV üzerinden otomatik puanlama"},
    ],
    docs_url=None,
    redoc_url=None,
    default_response_class=DefaultResponseClass,
)

def simple_parse_cv(text: str) -> dict:
    lines = [line.strip() for line in text.splitlines()]
    norm_lines = []
    for ln in lines:
        if ln is None:
            continue
        s = ln.strip()
        norm_lines.append(s)

    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.[A-Za-z]{2,}", text, re.I)
    email = email_match.group(0) if email_match else ""

    phone_match = re.search(r"(\+?\d[\d\s\-()]{7,}\d)", text)
    phone = phone_match.group(0) if phone_match else ""

    # name heuristic = first non-empty line that is not email/phone and not a header word
    header_words = {"summary","objective","skills","skill","education","experience","experiences","work experience","projects","certificates","languages"}
    name = ""
    for ln in norm_lines:
        if not ln:
            continue
        low = ln.lower().strip(':')
        if (email and email in ln) or (phone and phone in ln):
            continue
        if low in header_words:
            continue
        if re.search(r"[A-Za-zğüşöçıİĞÜŞÖÇ]", ln):
            name = ln
            break

    # section scan
    known_headers = [
        r"skills?\b",
        r"education\b",
        r"experiences?\b|work\s+experience\b",
        r"projects\b",
        r"certificates?\b",
        r"languages\b",
        r"summary\b|objective\b",
    ]
    header_re = re.compile(r"^(" + r"|".join(known_headers) + r")[\s:]*$", re.I)

    sections: dict[str, list[str]] = {}
    current = None
    for ln in norm_lines:
        low = (ln or "").lower()
        if header_re.match(low):
            # normalize header key
            if re.search(r"skills?", low): key = "skills"
            elif re.search(r"education", low): key = "education"
            elif re.search(r"experiences?|work\s+experience", low): key = "experience"
            elif re.search(r"projects", low): key = "projects"
            elif re.search(r"certificates?", low): key = "certificates"
            elif re.search(r"languages", low): key = "languages"
            else: key = low.strip(':')
            current = key
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(ln)

    skills_sep = re.compile(r"[\n,;•·\u2022\u25CF]|\s\u00B7\s|")
    skills: list[str] = []
    if "skills" in sections:
        buf = "\n".join(sections["skills"]) if sections["skills"] else ""
        raw_sk = re.split(r"[\n,;•·\u2022\u25CF]", buf)
        skills = [s.strip() for s in raw_sk if s and len(s.strip()) > 1]

    def compact_block(lines_list: list[str]) -> list[str]:
        out: list[str] = []
        block: list[str] = []
        for ln in lines_list:
            if not ln:
                if block:
                    out.append(" ".join(block).strip())
                    block = []
                continue
            block.append(ln)
        if block:
            out.append(" ".join(block).strip())
        return [x for x in out if x]

    education = compact_block(sections.get("education", []))
    experience = compact_block(sections.get("experience", []))

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "skills": skills,
        "education": education,
        "experience": experience,
    }

# serve static assets (custom swagger + ui assets)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Docs",
        swagger_css_url="/static/custom-swagger.css?v=2",
    )


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/ui", status_code=307)

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)

@app.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon():
    return Response(status_code=204)

@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def apple_touch_icon2():
    return Response(status_code=204)

@app.get("/health", tags=["health"], summary="Servis sağlık kontrolü")
def health():
    return {"status": "ok"}

@app.post(
    "/upload",
    tags=["upload"],
    summary="CV dosyası yükle ve önizleme al",
    responses={
        200: {
            "description": "Dosya başarıyla işlendi",
            "content": {
                "application/json": {
                    "example": {
                        "filename": "ozgecmis.pdf",
                        "chars": 12345,
                        "preview": "Ali Veli\nYazılım Mühendisi\n...",
                        "parsed": {
                            "name": "Ali Veli",
                            "email": "ali@example.com",
                            "phone": "+905551112233",
                            "skills": ["Python", "Machine Learning"],
                            "education": ["BSc Computer Science"],
                            "experience": ["Software Developer at XYZ"]
                        }
                    }
                }
            },
        },
        400: {"description": "Hatalı dosya veya desteklenmeyen format"},
    },
)
async def upload(file: UploadFile = File(...)):
    try:
        fname = (file.filename or "").lower()
        if not (fname.endswith(".pdf") or fname.endswith(".txt")):
            raise HTTPException(
                status_code=400,
                detail="Sadece .pdf veya .txt dosyaları kabul edilir.",
            )

        raw = await file.read()
        content = ""

        if fname.endswith(".pdf"):
            try:
                content = extract_text_from_pdf_fileobj(io.BytesIO(raw)) or ""
            except Exception as e1:
                try:
                    from PyPDF2 import PdfReader  # type: ignore
                    reader = PdfReader(io.BytesIO(raw))
                    buf = []
                    for page in reader.pages:
                        try:
                            buf.append(page.extract_text() or "")
                        except Exception:
                            continue
                    content = "\n".join(buf)
                    if not content.strip():
                        raise RuntimeError("PyPDF2 fallback produced empty text")
                except Exception as e2:
                    raise HTTPException(status_code=400, detail=f"upload/parse error: {e1} | {e2}")
        else:
            try:
                content = extract_text_from_bytes_or_txt(file.filename, raw) or ""
            except Exception as e3:
                try:
                    content = raw.decode("utf-8", errors="ignore")
                except Exception:
                    raise HTTPException(status_code=400, detail=f"upload/parse error: {e3}")

        preview = (content or "").replace("\r\n", "\n").replace("\r", "\n")
        preview = "\n".join(line.strip() for line in preview.splitlines())
        preview = preview[:1200]

        parsed = simple_parse_cv(content)

        return {"filename": file.filename, "chars": len(content), "preview": preview, "parsed": parsed}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"upload/parse error: {e}")

def edu_level_from_text(education_lines: List[str]) -> str:
    # Join and normalize
    text = " \n".join(education_lines).lower()
    # Common keywords (add Turkish variants)
    has_phd = any(k in text for k in [
        "phd", "ph.d", "doctorate", "doctoral", "dphil", "doktor", "doktora"
    ])
    has_master = any(k in text for k in [
        "master", "msc", "m.sc", "m.s", "ms ", "yüksek lisans", "yuksek lisans", "tezli", "tezsiz"
    ])
    has_bachelor_kw = any(k in text for k in [
        "bachelor", "bsc", "b.sc", "b.s ", "bs ", "licence", "license", "lisans", "undergraduate"
    ])
    has_university = any(k in text for k in [
        "university", "üniversite", "universitesi", "faculty", "fakülte", "fakulte"
    ])
    has_high_school = any(k in text for k in [
        "high school", "lise"
    ])

    # Decision: pick the highest available level
    if has_phd:
        return "phd"
    if has_master:
        return "master"
    if has_bachelor_kw or has_university:
        # If any hint of university exists, treat as bachelor minimum
        return "bachelor"
    if has_high_school:
        return "high_school"
    return "unknown"

_months = {m.lower(): i for i,m in enumerate([
    "", "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"
])}

_date_pat = re.compile(r"(?P<mon>[A-Za-z]{3})\s*(?P<y>20\d{2}|19\d{2})", re.I)
_year_pat = re.compile(r"(20\d{2}|19\d{2})")

def exp_years_from_lines(exper_lines: List[str]) -> float:
    """Very rough heuristic: parse date ranges like 'Jul 2024 - Sep 2024' or '2022-2024'."""
    text = " \n".join(exper_lines)
    total_months = 0
    # pattern A: 'Jul 2024 - Sep 2024'
    range_pat = re.compile(r"([A-Za-z]{3})\s*(20\d{2}|19\d{2})\s*[-–]\s*([A-Za-z]{3})\s*(20\d{2}|19\d{2})")
    for m1,y1,m2,y2 in range_pat.findall(text):
        m1i = _months.get(m1.lower(), 1)
        m2i = _months.get(m2.lower(), 1)
        months = (int(y2)-int(y1))*12 + (m2i-m1i)
        if months > 0:
            total_months += months
    # pattern B: '2022 - 2024'
    yr_range = re.compile(r"(20\d{2}|19\d{2})\s*[-–]\s*(20\d{2}|19\d{2})")
    for y1,y2 in yr_range.findall(text):
        months = (int(y2)-int(y1))*12
        if months>0:
            total_months += months
    # Fallback: if nothing parsed but there are experience bullets, assume 0.2y per bullet
    if total_months == 0 and exper_lines:
        total_months = max(0, len([l for l in exper_lines if l])) * 2  # ~2 months each
    return round(total_months/12.0, 1)


@app.post(
    "/score",
    tags=["score"],
    summary="Yapılandırılmış CV üzerinden otomatik puanlama",
    response_model=dict,
)
async def score(payload: dict = Body(...)):
    try:
        # --- normalize input ---
        if all(k in payload for k in ("skills", "experience_years", "education_level")):
            cv_data = payload
            job_title = payload.get("job_title") or ""
            weights = payload.get("weights") or {"skills":0.5,"experience":0.3,"education":0.2}
        else:
            job_title = payload.get("job_title") or ""
            weights = payload.get("weights") or {"skills":0.5,"experience":0.3,"education":0.2}
            cv = payload.get("cv", {}) or {}
            cv_data = {
                "skills": cv.get("skills", []) or [],
                "experience_years": exp_years_from_lines(cv.get("experience", []) or []),
                "education_level": edu_level_from_text(cv.get("education", []) or []),
            }

        ROLE_SKILLS = {
            "data scientist": {
                "must": {"python","pandas","numpy","sql"},
                "nice": {"scikit-learn","ml","machine learning","statistics","probability","tensorflow","pytorch","power bi","tableau"},
            },
            "backend engineer": {
                "must": {"python","java","go","node","sql","rest","api"},
                "nice": {"django","fastapi","spring","microservices","docker","kubernetes","redis","rabbitmq"},
            },
            "business analyst": {
                "must": {"excel","sql","report","analyst","analysis"},
                "nice": {"power bi","tableau","requirements","documentation","stakeholder","process"},
            },
        }

        user_skills = [s.strip().lower() for s in (cv_data.get("skills") or []) if isinstance(s, str)]
        all_skill_text = " | ".join(user_skills)

        profile = ROLE_SKILLS.get((job_title or "").lower(), ROLE_SKILLS["data scientist"])  # default

        must_hits = sum(1 for k in profile["must"] if k in all_skill_text)
        nice_hits = sum(1 for k in profile["nice"] if k in all_skill_text)
        must_ratio = must_hits / max(1, len(profile["must"]))
        sp = round(min(5, 3*must_ratio + min(2, 0.4*nice_hits)))
        skills_reason = {
            "must_required": sorted(list(profile["must"])),
            "must_hits": must_hits,
            "nice_hits": nice_hits,
        }

        years = float(cv_data.get("experience_years") or 0)
        thresholds = [0, 0.5, 1, 2, 3, 4]
        xp = next((i for i,t in enumerate(thresholds) if years < t), 5)
        exp_reason = {"years_inferred": years, "thresholds": thresholds}

        level = (cv_data.get("education_level") or "unknown").lower()
        edu_map = {"high_school":1, "bachelor":3, "master":4, "phd":5, "unknown":2}
        ep = edu_map.get(level, 2)
        edu_reason = {"level": level, "map": edu_map}

        total_15 = int(sp + xp + ep)
        weighted_100 = round(100*(sp/5*weights["skills"] + xp/5*weights["experience"] + ep/5*weights["education"]))

        return {
            "job_title": job_title or "(unspecified)",
            "scale": {"per_dimension": 5, "total": 15, "weighted_total": 100, "weights": weights},
            "points": {
                "skills_points": sp,
                "experience_points": xp,
                "education_points": ep,
                "total": total_15,
                "weighted": weighted_100,
            },
            "reasons": {
                "skills": skills_reason,
                "experience": exp_reason,
                "education": edu_reason,
            },
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"score error: {e}")

@app.get("/ui", response_class=HTMLResponse, tags=["upload"], summary="Custom UI for CV upload")
async def ui():
    html_content = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CV Upload - CV Evaluation Engine</title>
  <style>
    :root{ --bg1:#6a11cb; --bg2:#2575fc; --ink:#0f172a; --paper:#ffffff; --accent:#00c2ff; --accent2:#ff6ec7; }
    html,body{height:100%}
    body{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial; background:linear-gradient(135deg,var(--bg1),var(--bg2)); color:var(--ink);} 
    .container{ max-width:820px; margin:48px auto; padding:0 20px; }
    h1{ color:#fff; text-align:center; }
    .card{ background:rgba(255,255,255,.96); border-radius:16px; padding:28px; box-shadow:0 12px 30px rgba(2,6,23,.18);} 
    .row{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
    input[type=file]{ display:block; padding:10px; background:#f8fafc; border:1px solid rgba(15,23,42,.15); border-radius:10px; }
    button{ appearance:none; border:none; background:linear-gradient(135deg,var(--accent),var(--accent2)); color:#fff; padding:12px 18px; border-radius:999px; font-weight:600; box-shadow:0 8px 20px rgba(0,0,0,.2); cursor:pointer; }
    button:hover{ transform:translateY(-1px); }
    .result{ margin-top:20px; background:#0b1220; color:#e5e7eb; border-radius:12px; padding:16px; overflow:auto; max-height:50vh; }
    #scorebox{ margin-top:20px; background:#0b1220; color:#e5e7eb; border-radius:12px; padding:16px; overflow:auto; max-height:50vh; }
    pre{ white-space:pre-wrap; word-break:break-word; margin:0; }
    .button-group{ display:flex; gap:12px; align-items:center; }
    #file-name{ margin-left:6px; }
    #change-file-btn{ appearance:none; border:none; background:#e2e8f0; color:#0f172a; padding:10px 14px; border-radius:999px; font-weight:600; cursor:pointer; }
    #change-file-btn:hover{ filter:brightness(0.98); }
  </style>
</head>
<body>
  <div class="container">
    <h1>CV Evaluation Engine</h1>
    <div class="card">
      <form id="upload-form" class="row" action="/upload" method="post" enctype="multipart/form-data" target="upload_result">
        <input id="file" name="file" type="file" accept=".pdf,.txt" required />
        <span id="file-name" style="color:#334155; font-size:14px;"></span>
        <button id="change-file-btn" type="button" style="display:none;">Dosyayı Değiştir</button>
        <button id="upload-btn" type="submit">Yükle ve Önizle</button>
      </form>
      <div class="row" style="margin-top:12px; align-items:center;">
        <label for="job" style="color:#0f172a; font-weight:600;">İş Pozisyonu:</label>
        <select id="job" name="job" style="flex-grow:1; padding:8px; border-radius:8px; border:1px solid #ccc;">
          <option value="Data Scientist">Data Scientist</option>
          <option value="Backend Engineer">Backend Engineer</option>
          <option value="Business Analyst">Business Analyst</option>
        </select>
        <button id="score-btn" type="button">Skorla</button>
      </div>
      <div id="out" class="result" style="display:none;">
        <pre id="json"></pre>
      </div>
      <div id="scorebox" style="display:block;">
        <pre id="scorejson">Skor burada görünecek. Önce "Yükle ve Önizle" yapın, sonra "Skorla" butonuna basın.</pre>
      </div>
      <!-- No-JS fallback output area -->
      <div style="margin-top:16px;">
        <iframe name="upload_result" id="upload_result" style="width:100%;height:280px;border:1px solid #0b1220;border-radius:12px;background:#0b1220;color:#e5e7eb;"></iframe>
      </div>
    </div>
  </div>
  <script>
    // --- Grab elements (script is at end of body, DOM is ready) ---
    const form = document.getElementById('upload-form');
    const fileInput = document.getElementById('file');
    const out = document.getElementById('out');
    const pre = document.getElementById('json');
    const scoreBtn = document.getElementById('score-btn');
    const jobSelect = document.getElementById('job');
    const scoreBox = document.getElementById('scorebox');
    const scorePre = document.getElementById('scorejson');
    const fileNameLbl = document.getElementById('file-name');
    const changeFileBtn = document.getElementById('change-file-btn');
    const uploadBtn = document.getElementById('upload-btn');

    scoreBox.style.display = 'block';

    document.getElementById('upload_result').style.display = 'none';

    let lastUploadResult = null;

    function showErrorInline(msg){
      out.style.display = 'block';
      pre.textContent = String(msg || 'Bilinmeyen hata');
    }

    function lockFileInput(file){
      if(!file) return;
      fileInput.disabled = true;
      changeFileBtn.style.display = 'inline-block';
      fileNameLbl.textContent = 'Seçilen: ' + file.name;
    }
    function unlockFileInput(){
      fileInput.disabled = false;
      changeFileBtn.style.display = 'none';
      fileInput.value = '';
      fileNameLbl.textContent = '';
    }
    changeFileBtn.addEventListener('click', function(){
      unlockFileInput();
      out.style.display = 'none';
      scoreBox.style.display = 'none';
    });

    async function performUpload(){
      try{
        const f = fileInput.files[0];
        out.style.display = 'block';
        if(!f){ pre.textContent='Lütfen dosya seçin.'; return; }
        pre.textContent = 'Yükleniyor...';
        const fd = new FormData();
        fd.append('file', f);
        const resp = await fetch('/upload', { method: 'POST', body: fd });
        const text = await resp.text();
        let j; try { j = JSON.parse(text); } catch(err) { j = {detail:text}; }
        if(!resp.ok){ pre.textContent = j.detail || text; lastUploadResult=null; return; }
        lastUploadResult = j; lockFileInput(f);
        if(j && j.parsed){
          const p = j.parsed;
          const sample = ((j && j.preview) ? String(j.preview) : '').slice(0,200).split('\\n').join(' ');
          pre.textContent = (
            'Dosya: ' + j.filename + ' | Karakter: ' + j.chars + '\\n' +
            'İsim: ' + (p.name||'-') + ' | Email: ' + (p.email||'-') + ' | Tel: ' + (p.phone||'-') + '\\n' +
            'Skills: ' + ((p.skills||[]).slice(0,8).join(', ')) + ((p.skills||[]).length>8?' ...':'') + '\\n' +
            'Experience entries: ' + ((p.experience||[]).length) + ' | Education entries: ' + ((p.education||[]).length) + '\\n' +
            'Önizleme: ' + sample + (((j.preview||'').length>200)?' ...':'')
          );
        } else {
          pre.textContent = JSON.stringify(j,null,2);
        }
      }catch(e){ showErrorInline(e && e.message ? e.message : e); }
    }

    async function performScore(){
      try{
        out.style.display = 'block';
        if(!lastUploadResult || !lastUploadResult.parsed){
          scorePre.textContent = 'Lütfen önce bir CV yükleyin ve önizleyin.';
          scoreBox.style.display = 'block';
          return;
        }
        const payload = {
          job_title: jobSelect.value,
          weights: {skills:0.5, experience:0.3, education:0.2},
          cv: lastUploadResult.parsed
        };
        scorePre.textContent = 'Skorlama yapılıyor...';
        scoreBox.style.display = 'block';
        const resp = await fetch('/score', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
        const text = await resp.text();
        let data; try{ data = JSON.parse(text); }catch(err){ data = {detail:text}; }
        if(!resp.ok){ scorePre.textContent = (data.detail||text); return; }
        var p = data.points||{}, sc=data.scale||{}, reasons=data.reasons||{};
        var skillsHits = (reasons.skills && reasons.skills.must_hits) ? reasons.skills.must_hits : 0;
        var niceHits = (reasons.skills && reasons.skills.nice_hits) ? reasons.skills.nice_hits : 0;
        var yearsInf = (reasons.experience && reasons.experience.years_inferred!=null) ? reasons.experience.years_inferred : '-';
        var eduLevel = (reasons.education && reasons.education.level) ? reasons.education.level : '-';
        scorePre.textContent = (
          'Job: ' + (data.job_title||'') + '\\n' +
          'Total: ' + (p.total||0) + '/' + (sc.total||15) + '  (Weighted: ' + (p.weighted||0) + '/' + (sc.weighted_total||100) + ')\\n' +
          'Skills: ' + (p.skills_points||0) + '/' + (sc.per_dimension||5) + '  | must_hits=' + skillsHits + ' nice_hits=' + niceHits + '\\n' +
          'Experience: ' + (p.experience_points||0) + '/' + (sc.per_dimension||5) + '  | years~' + yearsInf + '\\n' +
          'Education: ' + (p.education_points||0) + '/' + (sc.per_dimension||5) + '  | level=' + eduLevel
        );
      }catch(e){ showErrorInline(e && e.message ? e.message : e); }
    }

    // Ensure form submit uses AJAX and never reloads the page
    form.addEventListener('submit', function(e){
      console.log('submit trigger');
      e.preventDefault();
      performUpload();
    });

    // Primary bindings
    if(scoreBtn) scoreBtn.addEventListener('click', performScore);

    // Show any JS error on the page
    window.addEventListener('error', function(evt){ try{ showErrorInline('JS Hatası: ' + evt.message); }catch(err){} });
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content, status_code=200)