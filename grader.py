import google.generativeai as genai
import json
import time
import re
from typing import List, Dict

RETRY_CODES = (429, 503)

def _call_with_retry(fn, max_retries: int = 3):
    """429/503 에러 시 자동 재시도 (exponential backoff)"""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            # 재시도 대기시간 파싱
            wait_match = re.search(r'retry.*?(\d+)\s*s', msg, re.IGNORECASE)
            wait_sec = int(wait_match.group(1)) if wait_match else (2 ** (attempt + 1) * 5)
            is_rate_limit = '429' in msg or '503' in msg or 'quota' in msg.lower()
            if is_rate_limit and attempt < max_retries - 1:
                time.sleep(min(wait_sec + 2, 60))
                continue
            raise

def setup_gemini(api_key: str, model_name: str = 'gemini-2.5-flash') -> genai.GenerativeModel:
    """Gemini API 설정 및 모델 반환"""
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_name)


def build_rubric_text(rubric: List[Dict]) -> str:
    """루브릭 리스트를 프롬프트용 텍스트로 변환"""
    lines = []
    for i, item in enumerate(rubric, 1):
        lines.append(f"{i}. [{item['name']}] (만점: {item['max_score']}점)")
        lines.append(f"   채점 기준:\n{item['criteria']}")
        lines.append("")
    return '\n'.join(lines)


def grade_student_answer(
    model: genai.GenerativeModel,
    exam_questions: str,
    rubric: List[Dict],
    student_answer: str,
    student_name: str
) -> Dict:
    """Gemini를 이용한 학생 답안 채점 → 채점 결과 dict 반환"""

    rubric_text = build_rubric_text(rubric)
    total_max = sum(item['max_score'] for item in rubric)
    element_list = json.dumps(
        [{"element": r['name'], "max_score": r['max_score']} for r in rubric],
        ensure_ascii=False
    )

    prompt = f"""당신은 엄격하고 공정한 수행평가 채점 전문가입니다.
아래 수행평가 문항과 채점 기준에 따라 학생 답안을 정밀하게 채점하세요.

===== 수행평가 문항 =====
{exam_questions}

===== 채점 기준 (총 {total_max}점) =====
{rubric_text}

===== 학생 답안 (학생명: {student_name}) =====
{student_answer}

===== 채점 지침 =====
- OCR로 인식된 텍스트이므로 오타/띄어쓰기 오류를 감안해 채점하세요.
- 채점 근거는 학생 답안의 구체적 내용을 직접 인용하여 2~3문장으로 설명하세요.
- 아래 JSON 형식으로만 응답하고, 다른 텍스트는 절대 포함하지 마세요.
- element 이름은 반드시 아래 목록과 동일하게 사용하세요: {element_list}

{{
  "results": [
    {{"element": "채점요소명", "score": 획득점수, "max_score": 만점, "evidence": "채점 근거"}}
  ],
  "total_score": 총점,
  "overall_comment": "전체 평가 의견 (장단점 포함, 3~4문장)"
}}"""

    response = _call_with_retry(lambda: model.generate_content(prompt))
    raw = response.text.strip()

    # JSON 블록 추출
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if not json_match:
        raise ValueError(f"AI 응답에서 JSON을 찾을 수 없습니다:\n{raw}")

    result = json.loads(json_match.group())

    # 채점 요소 누락 시 보완
    existing = {r['element'] for r in result.get('results', [])}
    for item in rubric:
        if item['name'] not in existing:
            result['results'].append({
                "element": item['name'],
                "score": 0,
                "max_score": item['max_score'],
                "evidence": "채점 요소에 해당하는 내용이 답안에서 확인되지 않았습니다."
            })

    # total_score 재계산 (AI가 잘못 계산할 경우 대비)
    result['total_score'] = sum(r['score'] for r in result['results'])

    return result
