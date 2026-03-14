import streamlit as st
import google.generativeai as genai
from google.generativeai import types
import base64
import io
import re
import time
from PIL import Image

# ─────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────
st.set_page_config(
    page_title="🎬 스틱맨 이미지 생성기",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────
# 스타일 (CSS)
# ─────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        text-align: center;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 0.95rem;
        text-align: center;
        color: #888;
        margin-bottom: 1.5rem;
    }
    .step-badge {
        display: inline-block;
        padding: 4px 14px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.82rem;
        margin-bottom: 0.5rem;
    }
    .step-done   { background:#d4edda; color:#155724; }
    .step-active { background:#cce5ff; color:#004085; }
    .step-wait   { background:#f0f0f0; color:#888; }
    .cut-card {
        background: #fafafa;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 14px;
        margin-bottom: 14px;
    }
    .cut-text {
        font-size: 0.9rem;
        color: #333;
        margin-bottom: 6px;
    }
    .prompt-box {
        background: #f0f4ff;
        border-left: 3px solid #4a6cf7;
        padding: 8px 12px;
        font-size: 0.8rem;
        color: #444;
        border-radius: 0 6px 6px 0;
        white-space: pre-wrap;
        margin-bottom: 8px;
    }
    .img-caption {
        font-size: 0.78rem;
        color: #777;
        text-align: center;
    }
    div[data-testid="stExpander"] > div { padding: 0.4rem 0; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────
# 기본 스타일 가이드 (디폴트)
# ─────────────────────────────────────────
DEFAULT_STYLE_GUIDE = """당신은 '2D 스틱맨 애니메이션 전문 프롬프트 디렉터'입니다.

🎨 스타일 가이드 (Style Lock)
1. 비주얼 정의 (Visuals)
 캐릭터: Pure-white round faces, single hard cel shading(턱 아래 1단 그림자), thick black outline, thicker torso and neck, stick limbs, flat matte colors.
 배경: 저채도 평면 블록(Low saturation flat blocks), 글자 절대 금지.
 네거티브(내재): 3D, photoreal, gradient, soft light, text, letters, speech bubble.

2. 장면 해석 (Scene Interpretation)
 행동 중심: 감정은 눈썹/입선으로, 동작은 명확한 동사(leans, points, nods, clasps, gestures)로 표현.
 경제 개념 시각화: 추상적 개념은 인물+아이콘/도형으로 변환.
     상승/하락 → 화살표 아이콘(Arrow icons)
     데이터/실적 → 차트 도형, 기어, 지도 핀 (Chart shapes, Gears, Map pins)
     계약/문서 → 빈 종이 아이콘 (Blank paper icons)
     주의: 모든 간판, 화면, 문서에 글자(Text) 대신 기호/도형만 사용.

📝 출력 템플릿 (Output Template)
모든 프롬프트는 반드시 아래 문장으로 시작해야 합니다:
Upgraded stick-man 2D with thick black outline, pure white faces, single hard cel shading, thicker torso and neck, flat matte colors; SCENE: [행동 및 아이콘 묘사 (영문) + no text/letters 강조]"""

DEFAULT_FORMAT_PROMPT = "Upgraded stick-man 2D with thick black outline, pure white faces, single hard cel shading, thicker torso and neck, flat matte colors; SCENE: [장면 묘사], no text or letters."

# ─────────────────────────────────────────
# 언어 설정 매핑
# ─────────────────────────────────────────
LANGUAGE_SETTINGS = {
    "언어 없음": {
        "instruction": "Do NOT include any text, letters, numbers, or words in the image. All signage, screens, documents must use only geometric shapes and symbols.",
        "negative": "no text, no letters, no words, no numbers, no writing",
    },
    "한국어": {
        "instruction": "You may include Korean text (한국어) in the image where appropriate (signs, labels, minimal UI elements). Keep text minimal and natural.",
        "negative": "no English text, no Japanese text",
    },
    "일본어": {
        "instruction": "You may include Japanese text (日本語) in the image where appropriate (signs, labels, minimal UI elements). Keep text minimal and natural.",
        "negative": "no English text, no Korean text",
    },
    "영어": {
        "instruction": "You may include English text in the image where appropriate (signs, labels, minimal UI elements). Keep text minimal and natural.",
        "negative": "no Korean text, no Japanese text",
    },
}

# ─────────────────────────────────────────
# 헬퍼 함수
# ─────────────────────────────────────────

def chars_per_second(seconds: int) -> int:
    """한국어 기준 1초 = 4~5글자 (평균 4.5)"""
    return round(seconds * 4.5)


def split_script(script: str, seconds_per_cut: int) -> list[str]:
    """
    대본을 컷당 초 기준으로 분할.
    문장 경계(., !, ?, 。)를 우선하고, 없으면 글자 수로 자름.
    """
    target = chars_per_second(seconds_per_cut)
    # 공백 정규화
    script = re.sub(r'\s+', ' ', script.strip())

    sentences = re.split(r'(?<=[.!?。])\s*', script)
    cuts = []
    current = ""

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if not current:
            current = sent
        elif len(current) + len(sent) + 1 <= target * 1.4:
            current += " " + sent
        else:
            cuts.append(current.strip())
            current = sent

    if current:
        cuts.append(current.strip())

    # 너무 긴 컷은 강제 분할
    final_cuts = []
    for cut in cuts:
        while len(cut) > target * 1.6:
            final_cuts.append(cut[:target])
            cut = cut[target:]
        if cut:
            final_cuts.append(cut)

    return [c for c in final_cuts if c]


def build_image_prompt(
    cut_text: str,
    style_guide: str,
    format_prompt: str,
    language: str,
    cut_index: int,
    total_cuts: int,
    gemini_client,
) -> str:
    """Gemini 2.5 Flash 로 이미지 프롬프트 생성"""
    lang_cfg = LANGUAGE_SETTINGS[language]

    system = f"""당신은 2D 스틱맨 애니메이션 전문 이미지 프롬프트 작가입니다.
아래 스타일 가이드를 엄격히 따르세요:

{style_guide}

언어 지침: {lang_cfg['instruction']}
네거티브: {lang_cfg['negative']}

출력 형식:
- 반드시 영어로만 작성하세요.
- 프롬프트는 한 줄로 출력하세요. 설명, 번호, 따옴표 불필요.
- 프롬프트 형식: {format_prompt}"""

    user_msg = f"""컷 {cut_index}/{total_cuts}: 아래 대본 내용을 시각적으로 표현하는 이미지 프롬프트를 작성하세요.

대본 내용:
\"{cut_text}\"

위 내용을 스틱맨 스타일로 표현하는 한 줄 영문 이미지 프롬프트를 작성하세요."""

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_msg,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.7,
            max_output_tokens=300,
        ),
    )
    return response.text.strip().strip('"').strip("'")


def generate_image(prompt: str, language: str, gemini_client) -> Image.Image | None:
    """Nano Banana 2 (gemini-2.5-flash-preview-image-generation) 로 이미지 생성"""
    lang_cfg = LANGUAGE_SETTINGS[language]
    full_prompt = f"{prompt}, {lang_cfg['negative']}"

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash-preview-image-generation",
        contents=full_prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
            temperature=1.0,
        ),
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            img_bytes = base64.b64decode(part.inline_data.data)
            return Image.open(io.BytesIO(img_bytes))

    return None


# ─────────────────────────────────────────
# 세션 상태 초기화
# ─────────────────────────────────────────
if "cuts" not in st.session_state:
    st.session_state.cuts = []
if "prompts" not in st.session_state:
    st.session_state.prompts = []
if "images" not in st.session_state:
    st.session_state.images = []
if "step" not in st.session_state:
    st.session_state.step = 0  # 0=대기, 1=분석완료, 2=분할완료, 3=프롬프트완료, 4=완료
if "analysis" not in st.session_state:
    st.session_state.analysis = ""
if "errors" not in st.session_state:
    st.session_state.errors = []

# ─────────────────────────────────────────
# 사이드바 (설정)
# ─────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ 설정")

    # API Key
    st.markdown("### 🔑 API 키")
    api_key = st.text_input(
        "Gemini API Key",
        type="password",
        placeholder="AIza...",
        help="Google AI Studio에서 발급받은 API 키를 입력하세요.",
    )
    if api_key:
        st.success("API 키 입력됨 ✓")

    st.divider()

    # 컷당 시간 (5초 ~ 30초, 5초 단위)
    st.markdown("### ⏱ 컷당 시간")
    seconds_per_cut = st.select_slider(
        "초 선택",
        options=[5, 10, 15, 20, 25, 30],
        value=10,
        help="한 컷에 해당하는 시간(초). 한국어 기준 1초 ≈ 4~5글자.",
    )
    st.caption(f"컷당 약 **{chars_per_second(seconds_per_cut)}글자** 기준으로 분할됩니다.")

    st.divider()

    # 이미지 언어
    st.markdown("### 🌐 이미지 텍스트 언어")
    language = st.radio(
        "이미지에 표시할 언어",
        options=["언어 없음", "한국어", "일본어", "영어"],
        index=0,
        help="생성된 이미지 안의 텍스트(간판, 레이블 등) 언어를 선택합니다.",
    )

    st.divider()

    # 스타일 가이드
    st.markdown("### 🎨 이미지 스타일 가이드")
    style_guide = st.text_area(
        "스타일 가이드 (편집 가능)",
        value=DEFAULT_STYLE_GUIDE,
        height=220,
        help="이미지 생성 시 적용할 스타일 지침입니다. 자유롭게 수정하세요.",
    )

    st.divider()

    # 프롬프트 형식
    st.markdown("### 📋 프롬프트 형식 (선택)")
    format_prompt = st.text_area(
        "커스텀 형식 (비워두면 기본값 사용)",
        placeholder="예: A 2D stickman scene showing [action], minimal flat design...",
        height=80,
        help="비워두면 스틱맨 기본 형식이 적용됩니다.",
    )
    if not format_prompt.strip():
        format_prompt = DEFAULT_FORMAT_PROMPT

# ─────────────────────────────────────────
# 메인 영역
# ─────────────────────────────────────────
st.markdown('<div class="main-header">🎬 스틱맨 이미지 생성기</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Powered by Gemini 2.5 Flash + Nano Banana 2 🍌</div>', unsafe_allow_html=True)

# 대본 입력
script = st.text_area(
    "📝 대본 입력",
    height=160,
    placeholder="여기에 대본을 붙여넣으세요...\n\n예) 부자들은 위기를 기회로 삼습니다. 주식 시장이 폭락할 때 오히려 매수 버튼을 누르죠.",
)

# 생성 버튼
col_btn1, col_btn2 = st.columns([3, 1])
with col_btn1:
    start_btn = st.button("🚀 이미지 생성 시작", type="primary", use_container_width=True)
with col_btn2:
    reset_btn = st.button("🔄 초기화", use_container_width=True)

if reset_btn:
    for k in ["cuts", "prompts", "images", "step", "analysis", "errors"]:
        del st.session_state[k]
    st.rerun()

# ─────────────────────────────────────────
# 진행 상태 표시
# ─────────────────────────────────────────
def step_badge(label: str, status: str) -> str:
    return f'<span class="step-badge step-{status}">{label}</span>'

if st.session_state.step > 0:
    s = st.session_state.step
    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(step_badge("1. 대본 분석", "done" if s >= 1 else "wait"), unsafe_allow_html=True)
    with c2:
        st.markdown(step_badge("2. 초단위 분할", "done" if s >= 2 else ("active" if s == 1 else "wait")), unsafe_allow_html=True)
    with c3:
        st.markdown(step_badge("3. 프롬프트 생성", "done" if s >= 3 else ("active" if s == 2 else "wait")), unsafe_allow_html=True)
    with c4:
        st.markdown(step_badge("4. 이미지 생성", "done" if s >= 4 else ("active" if s == 3 else "wait")), unsafe_allow_html=True)

# ─────────────────────────────────────────
# 메인 파이프라인
# ─────────────────────────────────────────
if start_btn:
    # 유효성 검사
    if not api_key:
        st.error("❌ 사이드바에서 Gemini API 키를 먼저 입력해주세요.")
        st.stop()
    if not script.strip():
        st.error("❌ 대본을 입력해주세요.")
        st.stop()

    # 초기화
    st.session_state.cuts = []
    st.session_state.prompts = []
    st.session_state.images = []
    st.session_state.errors = []
    st.session_state.step = 0
    st.session_state.analysis = ""

    # Gemini 클라이언트
    client = genai.Client(api_key=api_key)

    # ── STEP 1: 대본 분석 ──────────────────
    with st.status("**1단계: 대본 분석 중...**", expanded=True) as status_1:
        try:
            analysis_resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"""아래 대본을 분석하고, 다음 항목을 간단하게 요약해주세요 (한국어):
1. 주제 (한 줄)
2. 전달 메시지 (핵심)
3. 주요 등장 개념/인물

대본:
{script}""",
                config=types.GenerateContentConfig(max_output_tokens=300, temperature=0.3),
            )
            st.session_state.analysis = analysis_resp.text.strip()
            st.session_state.step = 1
            st.markdown(st.session_state.analysis)
            status_1.update(label="✅ 1단계: 대본 분석 완료", state="complete")
        except Exception as e:
            status_1.update(label=f"❌ 대본 분석 실패: {e}", state="error")
            st.stop()

    # ── STEP 2: 초단위 분할 ────────────────
    with st.status("**2단계: 초단위 분할 중...**", expanded=True) as status_2:
        cuts = split_script(script, seconds_per_cut)
        st.session_state.cuts = cuts
        st.session_state.step = 2

        st.write(f"📌 총 **{len(cuts)}개** 컷으로 분할 (컷당 {seconds_per_cut}초, 약 {chars_per_second(seconds_per_cut)}글자 기준)")
        for i, cut in enumerate(cuts):
            st.markdown(f"**컷 {i+1}** ({len(cut)}글자): {cut}")
        status_2.update(label=f"✅ 2단계: {len(cuts)}개 컷으로 분할 완료", state="complete")

    # ── STEP 3: 프롬프트 생성 ──────────────
    prompts = []
    with st.status("**3단계: 이미지 프롬프트 생성 중...**", expanded=True) as status_3:
        prog3 = st.progress(0)
        for i, cut in enumerate(cuts):
            st.write(f"🖊 컷 {i+1}/{len(cuts)} 프롬프트 생성 중...")
            try:
                p = build_image_prompt(
                    cut_text=cut,
                    style_guide=style_guide,
                    format_prompt=format_prompt,
                    language=language,
                    cut_index=i + 1,
                    total_cuts=len(cuts),
                    gemini_client=client,
                )
                prompts.append(p)
                st.caption(f"→ {p[:120]}{'...' if len(p) > 120 else ''}")
            except Exception as e:
                fallback = f"{format_prompt} Scene showing: {cut[:80]}"
                prompts.append(fallback)
                st.session_state.errors.append(f"컷 {i+1} 프롬프트 오류: {e}")
            prog3.progress((i + 1) / len(cuts))
            time.sleep(0.3)  # rate limit 여유

        st.session_state.prompts = prompts
        st.session_state.step = 3
        status_3.update(label=f"✅ 3단계: {len(prompts)}개 프롬프트 생성 완료", state="complete")

    # ── STEP 4: 이미지 생성 ────────────────
    images = [None] * len(cuts)
    with st.status("**4단계: 이미지 생성 중 (Nano Banana 2 🍌)...**", expanded=True) as status_4:
        prog4 = st.progress(0)
        img_placeholder = st.empty()

        for i, (cut, prompt) in enumerate(zip(cuts, prompts)):
            st.write(f"🎨 컷 {i+1}/{len(cuts)} 이미지 생성 중...")
            try:
                img = generate_image(prompt, language, client)
                images[i] = img
                if img:
                    img_placeholder.image(img, caption=f"컷 {i+1} 미리보기", width=300)
            except Exception as e:
                st.session_state.errors.append(f"컷 {i+1} 이미지 오류: {e}")
                st.warning(f"⚠️ 컷 {i+1} 생성 실패: {e}")
            prog4.progress((i + 1) / len(cuts))
            time.sleep(0.5)

        img_placeholder.empty()
        st.session_state.images = images
        st.session_state.step = 4
        success_count = sum(1 for img in images if img is not None)
        status_4.update(
            label=f"✅ 4단계: {success_count}/{len(cuts)}개 이미지 생성 완료",
            state="complete",
        )

    st.rerun()

# ─────────────────────────────────────────
# 결과 출력 (생성 완료 후)
# ─────────────────────────────────────────
if st.session_state.step == 4 and st.session_state.cuts:
    st.markdown("---")
    st.markdown("## 🎉 생성 결과")

    # 오류 요약
    if st.session_state.errors:
        with st.expander(f"⚠️ 오류 {len(st.session_state.errors)}건"):
            for err in st.session_state.errors:
                st.caption(err)

    cuts = st.session_state.cuts
    prompts = st.session_state.prompts
    images = st.session_state.images

    # 컷 카드: 3열 그리드
    cols_per_row = 3
    for row_start in range(0, len(cuts), cols_per_row):
        row_cuts = cuts[row_start : row_start + cols_per_row]
        cols = st.columns(len(row_cuts))
        for col, (cut_idx, cut) in zip(cols, enumerate(row_cuts, start=row_start)):
            i = cut_idx
            with col:
                st.markdown(f"**컷 {i+1}**")
                # 이미지
                if images[i] is not None:
                    st.image(images[i], use_container_width=True)
                    # 다운로드 버튼
                    buf = io.BytesIO()
                    images[i].save(buf, format="PNG")
                    st.download_button(
                        label=f"💾 컷{i+1} 저장",
                        data=buf.getvalue(),
                        file_name=f"cut_{i+1:02d}.png",
                        mime="image/png",
                        key=f"dl_{i}",
                    )
                else:
                    st.warning("이미지 생성 실패")

                # 대본 텍스트
                st.caption(f"📝 {cut}")

                # 프롬프트 (접기)
                if i < len(prompts):
                    with st.expander("프롬프트 보기"):
                        st.code(prompts[i], language="text")

    # 전체 다운로드 — ZIP
    if any(img is not None for img in images):
        import zipfile
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            for i, img in enumerate(images):
                if img is not None:
                    img_buf = io.BytesIO()
                    img.save(img_buf, format="PNG")
                    zf.writestr(f"cut_{i+1:02d}.png", img_buf.getvalue())
        st.markdown("---")
        st.download_button(
            label="📦 전체 이미지 ZIP 다운로드",
            data=zip_buf.getvalue(),
            file_name="stickman_cuts.zip",
            mime="application/zip",
            type="primary",
        )

# 대기 상태 안내
if st.session_state.step == 0:
    st.markdown("---")
    st.info(
        "👈 사이드바에서 설정을 완료한 뒤, 대본을 입력하고 **🚀 이미지 생성 시작** 버튼을 눌러주세요.\n\n"
        "**처리 순서:** 대본 분석 → 초단위 분할 → 프롬프트 생성 → 이미지 생성"
    )
    with st.expander("📌 사용 방법"):
        st.markdown("""
1. 사이드바에 **Gemini API 키** 입력
2. **컷당 시간** 설정 (5초 ~ 30초, 5초 단위)
3. **이미지 언어** 선택 (언어 없음 / 한국어 / 일본어 / 영어)
4. 스타일 가이드 / 프롬프트 형식 필요 시 수정
5. 대본 입력 후 **이미지 생성 시작** 클릭
6. 4단계 자동 처리 후 결과 확인 및 다운로드

**모델 정보:**
- 🧠 대본 분석 / 프롬프트 생성: `gemini-2.5-flash`
- 🎨 이미지 생성: `gemini-2.5-flash-preview-image-generation` (Nano Banana 2 🍌)
        """)
