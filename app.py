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

STYLE_PRESETS = {
    "🎨 퀜틴 블레이크 (따뜻한 수채화)": {
        "prefix": (
            "In the distinctive hand-drawn, loose ink-and-wash style of Quentin Blake, "
            "vintage children's book illustration. Loose expressive scribbled ink lines, "
            "minimal transparent watercolor wash, pure white background, soft muted tones "
            "(washed blues, pale greens, ochre, soft reds)."
        ),
        "mood": "warm, expressive, humanistic",
    },
    "📰 뉴스/시사 다큐 일러스트": {
        "prefix": (
            "Editorial news illustration style, bold graphic ink lines, high-contrast composition, "
            "dark dramatic shadows, strong visual metaphors, newspaper editorial art style. "
            "Flat bold colors — deep red, dark navy, stark white, charcoal black. "
            "Powerful and direct visual storytelling, no decorative elements."
        ),
        "mood": "dramatic, serious, impactful",
    },
    "🎭 극적인 흑백 잉크": {
        "prefix": (
            "Dramatic black-and-white ink illustration, bold brush strokes, high contrast, "
            "expressive figures with strong shadows and stark lighting. "
            "Political cartoon / graphic novel style. Pure white background, only black ink."
        ),
        "mood": "stark, powerful, cinematic",
    },
    "✏️ 심플 라인아트 (미니멀)": {
        "prefix": (
            "Simple clean line art illustration, minimal style, thin precise black outlines, "
            "flat pastel color fills, white background, modern editorial infographic aesthetic. "
            "Clear and direct visual communication."
        ),
        "mood": "clean, modern, clear",
    },
    "🖌️ 커스텀 (직접 입력)": {
        "prefix": "",
        "mood": "",
    },
}

DEFAULT_FORMAT_PROMPT = """In the distinctive hand-drawn, loose ink-and-wash style of Quentin Blake, vintage children's book illustration; loose expressive scribbled ink lines, minimal transparent watercolor wash, pure white background, soft muted tones (washed blues, pale greens, ochre, soft reds); SCENE: {scene_description}; no text, no letters."""

LANGUAGE_SETTINGS = {
    "언어 없음": "absolutely no text, no letters, no words, no numbers, no writing of any kind in the image",
    "한국어": "Korean text only allowed on signs or labels if necessary, minimal",
    "일본어": "Japanese text only allowed on signs or labels if necessary, minimal",
    "영어": "English text only allowed on signs or labels if necessary, minimal",
}

def chars_per_second(seconds):
    return round(seconds * 4.5)

def split_script_semantic(client, script, seconds_per_cut):
    """
    Gemini가 문장 의미 단위로 대본을 분할
    글자 수 기준이 아니라 내용/호흡/의미 흐름 기준
    """
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"""아래 대본을 이미지 한 컷에 어울리는 의미 단위로 분할해주세요.

분할 기준:
- 한 컷 = 약 {seconds_per_cut}초 분량 (한국어 기준 약 {chars_per_second(seconds_per_cut)}글자)
- 글자 수보다 **의미와 호흡**을 우선: 하나의 생각/장면/감정이 완결되는 지점에서 자르기
- 문장 중간에서 자르지 말 것
- 너무 짧은 컷(10글자 미만)은 앞뒤와 합치기
- 번호와 내용만 출력 (설명 없이)

출력 형식 (반드시 이 형식 준수):
1. [컷 내용]
2. [컷 내용]
3. [컷 내용]
...

대본:
{script}""",
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=1000,
        )
    )

    raw = response.text.strip()
    cuts = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        # "1. 내용" 또는 "1) 내용" 패턴 파싱
        match = re.match(r'^\d+[\.\)]\s*(.+)', line)
        if match:
            cut = match.group(1).strip()
            if cut:
                cuts.append(cut)

    # 파싱 실패 시 글자 수 기준으로 fallback
    if len(cuts) == 0:
        st.warning("의미 분할 실패 — 글자 수 기준으로 대체합니다.")
        cuts = split_script_fallback(script, seconds_per_cut)

    return cuts


def split_script_fallback(script, seconds_per_cut):
    """글자 수 기준 분할 (백업용)"""
    target = chars_per_second(seconds_per_cut)
    script = re.sub(r'\s+', ' ', script.strip())
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
    final_cuts = []
    for cut in cuts:
        while len(cut) > target * 1.5:
            final_cuts.append(cut[:target])
            cut = cut[target:]
        if cut:
            final_cuts.append(cut)
    return [c for c in final_cuts if c]

def build_image_prompt(client, cut_text, style_prefix, language, cut_index, total_cuts):
    """
    대본 → 이미지 프롬프트
    핵심: 대본의 구체적 키워드/상황을 반드시 시각화하도록 2단계 처리
    1단계: 대본에서 핵심 시각 요소 추출
    2단계: 추출된 요소로 구체적 장면 구성
    """
    lang_note = LANGUAGE_SETTINGS[language]

    system_instruction = """You are a professional visual scene analyst and image prompt writer.

YOUR TASK: Convert a Korean script segment into a precise English visual scene description.

STRICT PROCESS (follow both steps):

STEP 1 — Extract from the script:
- WHO: specific people/entities mentioned (e.g., China, terrorist, victims, politician)
- WHAT: the core action or event happening
- KEY OBJECTS: specific items, symbols, money amounts, maps, flags, weapons, documents
- EMOTION/TONE: fear, anger, grief, irony, shock, triumph

STEP 2 — Build a visual scene using those elements:
- Place the extracted WHO doing the extracted WHAT
- Include KEY OBJECTS as visual symbols (e.g., "a giant pile of gold coins labeled ¥90T", "a target/crosshair symbol", "a map of Afghanistan")
- Show the EMOTION through poses and expressions
- Be SPECIFIC — not "people mourning" but "a crowd of diverse figures standing in shocked silence, hands over mouths"
- Keep under 80 words

OUTPUT: Only the scene description (no style words, no "SCENE:", no explanation)

CRITICAL: The output MUST visually represent the SPECIFIC content of the script.
If the script mentions China → show Chinese symbols/figures
If the script mentions money → show coins, bills, specific amounts as visual icons
If the script mentions terror/attack → show dramatic impact, not gentle sadness"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"""Script segment (cut {cut_index}/{total_cuts}):
"{cut_text}"

Extract the key visual elements and describe the scene:""",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.4,
            max_output_tokens=200,
        )
    )
    scene_description = response.text.strip().strip('"').strip("'")

    # 스타일 prefix + 장면 조합
    full_prompt = f"{style_prefix} SCENE: {scene_description}. {lang_note}."
    return full_prompt, scene_description


def generate_image(client, prompt, cut_text, language):
    """
    이미지 생성 — 프롬프트 + 원본 대본을 함께 넘겨서 내용 일치율 높임
    """
    lang_note = LANGUAGE_SETTINGS[language]

    # 이미지 모델에게: 프롬프트 + 원본 대본 내용을 같이 전달
    final_prompt = (
        f"{prompt}\n\n"
        f"IMPORTANT: The image must visually represent this specific content: '{cut_text}'\n"
        f"Draw exactly the scene described. {lang_note}."
    )

    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=final_prompt,
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
for key, default in [("cuts",[]),("prompts",[]),("scenes",[]),("images",[]),("step",0),("analysis",""),("errors",[])]:
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
    st.caption(f"컷당 목표 **{seconds_per_cut}초** 기준으로 의미 단위 분할합니다.")
    st.divider()

    st.markdown("### 🌐 이미지 언어")
    language = st.radio("이미지 내 텍스트 언어", options=["언어 없음","한국어","일본어","영어"], index=0)
    st.divider()

    st.markdown("### 🎨 이미지 스타일")
    selected_style = st.selectbox(
        "스타일 선택",
        options=list(STYLE_PRESETS.keys()),
        index=0,
        help="대본 분위기에 맞는 스타일을 선택하세요."
    )
    st.caption(f"분위기: *{STYLE_PRESETS[selected_style]['mood']}*")

    if selected_style == "🖌️ 커스텀 (직접 입력)":
        custom_style = st.text_area("커스텀 스타일 프롬프트", value=DEFAULT_STYLE_GUIDE, height=160)
        style_prefix = custom_style
    else:
        style_prefix = STYLE_PRESETS[selected_style]["prefix"]
        with st.expander("스타일 프롬프트 보기"):
            st.caption(style_prefix)
    st.divider()

    st.markdown("### 📋 추가 스타일 지시 (선택)")
    extra_style = st.text_area("추가 지시사항 (비워두면 기본값)", placeholder="예: 배경을 어둡게, 인물을 크게 등", height=60)
    if extra_style.strip():
        style_prefix = style_prefix + " " + extra_style.strip()

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
    for k in ["cuts","prompts","scenes","images","errors"]:
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

    # ── STEP 2: 의미 단위 분할 ─────────────────────────────────
    with st.status("**2단계: 의미 단위 분할 중...**", expanded=True) as s2:
        cuts = split_script_semantic(client, script, seconds_per_cut)
        st.session_state.cuts = cuts
        st.session_state.step = 2
        st.write(f"📌 총 **{len(cuts)}개** 컷 (컷당 목표 {seconds_per_cut}초 / 의미 단위 기준)")
        for i, cut in enumerate(cuts):
            st.markdown(f"**컷 {i+1}** `{len(cut)}자` — {cut}")
        s2.update(label=f"✅ 2단계: {len(cuts)}개 컷으로 분할 완료", state="complete")

    # ── STEP 3: 프롬프트 생성 ──────────────────────────────────
    prompts = []
    scenes = []
    with st.status("**3단계: 대본 → 이미지 프롬프트 변환 중...**", expanded=True) as s3:
        prog3 = st.progress(0)
        for i, cut in enumerate(cuts):
            st.write(f"🖊 컷 {i+1}/{len(cuts)}: `{cut[:25]}...` → 장면 분석 중")
            try:
                prompt, scene = build_image_prompt(
                    client, cut, style_prefix, language, i+1, len(cuts)
                )
                prompts.append(prompt)
                scenes.append(scene)
                st.caption(f"→ 장면: {scene[:80]}...")
            except Exception as e:
                scene = f"expressive characters in a scene related to: {cut[:60]}"
                fallback = f"{style_prefix} SCENE: {scene}. {LANGUAGE_SETTINGS[language]}."
                prompts.append(fallback)
                scenes.append(scene)
                st.session_state.errors.append(f"컷 {i+1} 프롬프트 오류: {e}")
            prog3.progress((i+1)/len(cuts))
            time.sleep(0.4)

        st.session_state.prompts = prompts
        st.session_state.scenes = scenes
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
                img = generate_image(client, prompt, cut, language)
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

    cuts    = st.session_state.cuts
    prompts = st.session_state.prompts
    scenes  = st.session_state.get("scenes", [""] * len(cuts))
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
                # 대본 원문
                st.caption(f"📝 대본: {cut}")
                # 장면 해석 (중간 단계 투명하게 보여줌)
                if i < len(scenes) and scenes[i]:
                    with st.expander("🎬 장면 해석 보기"):
                        st.write(scenes[i])
                # 전체 프롬프트
                if i < len(prompts):
                    with st.expander("🔍 전체 프롬프트 보기"):
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

        col_zip, col_save = st.columns([1, 1])
        with col_zip:
            st.download_button(
                "📦 전체 이미지 ZIP 다운로드",
                zip_buf.getvalue(), "stickman_cuts.zip",
                "application/zip", type="primary"
            )
        with col_save:
            # 라이브러리에 저장할 데이터 준비 (이미지는 base64로 직렬화)
            import base64 as b64mod, json, datetime
            save_title = st.text_input("저장 제목", value=script[:20].strip() + "...", key="save_title")
            if st.button("📚 라이브러리에 저장", type="secondary"):
                items = []
                for i, (cut, img) in enumerate(zip(cuts, images)):
                    img_b64 = ""
                    if img is not None:
                        buf2 = io.BytesIO()
                        img.save(buf2, format="PNG")
                        img_b64 = b64mod.b64encode(buf2.getvalue()).decode()
                    items.append({"cut": cut, "img": img_b64, "scene": scenes[i] if i < len(scenes) else ""})

                entry = {
                    "id": str(int(datetime.datetime.now().timestamp() * 1000)),
                    "title": save_title,
                    "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "expire": (datetime.datetime.now() + datetime.timedelta(days=2)).timestamp(),
                    "items": items,
                }
                # JS로 localStorage에 저장
                entry_json = json.dumps(entry, ensure_ascii=False)
                st.components.v1.html(f"""
<script>
(function() {{
    var key = 'imggen_library';
    var existing = JSON.parse(localStorage.getItem(key) || '[]');
    // 만료된 항목 제거
    var now = Date.now() / 1000;
    existing = existing.filter(function(e) {{ return e.expire > now; }});
    existing.unshift({entry_json});
    localStorage.setItem(key, JSON.stringify(existing));
    // 저장 완료 알림
    var msg = document.createElement('div');
    msg.style.cssText = 'background:#d4edda;color:#155724;padding:12px 18px;border-radius:8px;font-weight:600;font-size:14px;';
    msg.textContent = '✅ 라이브러리에 저장됐습니다! (48시간 후 자동 삭제)';
    document.body.appendChild(msg);
    setTimeout(function() {{ msg.remove(); }}, 3000);
}})();
</script>
""", height=50)
                st.success("✅ 라이브러리에 저장됐습니다! 아래 📚 라이브러리 탭에서 확인하세요.")

# ── 라이브러리 ──────────────────────────────────────────────────
st.markdown("---")
st.markdown("## 📚 라이브러리")
st.caption("저장된 작업물이 여기 표시됩니다. 48시간 후 자동 삭제됩니다.")

# localStorage에서 라이브러리 불러오기 + 표시
import streamlit.components.v1 as components
import json

# JS → Python 통신: localStorage 데이터를 query param으로 넘기는 방식
library_html = """
<style>
  body { font-family: sans-serif; margin: 0; background: transparent; }
  .lib-empty { color: #999; font-size: 13px; padding: 8px 0; }
  .lib-item {
    border: 1px solid #e0e0e0; border-radius: 10px;
    padding: 12px 16px; margin-bottom: 10px;
    background: #fafafa; cursor: pointer;
  }
  .lib-item:hover { background: #f0f4ff; border-color: #aac; }
  .lib-title { font-weight: 600; font-size: 14px; color: #333; }
  .lib-meta  { font-size: 12px; color: #888; margin-top: 2px; }
  .lib-del   { float: right; background: none; border: none;
               color: #cc4444; cursor: pointer; font-size: 13px; }
  .lib-imgs  { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .lib-imgs img { width: 90px; height: 90px; object-fit: cover;
                  border-radius: 6px; border: 1px solid #ddd; }
  .lib-cut   { font-size: 11px; color: #555; text-align: center;
               width: 90px; overflow: hidden; white-space: nowrap;
               text-overflow: ellipsis; }
  .expanded  { background: #f0f4ff !important; }
</style>

<div id="library"></div>

<script>
(function() {
  var key = 'imggen_library';
  var container = document.getElementById('library');

  function render() {
    var raw = localStorage.getItem(key) || '[]';
    var items;
    try { items = JSON.parse(raw); } catch(e) { items = []; }
    // 만료 제거
    var now = Date.now() / 1000;
    items = items.filter(function(e) { return e.expire > now; });
    localStorage.setItem(key, JSON.stringify(items));

    container.innerHTML = '';
    if (items.length === 0) {
      container.innerHTML = '<div class="lib-empty">저장된 항목이 없습니다.<br>생성 후 "📚 라이브러리에 저장" 버튼을 눌러주세요.</div>';
      return;
    }

    items.forEach(function(entry, idx) {
      var card = document.createElement('div');
      card.className = 'lib-item';
      var expire = new Date(entry.expire * 1000);
      var expireStr = expire.getMonth()+1 + '/' + expire.getDate() + ' ' + expire.getHours() + ':' + String(expire.getMinutes()).padStart(2,'0') + ' 까지';
      var cutCount = (entry.items || []).length;

      card.innerHTML =
        '<button class="lib-del" data-idx="' + idx + '">🗑 삭제</button>' +
        '<div class="lib-title">' + escHtml(entry.title) + '</div>' +
        '<div class="lib-meta">' + entry.date + ' · ' + cutCount + '컷 · ⏳ ' + expireStr + '</div>';

      // 이미지 미리보기 (처음에는 숨김)
      var imgArea = document.createElement('div');
      imgArea.className = 'lib-imgs';
      imgArea.style.display = 'none';
      (entry.items || []).forEach(function(item) {
        var wrap = document.createElement('div');
        if (item.img) {
          var img = document.createElement('img');
          img.src = 'data:image/png;base64,' + item.img;
          wrap.appendChild(img);
        }
        var cap = document.createElement('div');
        cap.className = 'lib-cut';
        cap.textContent = item.cut;
        wrap.appendChild(cap);
        imgArea.appendChild(wrap);
      });
      card.appendChild(imgArea);

      // 클릭 시 펼치기/접기
      card.addEventListener('click', function(e) {
        if (e.target.classList.contains('lib-del')) return;
        var visible = imgArea.style.display !== 'none';
        imgArea.style.display = visible ? 'none' : 'flex';
        card.classList.toggle('expanded', !visible);
      });

      // 삭제 버튼
      card.querySelector('.lib-del').addEventListener('click', function(e) {
        e.stopPropagation();
        var i = parseInt(this.getAttribute('data-idx'));
        var current = JSON.parse(localStorage.getItem(key) || '[]');
        current.splice(i, 1);
        localStorage.setItem(key, JSON.stringify(current));
        render();
      });

      container.appendChild(card);
    });
  }

  function escHtml(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  render();
})();
</script>
"""

components.html(library_html, height=420, scrolling=True)


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
