"""
PDF reader utility.

Chiến lược đọc:
1. Thử extract text bằng pypdf
2. Nếu text quá ngắn (< MIN_TEXT_CHARS) → PDF là ảnh scan → rasterize sang PNG bằng pdf2image
3. Trả về dict {"mode": "text"|"images", "text": str, "images": [base64_png, ...]}

Dùng mode "images" với GPT-4o Vision khi text không đọc được.
"""
import base64
import re
from pathlib import Path


MIN_TEXT_CHARS = 100   # ít hơn ngưỡng này → coi là ảnh scan


def extract_pdf_text(pdf_path: str, max_chars: int = 10000) -> str:
    """Extract text từ PDF bằng pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        pages_text = [page.extract_text() or "" for page in reader.pages]
        full_text = "\n".join(pages_text)
        if len(full_text) > max_chars:
            full_text = full_text[:max_chars] + "\n...[truncated]"
        return full_text
    except Exception as e:
        return f"[Không đọc được PDF: {e}]"


def pdf_to_images_base64(pdf_path: str, dpi: int = 200, max_pages: int = 4) -> list[str]:
    """
    Rasterize PDF sang PNG, trả về list base64 strings (mỗi trang 1 ảnh).
    Dùng pdf2image (wrapper của poppler).
    """
    try:
        from pdf2image import convert_from_path
        pages = convert_from_path(pdf_path, dpi=dpi, first_page=1, last_page=max_pages)
        result = []
        for page in pages:
            import io
            buf = io.BytesIO()
            page.save(buf, format="PNG")
            b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
            result.append(b64)
        return result
    except ImportError:
        raise RuntimeError(
            "pdf2image chưa cài. Chạy: pip install pdf2image  "
            "(cần poppler: Windows → https://github.com/oschwartz10612/poppler-windows/releases)"
        )
    except Exception as e:
        raise RuntimeError(f"Không rasterize được PDF: {e}")


def read_pdf_smart(pdf_path: str) -> dict:
    """
    Trả về dict:
      {"mode": "text",   "text": "...", "images": []}
      {"mode": "images", "text": "",   "images": ["base64png", ...]}
    """
    text = extract_pdf_text(pdf_path)
    # Bỏ whitespace để đánh giá độ dài thực
    text_stripped = text.replace(" ", "").replace("\n", "").replace("\t", "")
    if len(text_stripped) >= MIN_TEXT_CHARS and not text.startswith("[Không đọc được"):
        return {"mode": "text", "text": text, "images": []}

    # Text quá ngắn → rasterize
    try:
        images = pdf_to_images_base64(pdf_path)
        return {"mode": "images", "text": "", "images": images}
    except Exception as e:
        # Fallback: trả text dù ngắn, kèm cảnh báo
        return {
            "mode": "text",
            "text": text or f"[Không đọc được text; rasterize thất bại: {e}]",
            "images": []
        }


def clean_json_response(raw: str) -> str:
    """
    Làm sạch response từ LLM trước khi json.loads:
    - Bóc markdown code fences
    - Nếu có nhiều JSON objects nối tiếp, chỉ lấy object đầu tiên
    """
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    raw = raw.strip()

    if raw.startswith("{"):
        depth = 0
        for i, ch in enumerate(raw):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return raw[: i + 1]
    elif raw.startswith("["):
        depth = 0
        for i, ch in enumerate(raw):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return raw[: i + 1]
    return raw


def build_pdf_message(pdf_paths: list, prompt: str) -> list:
    """
    Build OpenAI message content từ danh sách PDF.
    - Nếu PDF có text → gửi text block
    - Nếu PDF là ảnh → gửi image_url block (base64 PNG) để dùng Vision
    """
    content = []
    for path in pdf_paths:
        name = Path(path).name
        info = read_pdf_smart(path)

        if info["mode"] == "images":
            content.append({
                "type": "text",
                "text": f"--- FILE: {name} (image scan — reading via vision) ---"
            })
            for i, b64 in enumerate(info["images"]):
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{b64}",
                        "detail": "high"
                    }
                })
        else:
            content.append({
                "type": "text",
                "text": f"--- FILE: {name} ---\n{info['text']}\n--- END: {name} ---"
            })

    content.append({"type": "text", "text": prompt})
    return content
