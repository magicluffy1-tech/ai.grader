import io
import time
import re
from PIL import Image
import google.generativeai as genai


# ─── 재시도 래퍼 ──────────────────────────────────────────────────────────────────
def _call_with_retry(fn, max_retries: int = 3):
    """429/503 에러 시 자동 재시도 (exponential backoff)"""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            wait_match = re.search(r'retry.*?(\d+)\s*s', msg, re.IGNORECASE)
            wait_sec = int(wait_match.group(1)) if wait_match else (2 ** (attempt + 1) * 5)
            is_rate_limit = '429' in msg or '503' in msg or 'quota' in msg.lower()
            if is_rate_limit and attempt < max_retries - 1:
                time.sleep(min(wait_sec + 2, 65))
                continue
            raise


# ─── 파일 → PIL Image 변환 ────────────────────────────────────────────────────────
def _image_bytes_to_pil(image_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(image_bytes)).convert('RGB')


def _pdf_to_images(pdf_bytes: bytes) -> list:
    """PDF → 페이지별 PIL Image 리스트 (200dpi, 선명도 최적화)"""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    for page in doc:
        # 2.5배 배율로 렌더링 → 손글씨 인식 정확도 향상
        pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert('RGB')
        images.append(img)
    doc.close()
    return images


# ═══════════════════════════════════════════════════════
# Gemini Vision OCR (유일한 엔진)
# ═══════════════════════════════════════════════════════

def load_ocr_reader(api_key: str, model_name: str = 'gemini-2.5-flash') -> genai.GenerativeModel:
    """Gemini Vision 모델 초기화"""
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_name)


def _ocr_image_with_gemini(model, image: Image.Image, page_label: str = "") -> str:
    """Gemini Vision으로 손글씨 이미지 OCR — 한국어 특화 프롬프트"""
    prompt = """이 이미지는 학생이 손으로 작성한 수행평가 답안지입니다.
이미지에서 학생이 쓴 텍스트를 최대한 정확하게 읽어주세요.

지침:
- 손글씨이므로 불분명한 글자는 문맥에 맞게 최선으로 해석하세요.
- 서론/본론/결론 등 구조가 있다면 그 구조를 유지하세요.
- 이미지 속 학생 텍스트만 출력하고, 설명이나 주석은 절대 추가하지 마세요.
- 인식이 불확실한 단어는 [?] 로 표시하세요.
- 수정된 흔적이 있으면 최종 답안을 기준으로 읽으세요.
- 텍스트만 출력하세요."""

    response = _call_with_retry(lambda: model.generate_content([prompt, image]))
    text = response.text.strip()
    if page_label:
        return f"[{page_label}]\n{text}"
    return text


def process_uploaded_file(model, file_bytes: bytes, filename: str) -> str:
    """Gemini Vision으로 파일 OCR (이미지 / PDF 지원)"""
    ext = filename.lower().rsplit('.', 1)[-1]
    if ext == 'pdf':
        images = _pdf_to_images(file_bytes)
        results = []
        for i, img in enumerate(images):
            text = _ocr_image_with_gemini(model, img, page_label=f"{i+1}페이지")
            results.append(text)
        return '\n\n'.join(results)
    elif ext in ['jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'webp']:
        image = _image_bytes_to_pil(file_bytes)
        return _ocr_image_with_gemini(model, image)
    else:
        raise ValueError(f"지원하지 않는 파일 형식입니다: .{ext}")
