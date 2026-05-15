import os
import streamlit as st
import json
import time
from datetime import datetime
from pathlib import Path
from ocr_engine import load_ocr_reader, process_uploaded_file
from grader import setup_gemini, grade_student_answer
from excel_output import build_excel

# ─── 환경 감지: Streamlit Cloud vs 로컬 ─────────────────────────────────────────
# Streamlit Cloud는 STREAMLIT_SHARING_MODE 또는 HOSTNAME 환경변수로 감지
IS_CLOUD = bool(
    os.environ.get("STREAMLIT_SHARING_MODE") or
    os.environ.get("STLIT_DEPLOY_ID") or
    os.environ.get("IS_STREAMLIT_CLOUD")   # secrets에 직접 설정도 가능
)

# ─── 프리셋(설정) / 결과 저장 경로 ──────────────────────────────────────────────
# 로컬: 앱 폴더 내 presets/, results/ 사용
# 클라우드: 폴더는 만들어지지만 세션 간 유지 안 됨 → 다운로드 버튼으로 대체
PRESETS_DIR = Path(__file__).parent / "presets"
RESULTS_DIR = Path(__file__).parent / "results"
try:
    PRESETS_DIR.mkdir(exist_ok=True)
    RESULTS_DIR.mkdir(exist_ok=True)
except Exception:
    pass  # 권한 없을 시 무시

LAST_USED_FILE = PRESETS_DIR / "_마지막_사용.json"


def _load_preset(path: Path) -> dict:
    """프리셋 JSON 파일 읽기"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_preset(data: dict, path: Path):
    """프리셋 JSON 파일 쓰기"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _list_presets() -> list[Path]:
    """presets/ 폴더의 JSON 파일 목록 (숨김 파일 제외, 이름순)"""
    return sorted(
        [p for p in PRESETS_DIR.glob("*.json") if not p.name.startswith("_")],
        key=lambda p: p.stat().st_mtime, reverse=True
    )


def _apply_preset(data: dict):
    """프리셋 데이터를 session_state에 적용"""
    if isinstance(data, list):          # 구형식(루브릭만 저장) 호환
        st.session_state["rubric"] = data
        return
    for key in ("exam_name", "subject", "exam_questions"):
        if data.get(key):
            st.session_state[key] = data[key]
    if data.get("rubric"):
        st.session_state["rubric"] = data["rubric"]


def _current_settings() -> dict:
    """현재 session_state 설정을 dict로 반환"""
    return {
        "exam_name":      st.session_state.get("exam_name", ""),
        "subject":        st.session_state.get("subject", ""),
        "exam_questions": st.session_state.get("exam_questions", ""),
        "rubric":         st.session_state.get("rubric", []),
    }


# ─── 앱 시작 시: 마지막 사용 설정 자동 복원 (1회만) ───────────────────────────────
if "_preset_loaded" not in st.session_state:
    st.session_state["_preset_loaded"] = True
    if LAST_USED_FILE.exists():
        try:
            _apply_preset(_load_preset(LAST_USED_FILE))
        except Exception:
            pass

# ─── 페이지 설정 ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="수행평가 AI 채점기", page_icon="📝", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap');

/* Material Icon 폰트 깨짐(arrow_ 등) 방지를 위해 * 대신 특정 태그에만 폰트 적용 */
html, body, p, div, span:not(.material-icons), h1, h2, h3, h4, h5, h6, li, a, button, input, textarea { 
    font-family: 'Noto Sans KR', sans-serif; 
}
.hero {
    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #db2777 100%);
    padding: 2.5rem 2rem; border-radius: 20px; margin-bottom: 2rem;
    text-align: center; box-shadow: 0 20px 60px rgba(79,70,229,.35);
}
.hero h1 { color: white; font-size: 2.4rem; font-weight: 900; margin: 0; letter-spacing: -1px; }
.hero p  { color: rgba(255,255,255,.85); margin: .5rem 0 0; font-size: 1.05rem; }

.card {
    background: white; border-radius: 14px; padding: 1.4rem;
    box-shadow: 0 4px 20px rgba(0,0,0,.07); border: 1px solid #e5e7eb;
    margin-bottom: 1rem;
}
.el-cell {
    border-radius: 12px; padding: 1.2rem; margin-bottom: .8rem;
    border-left: 5px solid; background: #f9fafb;
}
.el-full    { border-color: #10b981; background: #f0fdf4; }
.el-partial { border-color: #f59e0b; background: #fffbeb; }
.el-zero    { border-color: #ef4444; background: #fef2f2; }

.score-badge {
    display: inline-block; padding: .25rem .75rem; border-radius: 999px;
    font-weight: 700; font-size: .9rem; margin-bottom: .5rem;
}
.badge-full    { background: #d1fae5; color: #065f46; }
.badge-partial { background: #fef3c7; color: #92400e; }
.badge-zero    { background: #fee2e2; color: #991b1b; }

.total-box {
    background: linear-gradient(135deg,#4f46e5,#7c3aed); color: white;
    border-radius: 14px; padding: 1.2rem 1.5rem; text-align: center;
    margin-bottom: 1rem;
}
.total-box .num { font-size: 2.5rem; font-weight: 900; }
.total-box .lbl { font-size: .9rem; opacity: .85; }

.step-badge {
    display: inline-block; background: #4f46e5; color: white;
    border-radius: 50%; width: 28px; height: 28px; line-height: 28px;
    text-align: center; font-weight: 700; margin-right: .5rem; font-size: .85rem;
}
.sidebar-section { background: #f8fafc; border-radius: 10px; padding: 1rem; margin-bottom: 1rem; }

.ocr-badge {
    display: inline-flex; align-items: center; gap: .4rem;
    background: linear-gradient(90deg,#4f46e5,#7c3aed); color: white;
    border-radius: 8px; padding: .35rem .9rem; font-size: .85rem; font-weight: 700;
    margin-bottom: .8rem;
}
</style>
""", unsafe_allow_html=True)

# ─── 사이드바 ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ API 설정")
    with st.expander("🔑 Gemini API 키", expanded=True):
        gemini_key = st.text_input("API Key", type="password",
                                   value=st.session_state.get("gemini_key", ""),
                                   key="gemini_key_input")
        if gemini_key:
            st.session_state["gemini_key"] = gemini_key
            st.success("✅ 입력됨")

    with st.expander("🤖 AI 모델 선택", expanded=False):
        model_options = {
            "gemini-2.5-flash (기본 권장)": "gemini-2.5-flash",
            "gemini-2.5-pro (고성능)": "gemini-2.5-pro",
            "gemini-2.0-flash (구버전)": "gemini-2.0-flash",
        }
        selected_label = st.selectbox("모델", list(model_options.keys()),
                                      index=0, key="model_select")
        st.session_state["model_name"] = model_options[selected_label]
        st.caption("OCR 및 채점 모두 동일 모델을 사용합니다.")

    st.markdown("---")
    st.markdown("""
**사용 순서**  
<span class='step-badge'>1</span> 수행평가 설정  
<span class='step-badge'>2</span> 답안 업로드  
<span class='step-badge'>3</span> OCR 처리  
<span class='step-badge'>4</span> AI 채점  
<span class='step-badge'>5</span> 엑셀 저장
""", unsafe_allow_html=True)

# ─── 헤더 ────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class='hero'>
  <h1>📝 수행평가 AI 채점기</h1>
  <p>스캔 답안 → Gemini Vision OCR → AI 자동 채점 → 엑셀 파일 저장</p>
</div>
""", unsafe_allow_html=True)

# ─── 탭 ─────────────────────────────────────────────────────────────────────────
tabs = st.tabs(["① 수행평가 설정", "② 답안 업로드", "③ OCR 처리", "④ AI 채점", "⑤ 엑셀 파일 저장"])

# ══════════════════════════════════════════════════════════
# TAB 1 : 수행평가 설정
# ══════════════════════════════════════════════════════════
with tabs[0]:

    if "rubric" not in st.session_state:
        st.session_state["rubric"] = [{"name": "", "max_score": 5, "criteria": ""}]

    # ════════════════════════════════════════════════════
    # ① 설정 저장 · 불러오기
    # ════════════════════════════════════════════════════
    with st.expander("💾 저장된 수행평가 불러오기 / 저장하기", expanded=True):
        presets = _list_presets()
        preset_names = [p.stem for p in presets]

        col_sel, col_load, col_save, col_dl = st.columns([3, 1, 1, 1])

        with col_sel:
            if preset_names:
                chosen = st.selectbox(
                    "저장된 설정 선택", options=[""] + preset_names,
                    format_func=lambda x: "— 선택하세요 —" if x == "" else x,
                    key="preset_select"
                )
            else:
                st.caption("저장된 설정이 없습니다. 아래에서 입력 후 저장하세요.")
                chosen = ""

        with col_load:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("📂 불러오기", use_container_width=True,
                         disabled=not chosen, key="btn_load_preset"):
                try:
                    data = _load_preset(PRESETS_DIR / f"{chosen}.json")
                    _apply_preset(data)
                    _save_preset(data, LAST_USED_FILE)   # 마지막 사용 갱신
                    st.success(f"✅ '{chosen}' 불러왔습니다!")
                    st.rerun()
                except Exception as e:
                    st.error(f"불러오기 실패: {e}")

        with col_save:
            st.markdown("<br>", unsafe_allow_html=True)
            exam_nm_now = st.session_state.get("exam_name", "").strip()
            if st.button("💾 PC 저장", type="primary", use_container_width=True,
                         disabled=not exam_nm_now, key="btn_save_preset",
                         help="현재 설정을 앱 폴더(presets/)에 저장합니다."):
                try:
                    data = _current_settings()
                    safe_name = "".join(c for c in exam_nm_now if c not in r'\/:*?"<>|')
                    save_path = PRESETS_DIR / f"{safe_name}.json"
                    _save_preset(data, save_path)
                    _save_preset(data, LAST_USED_FILE)
                    st.success(f"✅ '{safe_name}' 저장 완료!")
                    st.rerun()
                except Exception as e:
                    st.error(f"저장 실패: {e}")

        with col_dl:
            st.markdown("<br>", unsafe_allow_html=True)
            data_dl = _current_settings()
            fname_dl = f"{data_dl['exam_name'] or '수행평가'}_설정.json"
            st.download_button(
                "⬇️ 다운로드", key="btn_dl_preset",
                data=json.dumps(data_dl, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name=fname_dl, mime="application/json",
                use_container_width=True,
                help="브라우저 Downloads 폴더에 JSON 파일로 내보냅니다."
            )

        if chosen and presets:
            del_target = st.selectbox("삭제할 설정 선택", options=preset_names, key="preset_del_sel")
            if st.button(f"'{del_target}' 삭제", type="secondary", key="btn_del_preset"):
                try:
                    (PRESETS_DIR / f"{del_target}.json").unlink()
                    st.success(f"✅ '{del_target}' 삭제 완료")
                    st.rerun()
                except Exception as e:
                    st.error(f"삭제 실패: {e}")

        if st.session_state.get("exam_name"):
            st.markdown(f"""
            <div style='background:#ede9fe;border-radius:8px;padding:.55rem 1rem;
                        font-size:.88rem;color:#4c1d95;margin-top:.2rem'>
                📌 <b>{st.session_state.get('exam_name','')}</b>
                &nbsp;·&nbsp; {st.session_state.get('subject','')}
                &nbsp;·&nbsp; 루브릭 {len(st.session_state.get('rubric',[]))}개
                &nbsp;<span style='opacity:.6;font-size:.8rem'>— 앱 재시작 시 자동 복원됩니다</span>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")

    # ════════════════════════════════════════════════════
    # ② 기본 정보 입력
    # ════════════════════════════════════════════════════
    st.subheader("📋 수행평가 기본 정보")
    c1, c2 = st.columns(2)
    with c1:
        exam_name = st.text_input("수행평가명", value=st.session_state.get("exam_name", ""),
                                  placeholder="예: 2024 1학기 과학 수행평가")
        if exam_name:
            st.session_state["exam_name"] = exam_name
    with c2:
        subject = st.text_input("과목", value=st.session_state.get("subject", ""),
                                 placeholder="예: 과학, 국어, 수학")
        if subject:
            st.session_state["subject"] = subject

    st.subheader("📄 수행평가 문항")
    exam_q = st.text_area("수행평가 문항 전체 내용을 입력하세요",
                           value=st.session_state.get("exam_questions", ""),
                           height=180, placeholder="문항 번호, 지시문, 조건 등 전체를 입력하세요.")
    if exam_q:
        st.session_state["exam_questions"] = exam_q

    # ════════════════════════════════════════════════════
    # ③ 루브릭 입력
    # ════════════════════════════════════════════════════
    st.subheader("📏 채점 기준 (루브릭)")

    rubric = st.session_state["rubric"]
    # 키 누락 방어
    for item in rubric:
        item.setdefault("name", "")
        item.setdefault("max_score", 5)
        item.setdefault("criteria", "")

    for i, item in enumerate(rubric):
        with st.container():
            st.markdown(f"<div class='card'>", unsafe_allow_html=True)
            r1, r2, r3 = st.columns([3, 1, 0.4])
            with r1:
                rubric[i]["name"] = st.text_input(f"채점 요소명 #{i+1}", value=item.get("name", ""),
                                                   key=f"rname_{i}", placeholder="예: 탐구 목적 서술")
            with r2:
                rubric[i]["max_score"] = st.number_input(f"만점", min_value=1, max_value=100,
                                                          value=int(item.get("max_score", 5)), key=f"rmax_{i}")
            with r3:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🗑️", key=f"rdel_{i}", help="삭제") and len(rubric) > 1:
                    rubric.pop(i)
                    st.rerun()
            rubric[i]["criteria"] = st.text_area(f"채점 기준 #{i+1}",
                                                  value=item.get("criteria", ""), key=f"rcrit_{i}",
                                                  height=100,
                                                  placeholder="예:\n4점: 탐구 목적을 과학적 근거와 함께 명확히 서술\n2점: 탐구 목적 서술하였으나 근거 미흡\n0점: 탐구 목적 없음")
            st.markdown("</div>", unsafe_allow_html=True)

    if st.button("➕ 채점 요소 추가", use_container_width=True):
        st.session_state["rubric"].append({"name": "", "max_score": 5, "criteria": ""})
        st.rerun()

    total_max = sum(int(r.get("max_score", 0)) for r in st.session_state["rubric"])
    st.info(f"💯 총 배점: **{total_max}점** | 채점 요소 수: **{len(st.session_state['rubric'])}개**")

# ══════════════════════════════════════════════════════════
# TAB 2 : 답안 업로드
# ══════════════════════════════════════════════════════════
with tabs[1]:
    st.subheader("📤 학생 답안 파일 업로드")
    st.info("파일명 형식: **홍길동.jpg** 또는 **홍길동_1.pdf** — 파일명이 학생 이름으로 사용됩니다.")

    uploaded = st.file_uploader(
        "스캔 파일을 모두 선택하세요 (이미지/PDF)",
        type=["jpg", "jpeg", "png", "bmp", "tiff", "tif", "webp", "pdf"],
        accept_multiple_files=True, key="file_uploader"
    )

    if uploaded:
        if "student_files" not in st.session_state:
            st.session_state["student_files"] = {}
        for f in uploaded:
            raw_name = f.name.rsplit('.', 1)[0]
            student_name = raw_name.split('_')[0].strip()
            st.session_state["student_files"][student_name] = {
                "filename": f.name,
                "bytes": f.read()
            }

    if "student_files" in st.session_state and st.session_state["student_files"]:
        st.markdown("### 📋 업로드된 파일 목록")
        files = st.session_state["student_files"]
        for sname, fdata in files.items():
            c1, c2, c3 = st.columns([2, 3, 1])
            with c1:
                new_name = st.text_input("학생명", value=sname, key=f"sname_{sname}")
            with c2:
                st.markdown(f"<br>📄 `{fdata['filename']}`", unsafe_allow_html=True)
            with c3:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🗑️ 삭제", key=f"fdel_{sname}"):
                    del st.session_state["student_files"][sname]
                    st.rerun()
            # 이름 변경 반영
            if new_name != sname:
                st.session_state["student_files"][new_name] = st.session_state["student_files"].pop(sname)
                st.rerun()

        st.success(f"✅ 총 **{len(files)}명** 업로드 완료")
    else:
        st.warning("아직 업로드된 파일이 없습니다.")

# ══════════════════════════════════════════════════════════
# TAB 3 : OCR 처리
# ══════════════════════════════════════════════════════════
with tabs[2]:
    st.subheader("🔍 OCR 텍스트 추출")

    # OCR 엔진 안내 배지
    st.markdown("""
    <div class='ocr-badge'>
        ✨ Gemini Vision OCR &nbsp;|&nbsp; 한국어 손글씨 최적화
    </div>
    """, unsafe_allow_html=True)

    if "student_files" not in st.session_state or not st.session_state["student_files"]:
        st.warning("② 탭에서 먼저 파일을 업로드하세요.")
    else:
        if "ocr_results" not in st.session_state:
            st.session_state["ocr_results"] = {}

        api_key = st.session_state.get("gemini_key", "")
        model_name = st.session_state.get("model_name", "gemini-2.5-flash")

        if not api_key:
            st.error("사이드바에서 Gemini API 키를 먼저 입력하세요.")
        else:
            st.caption(f"사용 모델: `{model_name}` — 오류 발생 시 사이드바에서 모델을 변경하세요.")

            if st.button("🚀 전체 OCR 시작", type="primary", use_container_width=True):
                files = st.session_state["student_files"]
                prog = st.progress(0)
                status = st.empty()

                with st.spinner(f"Gemini Vision ({model_name}) 초기화 중…"):
                    reader = load_ocr_reader(api_key, model_name)

                for idx, (sname, fdata) in enumerate(files.items()):
                    status.info(f"⏳ **{sname}** 손글씨 인식 중… ({idx+1}/{len(files)})")
                    try:
                        text = process_uploaded_file(reader, fdata["bytes"], fdata["filename"])
                        st.session_state["ocr_results"][sname] = text
                    except Exception as e:
                        st.session_state["ocr_results"][sname] = f"[OCR 오류] {e}"
                    prog.progress((idx + 1) / len(files))

                status.success("✅ 전체 OCR 완료!")

        # 결과 미리보기 & 수정
        if st.session_state.get("ocr_results"):
            st.markdown("---")
            st.markdown("### ✏️ OCR 결과 확인 및 수정")
            st.caption("AI가 인식한 텍스트를 직접 수정할 수 있습니다.")
            for sname, text in st.session_state["ocr_results"].items():
                with st.expander(f"📄 {sname}", expanded=False):
                    edited = st.text_area("텍스트 수정", value=text, height=250, key=f"ocr_{sname}")
                    st.session_state["ocr_results"][sname] = edited

# ══════════════════════════════════════════════════════════
# TAB 4 : AI 채점
# ══════════════════════════════════════════════════════════
with tabs[3]:
    st.subheader("🤖 AI 자동 채점")

    ocr_done = bool(st.session_state.get("ocr_results"))
    api_ready = bool(st.session_state.get("gemini_key"))
    rubric_ready = any(r.get("name") for r in st.session_state.get("rubric", []))

    if not api_ready:
        st.error("사이드바에서 Gemini API 키를 입력하세요.")
    elif not ocr_done:
        st.warning("③ 탭에서 먼저 OCR을 실행하세요.")
    elif not rubric_ready:
        st.warning("① 탭에서 채점 기준(루브릭)을 입력하세요.")
    else:
        if st.button("🎯 전체 채점 시작", type="primary", use_container_width=True):
            model = setup_gemini(st.session_state["gemini_key"],
                                 st.session_state.get("model_name", "gemini-2.5-flash"))
            rubric = st.session_state["rubric"]
            exam_q = st.session_state.get("exam_questions", "")
            ocr_results = st.session_state["ocr_results"]

            if "grading_results" not in st.session_state:
                st.session_state["grading_results"] = {}

            prog = st.progress(0)
            status = st.empty()
            items = list(ocr_results.items())
            for idx, (sname, text) in enumerate(items):
                status.info(f"⏳ **{sname}** 채점 중… ({idx+1}/{len(items)})")
                try:
                    result = grade_student_answer(model, exam_q, rubric, text, sname)
                    st.session_state["grading_results"][sname] = result
                except Exception as e:
                    st.session_state["grading_results"][sname] = {"error": str(e)}
                prog.progress((idx + 1) / len(items))
                time.sleep(0.5)
            status.success("✅ 전체 채점 완료!")

        # 결과 표시
        if st.session_state.get("grading_results"):
            st.markdown("---")
            rubric = st.session_state["rubric"]
            total_max = sum(int(r.get("max_score", 0)) for r in rubric)

            # 요약 테이블
            st.markdown("### 📊 채점 결과 요약")
            summary_rows = []
            for sname, gr in st.session_state["grading_results"].items():
                if "error" in gr:
                    summary_rows.append({"학생명": sname, "총점": "오류", "비율": "-"})
                else:
                    ts = gr.get("total_score", 0)
                    summary_rows.append({
                        "학생명": sname,
                        "총점": f"{ts} / {total_max}",
                        "비율": f"{ts/total_max*100:.1f}%"
                    })
            st.dataframe(summary_rows, use_container_width=True)

            # 학생별 상세 결과
            st.markdown("### 📋 학생별 상세 채점")
            for sname, gr in st.session_state["grading_results"].items():
                with st.expander(f"👤 {sname}", expanded=False):
                    if "error" in gr:
                        st.error(f"채점 오류: {gr['error']}")
                        continue

                    total_score = gr.get("total_score", 0)
                    ratio = total_score / total_max if total_max else 0
                    st.markdown(f"""
                    <div class='total-box'>
                        <div class='lbl'>{sname} 최종 점수</div>
                        <div class='num'>{total_score} <span style='font-size:1.2rem;opacity:.8'>/ {total_max}점</span></div>
                        <div class='lbl'>{ratio*100:.1f}%</div>
                    </div>
                    """, unsafe_allow_html=True)

                    # 채점 요소별 셀
                    for res in gr.get("results", []):
                        sc = res.get("score", 0)
                        mx = res.get("max_score", 1)
                        r = sc / mx if mx else 0
                        if r >= 0.8:
                            cls, badge = "el-full", "badge-full"
                            icon = "✅"
                        elif r >= 0.4:
                            cls, badge = "el-partial", "badge-partial"
                            icon = "⚠️"
                        else:
                            cls, badge = "el-zero", "badge-zero"
                            icon = "❌"

                        st.markdown(f"""
                        <div class='el-cell {cls}'>
                            <div style='font-weight:700;margin-bottom:.4rem'>{icon} {res['element']}</div>
                            <span class='score-badge {badge}'>{sc} / {mx}점</span>
                            <p style='margin:.5rem 0 0;font-size:.92rem;color:#374151'>💬 {res['evidence']}</p>
                        </div>
                        """, unsafe_allow_html=True)

                    st.markdown(f"**🗒️ 전체 의견:** {gr.get('overall_comment','')}")

# ══════════════════════════════════════════════════════════
# TAB 5 : 엑셀 저장
# ══════════════════════════════════════════════════════════
with tabs[4]:
    st.subheader("📥 엑셀 파일 저장")

    if not st.session_state.get("grading_results"):
        st.warning("④ 탭에서 먼저 AI 채점을 완료하세요.")
    else:
        exam_name       = st.session_state.get("exam_name", "수행평가")
        rubric          = st.session_state["rubric"]
        ocr_results     = st.session_state.get("ocr_results", {})
        grading_results = st.session_state["grading_results"]

        n_ok  = sum(1 for gr in grading_results.values() if "error" not in gr)
        n_err = len(grading_results) - n_ok
        st.info(f"✅ 채점 완료: **{n_ok}명**" + (f"  |  ⚠️ 오류: **{n_err}명**" if n_err else ""))

        st.markdown("""
        <div class='card' style='display:flex;gap:2rem;align-items:center;padding:1.2rem 1.6rem'>
            <div style='font-size:3rem'>📊</div>
            <div>
                <div style='font-weight:700;font-size:1.1rem;margin-bottom:.3rem'>엑셀 파일 구성</div>
                <div style='color:#6b7280;font-size:.92rem'>
                    📋 <b>채점 요약</b> 시트 — 학생별 점수 한눈에<br>
                    📝 <b>상세 근거</b> 시트 — 요소별 점수 + AI 채점 근거
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        all_results = [
            {"student_name": sname, "ocr_text": ocr_results.get(sname, ""), "grading": gr}
            for sname, gr in grading_results.items()
        ]

        try:
            excel_bytes = build_excel(exam_name, rubric, all_results)
            safe_name   = "".join(c for c in exam_name if c not in r'\/:*?"<>|')
            filename    = f"{safe_name}_채점결과_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
            save_path   = RESULTS_DIR / filename

            btn_col, dl_col = st.columns(2)

            with btn_col:
                if st.button("💾 PC에 저장", type="primary", use_container_width=True,
                             help=f"채점/results/ 폴더에 엑셀 파일을 저장합니다."):
                    save_path.write_bytes(excel_bytes)
                    st.session_state["last_excel_path"] = str(save_path)
                    st.success(f"✅ 저장 완료!")
                    st.code(str(save_path), language=None)

            with dl_col:
                st.download_button(
                    label="⬇️ 브라우저 다운로드",
                    data=excel_bytes,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    help="브라우저 Downloads 폴더에 저장합니다."
                )

            # 저장된 파일 목록 표시
            saved_files = sorted(RESULTS_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
            if saved_files:
                st.markdown("---")
                st.markdown("### 📁 저장된 채점 결과 파일 목록")
                st.caption(f"저장 위치: `{RESULTS_DIR}`")
                for f in saved_files:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    sz    = f.stat().st_size
                    sz_str = f"{sz/1024:.1f} KB" if sz >= 1024 else f"{sz} B"
                    st.markdown(f"""
                    <div class='card' style='padding:.7rem 1rem;display:flex;
                         justify-content:space-between;align-items:center;margin-bottom:.4rem'>
                        <div>📊 <b>{f.name}</b></div>
                        <div style='color:#6b7280;font-size:.85rem'>{sz_str} &nbsp;·&nbsp; {mtime}</div>
                    </div>
                    """, unsafe_allow_html=True)

        except Exception as e:
            st.error(f"엑셀 생성 오류: {e}")
