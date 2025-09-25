import io
import pdfplumber

def extract_text_from_pdf_fileobj(fileobj) -> str:
    text = ""
    fileobj.seek(0)
    with pdfplumber.open(fileobj) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return (text or "").strip()

def extract_text_from_bytes_or_txt(filename: str, raw: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".txt"):
        return raw.decode("utf-8", errors="ignore").strip()
    raise ValueError("TXT dışı içerik için bu fonksiyonu kullanmayın.")
