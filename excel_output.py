import io
from datetime import datetime
from typing import List, Dict

from openpyxl import Workbook
from openpyxl.styles import (
    PatternFill, Font, Alignment, Border, Side
)
from openpyxl.utils import get_column_letter


# ── 스타일 상수 ────────────────────────────────────────────────────────────────
_PURPLE   = "5B21B6"
_INDIGO   = "4338CA"
_GREEN    = "065F46"
_AMBER    = "92400E"
_RED      = "991B1B"
_BG_GREEN = "D1FAE5"
_BG_AMBER = "FEF3C7"
_BG_RED   = "FEE2E2"
_BG_GRAY  = "F3F4F6"
_WHITE    = "FFFFFF"

def _hdr_fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)

def _font(bold=False, color="000000", size=10) -> Font:
    return Font(bold=bold, color=color, size=size, name="맑은 고딕")

def _border() -> Border:
    s = Side(style="thin", color="D1D5DB")
    return Border(left=s, right=s, top=s, bottom=s)

def _center() -> Alignment:
    return Alignment(horizontal="center", vertical="center", wrap_text=True)

def _left() -> Alignment:
    return Alignment(horizontal="left", vertical="center", wrap_text=True)


def _apply_header(ws, row: int, col: int, value, bg: str, bold=True, fontcolor=_WHITE):
    cell = ws.cell(row=row, column=col, value=value)
    cell.fill = _hdr_fill(bg)
    cell.font = _font(bold=bold, color=fontcolor, size=10)
    cell.alignment = _center()
    cell.border = _border()


def _apply_cell(ws, row: int, col: int, value, bg: str = _WHITE, bold=False, align="left"):
    cell = ws.cell(row=row, column=col, value=value)
    cell.fill = _hdr_fill(bg)
    cell.font = _font(bold=bold, size=10)
    cell.alignment = _center() if align == "center" else _left()
    cell.border = _border()


# ── 공개 함수 ──────────────────────────────────────────────────────────────────
def build_excel(
    exam_name: str,
    rubric: List[Dict],
    all_results: List[Dict],
) -> bytes:
    """채점 결과를 엑셀(xlsx) bytes로 반환"""
    wb = Workbook()

    _build_summary_sheet(wb, exam_name, rubric, all_results)
    _build_detail_sheet(wb, exam_name, rubric, all_results)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _build_summary_sheet(wb, exam_name, rubric, all_results):
    """시트1: 채점 요약 (학생별 한 행)"""
    ws = wb.active
    ws.title = "채점 요약"
    ws.freeze_panes = "B3"

    total_max = sum(r.get("max_score", 0) for r in rubric)

    # ── 1행: 제목 ──────────────────────────────────────────────────────────────
    n_cols = 4 + len(rubric) * 2
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_cols)
    title_cell = ws.cell(row=1, column=1,
                         value=f"📝 {exam_name}  채점 결과  ({datetime.now().strftime('%Y-%m-%d')})")
    title_cell.fill = _hdr_fill(_PURPLE)
    title_cell.font = Font(bold=True, color=_WHITE, size=13, name="맑은 고딕")
    title_cell.alignment = _center()
    ws.row_dimensions[1].height = 32

    # ── 2행: 컬럼 헤더 ────────────────────────────────────────────────────────
    fixed_headers = ["학생명", f"총점 (/{total_max})", "비율 (%)"]
    for ci, h in enumerate(fixed_headers, 1):
        _apply_header(ws, 2, ci, h, _INDIGO)

    col = len(fixed_headers) + 1
    for r in rubric:
        ws.merge_cells(start_row=2, start_column=col, end_row=2, end_column=col + 1)
        _apply_header(ws, 2, col, f"{r.get('name','')} (/{r.get('max_score',0)})", _INDIGO)
        col += 2

    _apply_header(ws, 2, col, "전체 평가 의견", _INDIGO)
    ws.row_dimensions[2].height = 22

    # ── 3행~: 데이터 ──────────────────────────────────────────────────────────
    for ri, entry in enumerate(all_results, 3):
        sname   = entry.get("student_name", "")
        grading = entry.get("grading", {})
        ts      = grading.get("total_score", 0)
        ratio   = f"{ts / total_max * 100:.1f}%" if total_max else "-"
        comment = grading.get("overall_comment", "")

        row_bg = _BG_GRAY if ri % 2 == 0 else _WHITE

        _apply_cell(ws, ri, 1, sname, row_bg, bold=True, align="center")
        _apply_cell(ws, ri, 2, ts,    row_bg, align="center")
        _apply_cell(ws, ri, 3, ratio, row_bg, align="center")

        col = 4
        results_map = {r["element"]: r for r in grading.get("results", [])}
        for rb in rubric:
            res  = results_map.get(rb.get("name", ""), {})
            sc   = res.get("score", "-")
            mx   = rb.get("max_score", 1)
            r_pct = sc / mx if isinstance(sc, (int, float)) and mx else 0
            # 점수 셀 컬러
            if r_pct >= 0.8:
                bg_s = _BG_GREEN
            elif r_pct >= 0.4:
                bg_s = _BG_AMBER
            else:
                bg_s = _BG_RED

            _apply_cell(ws, ri, col,     sc,                       bg_s, align="center")
            _apply_cell(ws, ri, col + 1, res.get("evidence", ""),  row_bg)
            col += 2

        _apply_cell(ws, ri, col, comment, row_bg)
        ws.row_dimensions[ri].height = 60

    # ── 열 너비 자동 조정 ─────────────────────────────────────────────────────
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 10
    ws.column_dimensions["C"].width = 9
    col = 4
    for rb in rubric:
        ws.column_dimensions[get_column_letter(col)].width = 9
        ws.column_dimensions[get_column_letter(col + 1)].width = 38
        col += 2
    ws.column_dimensions[get_column_letter(col)].width = 50


def _build_detail_sheet(wb, exam_name, rubric, all_results):
    """시트2: 학생별 상세 근거 (학생·요소 각각 한 행)"""
    ws = wb.create_sheet(title="상세 근거")
    ws.freeze_panes = "A3"

    # 헤더
    headers = ["학생명", "채점 요소", f"점수", "만점", "비율", "채점 근거"]
    for ci, h in enumerate(headers, 1):
        _apply_header(ws, 1, ci, h, _INDIGO)
    ws.row_dimensions[1].height = 22

    row = 2
    for entry in all_results:
        sname   = entry.get("student_name", "")
        grading = entry.get("grading", {})
        results_map = {r["element"]: r for r in grading.get("results", [])}

        first = True
        for rb in rubric:
            res  = results_map.get(rb.get("name", ""), {})
            sc   = res.get("score", "-")
            mx   = rb.get("max_score", 1)
            r_pct = sc / mx if isinstance(sc, (int, float)) and mx else 0

            if r_pct >= 0.8:
                score_bg = _BG_GREEN
            elif r_pct >= 0.4:
                score_bg = _BG_AMBER
            else:
                score_bg = _BG_RED

            _apply_cell(ws, row, 1, sname if first else "",    _WHITE, bold=first, align="center")
            _apply_cell(ws, row, 2, rb.get("name", ""),        _WHITE)
            _apply_cell(ws, row, 3, sc,                        score_bg, align="center")
            _apply_cell(ws, row, 4, mx,                        _WHITE,   align="center")
            _apply_cell(ws, row, 5, f"{r_pct*100:.0f}%",       score_bg, align="center")
            _apply_cell(ws, row, 6, res.get("evidence", ""),   _WHITE)
            ws.row_dimensions[row].height = 55
            first = False
            row  += 1

    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 8
    ws.column_dimensions["D"].width = 8
    ws.column_dimensions["E"].width = 8
    ws.column_dimensions["F"].width = 55
