import streamlit as st
from google import genai
from google.genai import types
import io
import re
import time
from PIL import Image

st.set_page_config(
    page_title="🎬 스틱맨 이미지 생성기",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-header { font-size:2rem; font-weight:700; text-align:center; margin-bottom:0.2rem; }
    .sub-header  { font-size:0.95rem; text-align:center; color:#888; margin-bottom:1.5rem; }
    .step-badge  { display:inline-block; padding:4px 14px; border-radius:20px; font-weight:600; font-size:0.82rem; margin-bottom:0.5rem; }
    .step-done   { background:#d4edda; color:#155724; }
    .step-active { background:#cce5ff; color:#004085; }
    .step-wait   { background:#f0f0f0; color:#888; }
</style>
""", unsafe_allow_html=True)

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
     데이터/실적 → 차트 도형, 기어, 지도 핀
     계약/문서 → 빈 종이 아이콘
     주의: 모든 간판, 화면, 문서에 글자(Text) 대신 기호/도형만 사용.

📝 출력 템플릿 (Output Template)
모든 프롬프트는 반드시 아래 문장으로 시작해야 합니다:
Upgraded stick-man 2D with thick black outline, pure white faces, single hard cel shading, thicker torso and neck, flat matte colors; SCENE: [행동 및 아이콘 묘사 (영문) + no text/letters 강조]"""

DEFAULT_FORMAT_PROMPT = "Upgraded stick-man 2D with thick black outline, pure white faces, single hard cel shading, thicker torso and neck, flat matte colors; SCENE: [장면 묘사], no text or letters."

LANGUAGE_SETTINGS = {
    "언어 없음": {
        "instruction": "Do NOT include any text, letters, numbers, or words in the image.",
        "negative": "no text, no letters, no words, no numbers, no writing",
    },
    "한국어": {
        "instruction": "You may include Korean text (한국어) in the image where appropriate. Keep text minimal.",
        "negative": "no English text, no Japanese text",
    },
    "일본어": {
        "instruction": "You may include Japanese text (日本語) in the image where appropriate. Keep text minimal.",
        "negative": "no English text, no Korean text",
    },
    "영어": {
        "instruction": "You may include English text in the image where appropriate. Keep text minimal.",
        "negative": "no Korean text, no Japanese text",
    },
}

def chars_per_second(seconds):
    return round(seconds * 4.5)

def split_script(script, seconds_per_cut):
    target = chars_per_second(seconds_per_cut)
    script = re.sub(r'\s+', ' ', script.strip())
    sentences = re.split(r'(?<=[.!?。])\s*', script)
    cuts, current = [], ""
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
    final_cuts = []
    for cut in cuts:
        while len(cut) > target * 1.6:
            final_cuts.append(cut[:target])
            cut = cut[target:]
        if cut:
            final_cuts.append(cut)
    return [c for c in final_cuts if c]

def build_image_prompt(client, cut_text, style_guide, format_prompt, language, cut_index, total_cuts):
    """Gemini 2.5 Flash 텍스트 모델로 프롬프트 생성"""
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

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f'컷 {cut_index}/{total_cuts}: 아래 대본 내용을 시각적으로 표현하는 이미지 프롬프트를 작성하세요.\n\n대본 내용:\n"{cut_text}"\n\n위 내용을 스틱맨 스타일로 표현하는 한 줄 영문 이미지 프롬프트를 작성하세요.',
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.7,
            max_output_tokens=300,
        )
    )
    return response.text.strip().strip('"').strip("'")

def generate_image(client, prompt, language):
    """
    이미지 생성 - imagen-3.0-generate-002 사용
    generate_images() 함수 + image_bytes 방식
    """
    lang_cfg = LANGUAGE_SETTINGS[language]
    full_prompt = f"{prompt}, {lang_cfg['negative']}"

    response = client.models.generate_images(
        model="imagen-3.0-generate-002",
        prompt=full_prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            output_mime_type="image/jpeg",
        )
    )
    if response.generated_images:
        image_bytes = response.generated_images[0].image.image_bytes
        return Image.open(io.BytesIO(image_bytes))
    return None

# 세션 초기화
for key, default in [("cuts",[]),("prompts",[]),("images",[]),("step",0),("analysis",""),("errors",[])]:
    if key not in st.session_state:
        st.session_state[key] = default

# 사이드바
with st.sidebar:
    st.markdown("## ⚙️ 설정")
    st.markdown("### 🔑 API 키")
    api_key = st.text_input("Gemini API Key", type="password", placeholder="AIza...")
    if api_key:
        st.success("API 키 입력됨 ✓")
    st.divider()

    st.markdown("### ⏱ 컷당 시간")
    seconds_per_cut = st.select_slider("초 선택", options=[5,10,15,20,25,30], value=10)
    st.caption(f"컷당 약 **{chars_per_second(seconds_per_cut)}글자** 기준으로 분할됩니다.")
    st.divider()

    st.markdown("### 🌐 이미지 텍스트 언어")
    language = st.radio("이미지에 표시할 언어", options=["언어 없음","한국어","일본어","영어"], index=0)
    st.divider()

    st.markdown("### 🎨 이미지 스타일 가이드")
    style_guide = st.text_area("스타일 가이드 (편집 가능)", value=DEFAULT_STYLE_GUIDE, height=220)
    st.divider()

    st.markdown("### 📋 프롬프트 형식 (선택)")
    format_prompt = st.text_area("커스텀 형식 (비워두면 기본값 사용)", placeholder="예: A 2D stickman scene...", height=80)
    if not format_prompt.strip():
        format_prompt = DEFAULT_FORMAT_PROMPT

# 메인
st.markdown('<div class="main-header">🎬 스틱맨 이미지 생성기</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Powered by Gemini 2.5 Flash + Imagen 3 🍌</div>', unsafe_allow_html=True)

script = st.text_area("📝 대본 입력", height=160,
    placeholder="여기에 대본을 붙여넣으세요...\n\n예) 부자들은 위기를 기회로 삼습니다. 주식 시장이 폭락할 때 오히려 매수 버튼을 누르죠.")

col_btn1, col_btn2 = st.columns([3,1])
with col_btn1:
    start_btn = st.button("🚀 이미지 생성 시작", type="primary", use_container_width=True)
with col_btn2:
    reset_btn = st.button("🔄 초기화", use_container_width=True)

if reset_btn:
    for k in ["cuts","prompts","images","errors"]:
        st.session_state[k] = []
    st.session_state.step = 0
    st.session_state.analysis = ""
    st.rerun()

def step_badge(label, status):
    return f'<span class="step-badge step-{status}">{label}</span>'

if st.session_state.step > 0:
    s = st.session_state.step
    st.markdown("---")
    c1,c2,c3,c4 = st.columns(4)
    with c1: st.markdown(step_badge("1. 대본 분석","done" if s>=1 else "wait"), unsafe_allow_html=True)
    with c2: st.markdown(step_badge("2. 초단위 분할","done" if s>=2 else ("active" if s==1 else "wait")), unsafe_allow_html=True)
    with c3: st.markdown(step_badge("3. 프롬프트 생성","done" if s>=3 else ("active" if s==2 else "wait")), unsafe_allow_html=True)
    with c4: st.markdown(step_badge("4. 이미지 생성","done" if s>=4 else ("active" if s==3 else "wait")), unsafe_allow_html=True)

if start_btn:
    if not api_key:
        st.error("❌ 사이드바에서 Gemini API 키를 먼저 입력해주세요.")
        st.stop()
    if not script.strip():
        st.error("❌ 대본을 입력해주세요.")
        st.stop()

    st.session_state.cuts = []
    st.session_state.prompts = []
    st.session_state.images = []
    st.session_state.errors = []
    st.session_state.step = 0
    st.session_state.analysis = ""

    client = genai.Client(api_key=api_key)

    # STEP 1: 대본 분석
    with st.status("**1단계: 대본 분석 중...**", expanded=True) as status_1:
        try:
            r = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"아래 대본을 분석하고, 다음 항목을 간단하게 요약해주세요 (한국어):\n1. 주제 (한 줄)\n2. 전달 메시지 (핵심)\n3. 주요 등장 개념/인물\n\n대본:\n{script}",
                config=types.GenerateContentConfig(max_output_tokens=300, temperature=0.3)
            )
            st.session_state.analysis = r.text.strip()
            st.session_state.step = 1
            st.markdown(st.session_state.analysis)
            status_1.update(label="✅ 1단계: 대본 분석 완료", state="complete")
        except Exception as e:
            status_1.update(label=f"❌ 대본 분석 실패: {e}", state="error")
            st.stop()

    # STEP 2: 초단위 분할
    with st.status("**2단계: 초단위 분할 중...**", expanded=True) as status_2:
        cuts = split_script(script, seconds_per_cut)
        st.session_state.cuts = cuts
        st.session_state.step = 2
        st.write(f"📌 총 **{len(cuts)}개** 컷 (컷당 {seconds_per_cut}초, 약 {chars_per_second(seconds_per_cut)}글자 기준)")
        for i, cut in enumerate(cuts):
            st.markdown(f"**컷 {i+1}** ({len(cut)}글자): {cut}")
        status_2.update(label=f"✅ 2단계: {len(cuts)}개 컷으로 분할 완료", state="complete")

    # STEP 3: 프롬프트 생성
    prompts = []
    with st.status("**3단계: 이미지 프롬프트 생성 중...**", expanded=True) as status_3:
        prog3 = st.progress(0)
        for i, cut in enumerate(cuts):
            st.write(f"🖊 컷 {i+1}/{len(cuts)} 프롬프트 생성 중...")
            try:
                p = build_image_prompt(client, cut, style_guide, format_prompt, language, i+1, len(cuts))
                prompts.append(p)
                st.caption(f"→ {p[:120]}{'...' if len(p)>120 else ''}")
            except Exception as e:
                prompts.append(f"{DEFAULT_FORMAT_PROMPT} Scene: {cut[:80]}")
                st.session_state.errors.append(f"컷 {i+1} 프롬프트 오류: {e}")
            prog3.progress((i+1)/len(cuts))
            time.sleep(0.3)
        st.session_state.prompts = prompts
        st.session_state.step = 3
        status_3.update(label=f"✅ 3단계: {len(prompts)}개 프롬프트 생성 완료", state="complete")

    # STEP 4: 이미지 생성
    images = [None]*len(cuts)
    with st.status("**4단계: 이미지 생성 중 (Imagen 3 🍌)...**", expanded=True) as status_4:
        prog4 = st.progress(0)
        img_ph = st.empty()
        for i, (cut, prompt) in enumerate(zip(cuts, prompts)):
            st.write(f"🎨 컷 {i+1}/{len(cuts)} 이미지 생성 중...")
            try:
                img = generate_image(client, prompt, language)
                images[i] = img
                if img:
                    img_ph.image(img, caption=f"컷 {i+1} 미리보기", width=300)
            except Exception as e:
                st.session_state.errors.append(f"컷 {i+1} 이미지 오류: {e}")
                st.warning(f"⚠️ 컷 {i+1} 생성 실패: {e}")
            prog4.progress((i+1)/len(cuts))
            time.sleep(0.5)
        img_ph.empty()
        st.session_state.images = images
        st.session_state.step = 4
        ok = sum(1 for img in images if img is not None)
        status_4.update(label=f"✅ 4단계: {ok}/{len(cuts)}개 이미지 생성 완료", state="complete")

    st.rerun()

# 결과 출력
if st.session_state.step == 4 and st.session_state.cuts:
    st.markdown("---")
    st.markdown("## 🎉 생성 결과")
    if st.session_state.errors:
        with st.expander(f"⚠️ 오류 {len(st.session_state.errors)}건"):
            for err in st.session_state.errors:
                st.caption(err)

    cuts = st.session_state.cuts
    prompts = st.session_state.prompts
    images = st.session_state.images

    for row_start in range(0, len(cuts), 3):
        row_items = list(enumerate(cuts[row_start:row_start+3], start=row_start))
        cols = st.columns(len(row_items))
        for col, (i, cut) in zip(cols, row_items):
            with col:
                st.markdown(f"**컷 {i+1}**")
                if images[i] is not None:
                    st.image(images[i], use_container_width=True)
                    buf = io.BytesIO()
                    images[i].save(buf, format="PNG")
                    st.download_button(f"💾 컷{i+1} 저장", buf.getvalue(), f"cut_{i+1:02d}.png", "image/png", key=f"dl_{i}")
                else:
                    st.warning("이미지 생성 실패")
                st.caption(f"📝 {cut}")
                if i < len(prompts):
                    with st.expander("프롬프트 보기"):
                        st.code(prompts[i], language="text")

    if any(img is not None for img in images):
        import zipfile
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            for i, img in enumerate(images):
                if img is not None:
                    b = io.BytesIO()
                    img.save(b, format="PNG")
                    zf.writestr(f"cut_{i+1:02d}.png", b.getvalue())
        st.markdown("---")
        st.download_button("📦 전체 이미지 ZIP 다운로드", zip_buf.getvalue(), "stickman_cuts.zip", "application/zip", type="primary")

if st.session_state.step == 0:
    st.markdown("---")
    st.info("👈 사이드바에서 설정을 완료한 뒤, 대본을 입력하고 **🚀 이미지 생성 시작** 버튼을 눌러주세요.")
    with st.expander("📌 사용 방법"):
        st.markdown("""
1. 사이드바에 **Gemini API 키** 입력
2. **컷당 시간** 설정 (5초 ~ 30초, 5초 단위)
3. **이미지 언어** 선택 (언어 없음 / 한국어 / 일본어 / 영어)
4. 스타일 가이드 / 프롬프트 형식 필요 시 수정
5. 대본 입력 후 **이미지 생성 시작** 클릭

**모델 정보:**
- 🧠 대본 분석 / 프롬프트 생성: `gemini-2.5-flash`
- 🎨 이미지 생성: `imagen-3.0-generate-002`

⚠️ **참고:** Imagen 3는 유료 API 플랜에서만 사용 가능합니다.
Google AI Studio → 결제 수단 등록 필요
        """)
