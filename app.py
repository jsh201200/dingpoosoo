import streamlit as st
from google import genai
from google.genai import types
import base64
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

DEFAULT_STYLE_GUIDE = """In the distinctive hand-drawn, loose ink-and-wash style of Quentin Blake, reminiscent of the aesthetic in vintage children's book illustrations.
The scene features loose, expressive, dynamic scribbled ink line work. The coloring is a minimal, flat, transparent watercolor wash palette. The composition is isolated on a pure, clean white background, with only essential grounding details (like minimal floor scratches or soft shadows).
Colors are limited to soft, muted tones (e.g., washed-out blues, pale greens, ochre, soft reds) applied loosely over the ink lines.
- NO text, NO letters, NO words anywhere in image
- NO 3D, NO photoreal, NO digital art style
- Expressive character poses and emotions through body language and facial lines
- Minimal background, focus on character action"""

DEFAULT_FORMAT_PROMPT = """In the distinctive hand-drawn, loose ink-and-wash style of Quentin Blake, vintage children's book illustration; loose expressive scribbled ink lines, minimal transparent watercolor wash, pure white background, soft muted tones (washed blues, pale greens, ochre, soft reds); SCENE: {scene_description}; no text, no letters."""

LANGUAGE_SETTINGS = {
    "언어 없음": "absolutely no text, no letters, no words, no numbers, no writing of any kind in the image",
    "한국어": "Korean text only allowed on signs or labels if necessary, minimal",
    "일본어": "Japanese text only allowed on signs or labels if necessary, minimal",
    "영어": "English text only allowed on signs or labels if necessary, minimal",
}

def chars_per_second(seconds):
    return round(seconds * 4.5)

def split_script(script, seconds_per_cut):
    target = chars_per_second(seconds_per_cut)
    script = re.sub(r'\s+', ' ', script.strip())
    # 문장 단위로 먼저 분리 (마침표, 느낌표, 물음표, 줄바꿈 기준)
    sentences = re.split(r'(?<=[.!?。\n])\s*', script)
    cuts, current = [], ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if not current:
            current = sent
        elif len(current) + len(sent) + 1 <= target * 1.3:
            current += " " + sent
        else:
            cuts.append(current.strip())
            current = sent
    if current:
        cuts.append(current.strip())
    # 너무 긴 컷 강제 분할
    final_cuts = []
    for cut in cuts:
        while len(cut) > target * 1.5:
            final_cuts.append(cut[:target])
            cut = cut[target:]
        if cut:
            final_cuts.append(cut)
    return [c for c in final_cuts if c]

def build_image_prompt(client, cut_text, style_guide, format_prompt, language, cut_index, total_cuts):
    """
    Gemini 2.5 Flash로 대본 내용 → 영문 이미지 프롬프트 생성
    대본의 구체적인 행동/장면이 반드시 반영되도록 강하게 지시
    """
    lang_note = LANGUAGE_SETTINGS[language]

    system_instruction = f"""You are an expert image prompt writer specializing in 2D stick-man animation scenes.

YOUR ONLY JOB: Convert the given Korean script segment into ONE precise English image generation prompt.

MANDATORY RULES:
1. The prompt MUST specifically describe what is HAPPENING in the script — the exact action, emotion, or concept from the text
2. Always start with the style prefix: "Upgraded stick-man 2D with thick black outline, pure white round faces, single hard cel shading, thicker torso, stick limbs, flat matte colors; SCENE:"
3. After "SCENE:" describe the SPECIFIC action/scene from the script in vivid visual terms
4. Use concrete visual verbs: holds, points, gestures, leans, raises, clasps, runs, falls, celebrates, etc.
5. For abstract concepts: use icons (arrow↑ for growth, chart shape for data, coin icon for money, etc.)
6. End with: "{lang_note}"
7. Output ONLY the prompt — no explanation, no quotes, no numbering

STYLE REFERENCE:
{style_guide}

EXAMPLE:
Script: "주식 시장이 폭락할 때 오히려 매수 버튼을 누르죠"
Output: In the distinctive hand-drawn, loose ink-and-wash style of Quentin Blake, vintage children's book illustration; loose expressive scribbled ink lines, minimal transparent watercolor wash, pure white background, soft muted tones; SCENE: a confident man pressing a large button with a bold decisive gesture while chaotic figures around him panic and flail, expressive dynamic poses, ochre and pale blue wash; {lang_note}"""

    user_msg = f"""Convert this Korean script segment (cut {cut_index} of {total_cuts}) into an image prompt.

SCRIPT SEGMENT:
"{cut_text}"

Write ONE English image prompt that SPECIFICALLY shows what this script is about. The visual must clearly represent the content of this script."""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_msg,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.6,
            max_output_tokens=400,
        )
    )
    raw = response.text.strip().strip('"').strip("'")
    
    # 스타일 prefix가 빠진 경우 보완
    if not raw.lower().startswith("in the distinctive"):
        raw = f"In the distinctive hand-drawn, loose ink-and-wash style of Quentin Blake, vintage children's book illustration; loose expressive scribbled ink lines, minimal transparent watercolor wash, pure white background, soft muted tones; SCENE: {raw}; {lang_note}"
    
    return raw

def generate_image(client, prompt, language):
    """이미지 생성"""
    lang_note = LANGUAGE_SETTINGS[language]
    # 언어 지시와 스타일 강화를 프롬프트 끝에 추가
    full_prompt = f"{prompt}\n\nSTRICT REQUIREMENTS: Draw exactly what is described above. {lang_note}. Stick-man style ONLY."

    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=full_prompt,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
        )
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            data = part.inline_data.data
            if isinstance(data, str):
                data = base64.b64decode(data)
            return Image.open(io.BytesIO(data))
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

    st.markdown("### 🌐 이미지 언어")
    language = st.radio("이미지 내 텍스트 언어", options=["언어 없음","한국어","일본어","영어"], index=0)
    st.divider()

    st.markdown("### 🎨 스타일 가이드")
    style_guide = st.text_area("스타일 가이드 (편집 가능)", value=DEFAULT_STYLE_GUIDE, height=200)
    st.divider()

    st.markdown("### 📋 프롬프트 형식 (선택)")
    format_prompt = st.text_area("커스텀 형식 (비워두면 기본값)", placeholder="비워두면 기본 스틱맨 형식 사용", height=80)
    if not format_prompt.strip():
        format_prompt = DEFAULT_FORMAT_PROMPT

# 메인
st.markdown('<div class="main-header">🎬 스틱맨 이미지 생성기</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Powered by Gemini 2.5 Flash + Nano Banana 2 🍌</div>', unsafe_allow_html=True)

script = st.text_area(
    "📝 대본 입력",
    height=160,
    placeholder="여기에 대본을 붙여넣으세요...\n\n예) 부자들은 위기를 기회로 삼습니다.\n주식 시장이 폭락할 때 오히려 매수 버튼을 누르죠.",
)

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

    # ── STEP 1: 대본 분석 ──────────────────────────────────────
    with st.status("**1단계: 대본 분석 중...**", expanded=True) as s1:
        try:
            r = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"""아래 대본을 분석하고 한국어로 요약해주세요:
1. 전체 주제 (한 줄)
2. 핵심 메시지
3. 주요 장면/행동 키워드 (시각화에 중요한 것들)

대본:
{script}""",
                config=types.GenerateContentConfig(max_output_tokens=400, temperature=0.3)
            )
            st.session_state.analysis = r.text.strip()
            st.session_state.step = 1
            st.markdown(st.session_state.analysis)
            s1.update(label="✅ 1단계: 대본 분석 완료", state="complete")
        except Exception as e:
            s1.update(label=f"❌ 대본 분석 실패: {e}", state="error")
            st.stop()

    # ── STEP 2: 초단위 분할 ────────────────────────────────────
    with st.status("**2단계: 초단위 분할 중...**", expanded=True) as s2:
        cuts = split_script(script, seconds_per_cut)
        st.session_state.cuts = cuts
        st.session_state.step = 2
        st.write(f"📌 총 **{len(cuts)}개** 컷 (컷당 {seconds_per_cut}초 / 약 {chars_per_second(seconds_per_cut)}글자 기준)")
        for i, cut in enumerate(cuts):
            st.markdown(f"**컷 {i+1}** `{len(cut)}자` — {cut}")
        s2.update(label=f"✅ 2단계: {len(cuts)}개 컷으로 분할 완료", state="complete")

    # ── STEP 3: 프롬프트 생성 ──────────────────────────────────
    prompts = []
    with st.status("**3단계: 대본 → 이미지 프롬프트 변환 중...**", expanded=True) as s3:
        prog3 = st.progress(0)
        for i, cut in enumerate(cuts):
            st.write(f"🖊 컷 {i+1}/{len(cuts)}: `{cut[:30]}...` → 프롬프트 생성 중")
            try:
                p = build_image_prompt(
                    client, cut, style_guide, format_prompt, language, i+1, len(cuts)
                )
                prompts.append(p)
                # 프롬프트 미리보기 (SCENE: 이후만 보여줌)
                scene_part = p.split("SCENE:")[-1][:100] if "SCENE:" in p else p[:100]
                st.caption(f"→ SCENE: {scene_part}...")
            except Exception as e:
                fallback = f"In the distinctive hand-drawn, loose ink-and-wash style of Quentin Blake, vintage children's book illustration; loose expressive scribbled ink lines, minimal transparent watercolor wash, pure white background, soft muted tones; SCENE: expressive characters in a scene related to: {cut[:60]}; no text"
                prompts.append(fallback)
                st.session_state.errors.append(f"컷 {i+1} 프롬프트 오류: {e}")
            prog3.progress((i+1)/len(cuts))
            time.sleep(0.4)

        st.session_state.prompts = prompts
        st.session_state.step = 3
        s3.update(label=f"✅ 3단계: {len(prompts)}개 프롬프트 생성 완료", state="complete")

    # ── STEP 4: 이미지 생성 ────────────────────────────────────
    images = [None]*len(cuts)
    with st.status("**4단계: 이미지 생성 중 🍌...**", expanded=True) as s4:
        prog4 = st.progress(0)
        img_ph = st.empty()
        for i, (cut, prompt) in enumerate(zip(cuts, prompts)):
            st.write(f"🎨 컷 {i+1}/{len(cuts)} 이미지 생성 중...")
            try:
                img = generate_image(client, prompt, language)
                images[i] = img
                if img:
                    img_ph.image(img, caption=f"컷 {i+1}: {cut[:30]}...", width=320)
            except Exception as e:
                st.session_state.errors.append(f"컷 {i+1} 이미지 오류: {e}")
                st.warning(f"⚠️ 컷 {i+1} 실패: {e}")
            prog4.progress((i+1)/len(cuts))
            time.sleep(0.5)

        img_ph.empty()
        st.session_state.images = images
        st.session_state.step = 4
        ok = sum(1 for img in images if img is not None)
        s4.update(label=f"✅ 4단계: {ok}/{len(cuts)}개 이미지 생성 완료", state="complete")

    st.rerun()

# ── 결과 출력 ──────────────────────────────────────────────────
if st.session_state.step == 4 and st.session_state.cuts:
    st.markdown("---")
    st.markdown("## 🎉 생성 결과")

    if st.session_state.errors:
        with st.expander(f"⚠️ 오류 {len(st.session_state.errors)}건"):
            for err in st.session_state.errors:
                st.caption(err)

    cuts   = st.session_state.cuts
    prompts = st.session_state.prompts
    images  = st.session_state.images

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
                    st.download_button(
                        f"💾 컷{i+1} 저장", buf.getvalue(),
                        f"cut_{i+1:02d}.png", "image/png", key=f"dl_{i}"
                    )
                else:
                    st.warning("생성 실패")
                # 대본 내용 + 프롬프트 둘 다 보여줌
                st.caption(f"📝 대본: {cut}")
                if i < len(prompts):
                    with st.expander("🔍 생성된 프롬프트 보기"):
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
        st.download_button(
            "📦 전체 이미지 ZIP 다운로드",
            zip_buf.getvalue(), "stickman_cuts.zip",
            "application/zip", type="primary"
        )

if st.session_state.step == 0:
    st.markdown("---")
    st.info("👈 사이드바에서 설정 후, 대본을 입력하고 **🚀 이미지 생성 시작**을 눌러주세요.")
    with st.expander("📌 동작 방식"):
        st.markdown("""
**4단계 자동 파이프라인:**

1. **대본 분석** — Gemini가 전체 주제와 핵심 장면 키워드 파악
2. **초단위 분할** — 컷당 시간 기준(한국어 4.5자/초)으로 대본을 컷별로 나눔
3. **프롬프트 생성** — 각 컷의 내용을 스틱맨 스타일 영문 이미지 프롬프트로 변환
   - 대본 내용이 구체적으로 반영됨 (행동, 감정, 개념 → 시각적 묘사)
4. **이미지 생성** — 생성된 프롬프트로 실제 이미지 생성

**모델:**
- 🧠 프롬프트 생성: `gemini-2.5-flash`
- 🎨 이미지 생성: `gemini-3.1-flash-image-preview` (Nano Banana 2 🍌)
        """)
