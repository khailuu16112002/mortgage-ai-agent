import base64
from pathlib import Path


def pdf_to_base64(pdf_path: str) -> str:
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy: {pdf_path}")
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def extract_pdf_text(pdf_path: str, max_chars: int = 8000) -> str:
    """Extract text từ PDF dùng pypdf (OpenAI không nhận PDF trực tiếp)."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        pages_text = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages_text.append(text)
        full_text = "\n".join(pages_text)
        # Truncate nếu quá dài để tránh vượt context
        if len(full_text) > max_chars:
            full_text = full_text[:max_chars] + "\n...[truncated]"
        return full_text
    except Exception as e:
        return f"[Không đọc được PDF: {e}]"


def build_pdf_message(pdf_paths: list, prompt: str) -> list:
    """
    Build OpenAI message content từ danh sách PDF.
    OpenAI không nhận PDF binary trực tiếp — extract text qua pypdf.
    """
    content = []
    for path in pdf_paths:
        name = Path(path).name
        text = extract_pdf_text(path)
        content.append({
            "type": "text",
            "text": f"--- FILE: {name} ---\n{text}\n--- END: {name} ---"
        })
    content.append({"type": "text", "text": prompt})
    return content
