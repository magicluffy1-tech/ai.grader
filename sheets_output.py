import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from typing import List, Dict
import json

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]


def connect_sheets(credentials_info: dict) -> gspread.Client:
    """서비스 계정 JSON으로 Google Sheets 연결"""
    creds = Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
    return gspread.authorize(creds)


def export_to_sheets(
    client: gspread.Client,
    exam_name: str,
    rubric: List[Dict],
    all_results: List[Dict],
    sheet_url: str = None
) -> str:
    """채점 결과를 Google Sheets에 기록 후 URL 반환"""

    # 스프레드시트 열기 or 생성
    if sheet_url and sheet_url.strip():
        spreadsheet = client.open_by_url(sheet_url.strip())
    else:
        spreadsheet = client.create(f"{exam_name}_채점결과_{datetime.now().strftime('%Y%m%d')}")
        spreadsheet.share(None, perm_type='anyone', role='writer')

    # 워크시트 이름: 수행평가명_날짜시간
    ws_title = f"{exam_name}_{datetime.now().strftime('%m%d_%H%M')}"
    try:
        ws = spreadsheet.add_worksheet(title=ws_title, rows=200, cols=60)
    except Exception:
        ws = spreadsheet.sheet1
        ws.clear()

    # ── 헤더 행 구성 ──────────────────────────────────────────
    header_row1 = ['학생명', 'OCR 텍스트 요약', '총점', '전체 평가 의견']
    header_row2 = ['', '', '', '']

    for item in rubric:
        header_row1.extend([item['name'], ''])
        header_row2.extend([f"점수 (/{item['max_score']})", '채점 근거'])

    ws.append_row(header_row1, value_input_option='USER_ENTERED')
    ws.append_row(header_row2, value_input_option='USER_ENTERED')

    # ── 데이터 행 ──────────────────────────────────────────────
    for entry in all_results:
        student_name = entry['student_name']
        ocr_text = entry.get('ocr_text', '')
        grading = entry.get('grading', {})

        ocr_summary = ocr_text[:80] + '…' if len(ocr_text) > 80 else ocr_text
        total_score = grading.get('total_score', 0)
        comment = grading.get('overall_comment', '')

        row = [student_name, ocr_summary, total_score, comment]

        # 채점 요소별 점수 + 근거
        results_map = {r['element']: r for r in grading.get('results', [])}
        for item in rubric:
            res = results_map.get(item['name'], {})
            row.append(res.get('score', '-'))
            row.append(res.get('evidence', ''))

        ws.append_row(row, value_input_option='USER_ENTERED')

    # ── 헤더 굵게 (배치 업데이트) ──────────────────────────────
    try:
        ws.format('A1:ZZ2', {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.26, "green": 0.49, "blue": 0.82}
        })
    except Exception:
        pass  # 포맷 실패 시 무시

    return spreadsheet.url
