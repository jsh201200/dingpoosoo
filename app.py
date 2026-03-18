import streamlit as st
from google import genai
from google.genai import types
import base64, io, re, time, json, datetime, zipfile
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── 페이지 설정 ────────────────────────────────────────────────
st.set_page_config(page_title="비전 메이커", page_icon="🎬", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
  [data-testid="stSidebar"] { min-width:260px; max-width:280px; }
  .block-container { padding-top:1.2rem; padding-bottom:1rem; }
  .scene-card { border:1px solid #e0e0e0; border-radius:12px; padding:0; overflow:hidden; margin-bottom:16px; background:#fff; }
  .scene-header { background:#f8f9fa; padding:8px 14px; font-size:0.78rem; font-weight:600; color:#555; border-bottom:1px solid #e0e0e0; display:flex; justify-content:space-between; }
  .scene-script { padding:10px 14px; font-size:0.88rem; color:#333; line-height:1.5; background:#fff; }
  .intro-badge { display:inline-block; background:#fff3cd; color:#856404; border-radius:10px; padding:2px 8px; font-size:0.72rem; font-weight:600; }
  .body-badge  { display:inline-block; background:#d1ecf1; color:#0c5460; border-radius:10px; padding:2px 8px; font-size:0.72rem; font-weight:600; }
  .status-done { color:#28a745; font-size:0.78rem; }
  div[data-testid="stVerticalBlock"] > div { gap:0.3rem; }
</style>
""", unsafe_allow_html=True)

# ── 스타일 프리셋 ──────────────────────────────────────────────
STYLE_PRESETS = {
    "🐿️ Pixar/Disney 3D": (
        "Pixar and Disney CGI animation style, high-quality 3D render with warm cinematic studio lighting. "
        "Expressive anthropomorphic animal character as the focal point — large soulful eyes, soft detailed fur texture, "
        "fluid body proportions with oversized head for expressiveness. "
        "Outfit and accessories are context-appropriate and richly detailed (fabric folds, buttons, badges). "
        "Background is a fully realized, stylized 3D environment with depth layers: foreground props, midground activity, "
        "blurred background establishing location. "
        "Cinematic depth of field, vibrant saturated colors with rim lighting. "
        "Any Korean or English text in the scene (signs, screens, banners, news tickers, charts) must be sharply rendered, "
        "legible, correctly spelled, and naturally integrated into the environment. "
        "Overall feel: Zootopia meets a Korean news studio — polished, warm, emotionally engaging."
    ),
    "📰 뉴스/시사 다큐": (
        "Editorial illustration in the hand-drawn ink-and-wash style of Quentin Blake with aggressive news urgency. "
        "Loose, expressive, scribbled ink line work — thick where dramatic, thin where delicate. "
        "High-contrast composition: stark white areas slammed against deep charcoal black shadows. "
        "Minimal transparent watercolor wash — dominant palette of washed deep crimson red, cold navy blue, "
        "and urgent ochre yellow, applied loosely over ink lines with deliberate bleed and texture. "
        "Any Korean or English text (속보, 긴급, headlines, location labels, statistics) must appear as "
        "bold hand-lettered or stenciled text, dramatically integrated into the composition — "
        "on banners, chalkboards, torn paper, or broadcast lower-thirds. "
        "Characters show exaggerated emotion through body language: hunched shoulders for defeat, "
        "raised fist for defiance, wide-eyed paralysis for shock. "
        "Background has editorial depth: maps, data charts, silhouetted crowds, architectural outlines. "
        "Raw, unfinished, powerful — like a breaking news illustration drawn under deadline pressure."
    ),
    "😊 실사 다큐 포토": (
        "National Geographic and Reuters photojournalism aesthetic — cinematic documentary photography style. "
        "The main subject is an anthropomorphic animal character rendered with extreme photorealistic detail: "
        "individual fur strands, skin texture around eyes and nose, realistic light refraction in the eyes. "
        "Shallow depth of field — subject sharp, background beautifully blurred with environmental storytelling. "
        "Lighting is volumetric and natural: golden-hour warmth, cold blue office fluorescence, "
        "or dramatic single-source spotlight depending on scene emotion. "
        "The background is a fully detailed real-world environment (newsroom, protest street, courtroom, market) "
        "with authentic props, people, and atmosphere. "
        "Any Korean or English text visible in the scene (news monitors, protest signs, building signage, "
        "document text, TV chyrons) must be photographically realistic, correctly spelled, "
        "and naturally lit as if actually present in the environment. "
        "Shot on Canon EOS R5, 85mm f/1.4 lens, RAW format, 8K resolution. "
        "Color grading: cinematic LUT — slightly desaturated midtones, lifted shadows, cool highlights. "
        "Masterpiece quality — the kind of image that wins a World Press Photo award."
    ),
    "🎨 퀜틴 블레이크 수채화": (
        "Quintessential Quentin Blake hand-drawn illustration — loose, joyful, humanistic. "
        "Scribbled expressive black ink lines with deliberate imperfection and energy. "
        "Layered transparent watercolor washes with natural bleeding at edges: "
        "dominant palette of warm washed blues, soft pale greens, golden ochre, dusty rose, and gentle soft reds. "
        "Pure white background preserved in key areas to create luminosity and airiness. "
        "Characters are drawn with elastic, exaggerated proportions — rubbery limbs, tilted heads, "
        "enormous expressive eyes communicating complex emotion in a single glance. "
        "Backgrounds are suggested rather than fully rendered: loose architectural lines, "
        "a few gestural strokes establishing location without overpowering the character. "
        "Any Korean or English text in the image should appear as hand-lettered script "
        "organically woven into the illustration — on books, signs, banners, or notes — "
        "in the same loose ink style as the rest of the artwork. "
        "Overall warmth: the kind of illustration that makes adults feel like children again."
    ),
    "🎭 흑백 드라마 잉크": (
        "Stark, powerful black-and-white ink illustration — political cartoon meets graphic novel gravitas. "
        "Bold, deliberate brush strokes with dramatic variation: razor-thin lines for detail, "
        "thick slashing strokes for impact and shadow. "
        "Chiaroscuro lighting — deep pools of black shadow with sharp white highlights, "
        "zero mid-tones, maximum emotional contrast. "
        "Composition is cinematic and theatrical: strong diagonals, extreme close-ups, "
        "dutch angles, silhouettes against harsh white. "
        "Characters are drawn with anatomical exaggeration for emotional effect — "
        "hunched villains, towering heroes, crumbling figures in despair. "
        "Background elements are bold graphic shapes: city skylines reduced to black geometry, "
        "crowds as waves of silhouettes, institutions as imposing fortress lines. "
        "Any Korean or English text must appear as bold, high-contrast block lettering or "
        "stenciled type integrated into the image — urgent, unmissable, graphically powerful. "
        "Zero color. Only black ink on white. Like a protest poster designed by a master printmaker."
    ),
    "✏️ 모던 인포그래픽": (
        "Clean, sophisticated modern editorial illustration — information design meets fine art. "
        "Precise, consistent line weight throughout: thin 1pt outlines on all elements, "
        "no hand-drawn variation, purely geometric precision. "
        "Flat color fills only — curated palette of 4-5 colors maximum: "
        "one dominant neutral (off-white or light gray), two accent colors, one dark anchor color. "
        "Layout follows clear visual hierarchy: main character/subject large and centered, "
        "supporting elements organized in clear spatial zones. "
        "Data visualization elements (charts, graphs, timelines, flow diagrams, maps, percentages) "
        "are sharply rendered as crisp graphic elements integral to the composition. "
        "Any Korean or English text — labels, statistics, headlines, captions, UI elements — "
        "must be typographically clean, correctly spelled, appropriately sized, "
        "and designed as a core compositional element rather than an afterthought. "
        "White background with generous negative space. "
        "Overall aesthetic: the cover of a prestigious Korean economics magazine — "
        "intelligent, clear, visually elegant."
    ),
    "🖌️ 커스텀": "",
}


LANGUAGE_SETTINGS = {
    "언어 없음": "absolutely no text, no letters, no words, no numbers anywhere in the image",
    "한국어": "Korean text allowed on signs or labels, minimal",
    "일본어": "Japanese text allowed on signs or labels, minimal",
    "영어": "English text allowed on signs or labels, minimal",
}

# ── 세션 초기화 ────────────────────────────────────────────────
for k, v in [("cuts",[]),("sections",[]),("styles",[]),("prompts",[]),
             ("scenes",[]),("images",[]),("step",0),("errors",[]),
             ("regen_idx",None)]:
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════════
# 헬퍼 함수들
# ══════════════════════════════════════════════════════════════

def chars_per_second(s): return round(s * 4.5)

def split_semantic(client, script, seconds):
    """대본을 의미 단위로 분할. 긴 대본은 문장 단위로 청크 분할 후 합침."""
    chars = chars_per_second(seconds)
    est = max(3, round(len(script) / chars))

    # 대본이 길면 (예상 컷 15개 초과) 청크로 나눠서 각각 분할 후 합침
    if est > 15:
        # 문장 단위로 분리
        sentences = re.split(r'(?<=[.!?。])\s+', script.strip())
        # 청크당 약 10컷 분량으로 묶기
        chunk_size_chars = chars * 10
        chunks, current_chunk = [], ""
        for sent in sentences:
            if len(current_chunk) + len(sent) < chunk_size_chars:
                current_chunk += (" " if current_chunk else "") + sent
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sent
        if current_chunk:
            chunks.append(current_chunk)

        all_cuts = []
        for chunk in chunks:
            all_cuts.extend(_split_single(client, chunk, seconds))
        return all_cuts if all_cuts else [script]

    return _split_single(client, script, seconds)


def _split_single(client, script, seconds):
    """단일 청크를 Gemini로 분할."""
    chars = chars_per_second(seconds)
    est = max(3, round(len(script) / chars))
    r = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"""아래 대본을 이미지 컷 단위로 빠짐없이 분할하세요.

규칙:
- 한 컷 = 약 {seconds}초 = 약 {chars}글자
- 예상 컷 수: 약 {est}개 — 반드시 이 숫자에 맞게 분할할 것
- 대본의 처음부터 끝까지 단 한 글자도 빠뜨리지 말 것
- 각 문장/절은 별도 컷으로 — 여러 문장을 하나로 뭉치지 말 것
- 문장 중간에서 자르지 말 것 (마침표/느낌표/물음표 단위)
- 5글자 미만만 앞뒤와 합치기
- 번호. 내용 형식으로만 출력 (설명, 주석 없이)

출력:
1. [내용]
2. [내용]
...

대본 (처음부터 끝까지 전부 분할):
{script}""",
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=3000)
    )
    cuts = []
    for line in r.text.strip().split("\n"):
        m = re.match(r'^\d+[\.\)]\s*(.+)', line.strip())
        if m and m.group(1).strip():
            cuts.append(m.group(1).strip())
    if not cuts:
        cuts = [l.strip() for l in script.split("\n") if l.strip()]
    return cuts

def build_prompt(client, cut, style_prefix, character_b64, language, idx, total):
    lang = LANGUAGE_SETTINGS[language]

    # 캐릭터 있을 때 / 없을 때 시스템 지시 분기
    char_section = ""
    if character_b64:
        char_section = """
CHARACTER RULES (CRITICAL):
- The main character is from the reference image provided
- Keep species, face shape, fur color/texture, and overall body type IDENTICAL
- BUT adapt per scene:
  * EXPRESSION: match the emotion (shocked face, confident smirk, wide eyes in fear, laughing, crying, frowning, etc.)
  * OUTFIT: change to fit the scene context (formal suit, casual, military, torn clothes, etc.)
  * POSE/ACTION: dynamic and specific to the scene action
- Character must be the focal point and clearly doing something relevant to the script"""

    sys = f"""You are an expert cinematic image prompt writer for AI image generation.
Convert a Korean script segment into a detailed English image prompt.

{char_section}

SCENE ANALYSIS PROCESS:
1. WHO: specific entities (character, crowds, officials, etc.)
2. WHAT: the core action happening RIGHT NOW in this frame
3. KEY VISUAL OBJECTS: specific props, symbols, text overlays, icons, maps, charts, money stacks, flags
4. EMOTION/ATMOSPHERE: what should the viewer FEEL looking at this image
5. CAMERA/COMPOSITION: close-up, wide shot, dramatic angle, etc.

OUTPUT FORMAT — write a single detailed English paragraph covering:
- Main character's expression + pose + outfit
- Specific action happening
- Key objects and symbols in the scene
- Background/setting details
- Lighting and mood
- Any text/labels that should appear IN the image (e.g. "속보:", chart labels, location names)

QUALITY STANDARDS (match professional editorial illustration):
- Be HYPER-SPECIFIC: not "a sad character" but "character with trembling lower lip, eyes wide with shock, hands clutching chest"
- Include CINEMATIC details: dramatic backlighting, depth, foreground elements
- Specify TEXT OVERLAYS when relevant to the news/story content
- Maximum 120 words. Output the scene description ONLY."""

    r = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f'Script segment {idx}/{total}:\n"{cut}"\n\nWrite the detailed image prompt:',
        config=types.GenerateContentConfig(system_instruction=sys, temperature=0.45, max_output_tokens=250)
    )
    scene = r.text.strip().strip('"').strip("'")

    # 스타일 + 캐릭터 지시 + 장면 조합
    char_note = "Use the reference character image provided as the main character. Adapt expression, outfit, and pose to match the scene, but keep the character's core design identical. " if character_b64 else ""
    full = f"{style_prefix} {char_note}SCENE: {scene}. {lang}."
    return full, scene


def generate_image(client, prompt, cut, character_b64, language, aspect_ratio="1:1"):
    lang = LANGUAGE_SETTINGS[language]

    ratio_instruction = {
        "16:9": "Generate this as a WIDE LANDSCAPE image (16:9 aspect ratio, horizontal composition, cinematic widescreen format).",
        "1:1":  "Generate this as a SQUARE image (1:1 aspect ratio, balanced centered composition).",
        "9:16": "Generate this as a TALL PORTRAIT image (9:16 aspect ratio, vertical composition optimized for mobile/shorts).",
    }.get(aspect_ratio, "")

    final = (
        f"{prompt}\n\n"
        f"ADDITIONAL REQUIREMENTS:\n"
        f"- {ratio_instruction}\n"
        f"- Draw the EXACT scene described with high detail and cinematic quality\n"
        f"- The scene must clearly represent: '{cut[:80]}'\n"
        f"- Include rich background details, dramatic lighting, and expressive characters\n"
        f"- {lang}"
    )

    if character_b64:
        contents = [
            types.Content(role="user", parts=[
                types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=base64.b64decode(character_b64))),
                types.Part(text=(
                    f"This is the reference character. Generate an image using this character as the main character, "
                    f"adapting their expression, outfit, and pose to match the scene, "
                    f"but keeping their species, face, and core design identical.\n\n{final}"
                ))
            ])
        ]
        response = client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=contents,
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"])
        )
    else:
        response = client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=final,
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"])
        )

    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            data = part.inline_data.data
            if isinstance(data, str):
                data = base64.b64decode(data)
            return Image.open(io.BytesIO(data))
    return None

def regen_single(client, i, style_prefix, character_b64, language, aspect_ratio="1:1"):
    cut = st.session_state.cuts[i]
    try:
        p, sc = build_prompt(client, cut, style_prefix, character_b64, language, i+1, len(st.session_state.cuts))
        img = generate_image(client, p, cut, character_b64, language, aspect_ratio)
        st.session_state.prompts[i] = p
        st.session_state.scenes[i]  = sc
        st.session_state.images[i]  = img
    except Exception as e:
        st.session_state.errors.append(f"컷{i+1} 재생성 오류: {e}")

# ══════════════════════════════════════════════════════════════
# 사이드바
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🎬 비전 메이커")

    # API 키
    st.markdown("### 🔑 API 키")
    api_key = st.text_input("Gemini API Key", type="password", placeholder="AIza...", label_visibility="collapsed")
    if api_key: st.success("✓ 연결됨", icon="✅")
    st.divider()

    # 캐릭터 일관성
    st.markdown("### 🐾 캐릭터 일관성")
    st.caption("업로드하면 모든 씬에 같은 캐릭터가 등장합니다.\n표정·행동·옷차림은 장면에 맞게 자동 변경됩니다.")
    char_file = st.file_uploader("캐릭터 참조 이미지", type=["png","jpg","jpeg"],
                                  label_visibility="collapsed")
    character_b64 = None
    if char_file:
        img_bytes = char_file.read()
        character_b64 = base64.b64encode(img_bytes).decode()
        st.image(img_bytes, width=160, caption="✅ 캐릭터 등록됨")
        st.caption("😊 슬픔 / 😤 분노 / 😲 충격 / 😄 기쁨 등 상황별 표정 자동 적용")
    else:
        st.caption("미업로드 시 스타일 프롬프트 기반으로 생성됩니다.")
    st.divider()

    # 분할 설정
    st.markdown("### ⏱ 분할 설정")
    st.markdown("**🎬 인트로**")
    intro_seconds = st.slider("인트로 컷 시간", 4, 6, 4, step=1,
                               format="%d초", help="4~6초 고정, 빠른 호흡")
    st.caption(f"약 {chars_per_second(intro_seconds)}글자 단위")

    st.markdown("**📖 본문**")
    body_seconds = st.select_slider("본문 컷 시간", options=[20,25,30,35,40], value=20,
                                     format_func=lambda x: f"{x}초")
    st.caption(f"약 {chars_per_second(body_seconds)}글자 단위")
    st.divider()

    # 스타일
    st.markdown("### 🎨 비주얼 스타일")
    style_name = st.selectbox("스타일 선택", list(STYLE_PRESETS.keys()), index=0, label_visibility="collapsed")
    if style_name == "🖌️ 커스텀":
        style_prefix = st.text_area("커스텀 스타일", height=80, placeholder="스타일 프롬프트 입력...")
    else:
        style_prefix = STYLE_PRESETS[style_name]

    extra = st.text_area("추가 특징 (선택)", height=60, placeholder="예: 항상 포근, 주머니에 손...")
    if extra.strip(): style_prefix = style_prefix + " " + extra.strip()
    st.divider()

    # 출력 언어
    st.markdown("### 🌐 출력 언어")
    language = st.selectbox("언어", list(LANGUAGE_SETTINGS.keys()), label_visibility="collapsed")
    st.divider()

    # 이미지 사이즈
    st.markdown("### 📐 이미지 비율")
    aspect_ratio = st.radio(
        "비율 선택",
        options=["16:9", "1:1", "9:16"],
        index=1,
        horizontal=True,
        label_visibility="collapsed",
        help="16:9 유튜브 썸네일 · 1:1 SNS · 9:16 쇼츠/릴스"
    )
    ratio_labels = {"16:9": "🖥 유튜브 썸네일", "1:1": "📷 SNS 정방형", "9:16": "📱 쇼츠/릴스"}
    st.caption(ratio_labels[aspect_ratio])
    st.divider()

    # 병렬 작업
    st.markdown("### ⚡ 병렬 작업")
    parallel_workers = st.slider("동시 작업 수", 1, 8, 4, step=1, label_visibility="collapsed")
    st.caption(f"{parallel_workers}개 동시 생성")

# ══════════════════════════════════════════════════════════════
# 메인 영역
# ══════════════════════════════════════════════════════════════
col_title, col_btn1, col_btn2 = st.columns([4, 1.2, 1.2])
with col_title:
    st.markdown("## 비전 메이커 **v1.0**")
    st.caption("스크립트를 고품질 AI 비주얼 프로덕션으로 즉시 전환하세요.")
with col_btn1:
    split_only_btn = st.button("✂️ 장면 분할", use_container_width=True)
with col_btn2:
    gen_btn = st.button("⚡ 일괄 생성", type="primary", use_container_width=True)

st.markdown("---")

# 입력 영역 — 인트로 / 본문 2칸
col_intro, col_body = st.columns(2)
with col_intro:
    st.markdown(f"**🎬 인트로 스크립트**")
    intro_script = st.text_area(
        "intro", label_visibility="collapsed", height=160,
        placeholder="강렬한 도입부 스크립트를 여기에 붙여넣으세요...",
        key="intro_input"
    )
    st.caption(f"⏱ 인트로 분할: {intro_seconds}s")

with col_body:
    st.markdown(f"**📖 메인 본문 스크립트**")
    body_script = st.text_area(
        "body", label_visibility="collapsed", height=160,
        placeholder="본문 내용을 여기에 입력하세요...",
        key="body_input"
    )
    st.caption(f"⏱ 본문은 설정된 시간({body_seconds}s) 기준에 따라 분할됩니다.")

# 프로젝트 제목
project_title = st.text_input("프로젝트 통합 제목", placeholder="예: 삼성전자의 차세대 EV 배터리 전략 분석",
                               label_visibility="visible")

# ══════════════════════════════════════════════════════════════
# 장면 분할만 (미리보기)
# ══════════════════════════════════════════════════════════════
if split_only_btn:
    if not api_key:
        st.error("API 키를 입력해주세요.")
        st.stop()
    if not intro_script.strip() and not body_script.strip():
        st.error("스크립트를 입력해주세요.")
        st.stop()

    client = genai.Client(api_key=api_key)
    all_cuts, all_sections = [], []

    with st.spinner("장면 분할 중..."):
        if intro_script.strip():
            ic = split_semantic(client, intro_script.strip(), intro_seconds)
            all_cuts += ic; all_sections += ["intro"] * len(ic)
        if body_script.strip():
            bc = split_semantic(client, body_script.strip(), body_seconds)
            all_cuts += bc; all_sections += ["body"] * len(bc)

    st.session_state.cuts = all_cuts
    st.session_state.sections = all_sections
    st.session_state.prompts  = [None]*len(all_cuts)
    st.session_state.scenes   = [None]*len(all_cuts)
    st.session_state.images   = [None]*len(all_cuts)
    st.session_state.styles   = [style_prefix]*len(all_cuts)
    st.session_state.step = 1
    st.rerun()

# ══════════════════════════════════════════════════════════════
# 일괄 생성
# ══════════════════════════════════════════════════════════════
if gen_btn:
    if not api_key:
        st.error("API 키를 입력해주세요.")
        st.stop()
    if not intro_script.strip() and not body_script.strip():
        st.error("스크립트를 입력해주세요.")
        st.stop()

    client = genai.Client(api_key=api_key)
    st.session_state.errors = []

    # 분할
    all_cuts, all_sections = [], []
    with st.spinner("✂️ 장면 분할 중..."):
        if intro_script.strip():
            ic = split_semantic(client, intro_script.strip(), intro_seconds)
            all_cuts += ic; all_sections += ["intro"] * len(ic)
        if body_script.strip():
            bc = split_semantic(client, body_script.strip(), body_seconds)
            all_cuts += bc; all_sections += ["body"] * len(bc)

    n = len(all_cuts)
    st.session_state.cuts     = all_cuts
    st.session_state.sections = all_sections
    st.session_state.prompts  = [None]*n
    st.session_state.scenes   = [None]*n
    st.session_state.images   = [None]*n
    st.session_state.styles   = [style_prefix]*n
    st.session_state.step     = 2

    # 병렬 프롬프트 생성
    prompts_out = [None]*n
    scenes_out  = [None]*n
    prog = st.progress(0, text="📝 프롬프트 생성 중...")

    def _make_prompt(args):
        i, cut = args
        try:
            p, sc = build_prompt(client, cut, style_prefix, character_b64, language, i+1, n)
            return i, p, sc, None
        except Exception as e:
            sc = cut[:60]
            p  = f"{style_prefix} SCENE: {sc}. {LANGUAGE_SETTINGS[language]}."
            return i, p, sc, str(e)

    done = [0]
    with ThreadPoolExecutor(max_workers=parallel_workers) as ex:
        futs = {ex.submit(_make_prompt, (i, c)): i for i, c in enumerate(all_cuts)}
        for fut in as_completed(futs):
            i, p, sc, err = fut.result()
            if err:
                st.session_state.errors.append(f"컷{i+1} 프롬프트 오류: {err}")
            prompts_out[i] = p; scenes_out[i] = sc
            done[0] += 1
            prog.progress(done[0]/n, text=f"📝 프롬프트 생성 중... {done[0]}/{n}")

    st.session_state.prompts = prompts_out
    st.session_state.scenes  = scenes_out

    # 이미지 생성 — 완료되는 순서대로 실시간 표시
    images_out = [None] * n
    st.session_state.images = images_out  # 빈 상태로 먼저 저장
    st.session_state.step = 3
    st.session_state.cuts = all_cuts
    st.session_state.sections = all_sections

    prog2 = st.progress(0, text="🎨 이미지 생성 중...")
    done2 = [0]
    lock = __import__("threading").Lock()

    # 미리보기 placeholder — 컷 순서대로 배치
    st.markdown("**🎨 생성 중... (완료된 컷부터 순서대로 표시)**")
    placeholders = []
    # 2열 그리드로 placeholder 생성
    for row_start in range(0, n, 2):
        cols = st.columns(2)
        for j, col in enumerate(cols):
            idx_p = row_start + j
            if idx_p < n:
                with col:
                    ph = st.empty()
                    ph.markdown(f"⏳ 컷 {idx_p+1} 생성 대기 중...")
                    placeholders.append(ph)

    def _make_image(args):
        i, cut, prompt = args
        try:
            img = generate_image(client, prompt, cut, character_b64, language, aspect_ratio)
            return i, img, None  # (index, image, error)
        except Exception as e:
            return i, None, str(e)  # 에러를 반환값으로 전달

    with ThreadPoolExecutor(max_workers=min(parallel_workers, 4)) as ex:
        futs2 = {ex.submit(_make_image, (i, c, p)): i
                 for i, (c, p) in enumerate(zip(all_cuts, prompts_out))}
        for fut in as_completed(futs2):
            i, img, err = fut.result()
            if err:
                st.session_state.errors.append(f"컷{i+1} 이미지 오류: {err}")
            images_out[i] = img
            with lock:
                done2[0] += 1
                prog2.progress(done2[0] / n, text=f"🎨 이미지 생성 중... {done2[0]}/{n} 완료")
            if i < len(placeholders):
                if img:
                    placeholders[i].image(img, caption=f"✅ 컷 {i+1}: {all_cuts[i][:25]}...", use_container_width=True)
                else:
                    placeholders[i].warning(f"❌ 컷 {i+1} 생성 실패")

    st.session_state.images = images_out
    st.rerun()

# ══════════════════════════════════════════════════════════════
# 재생성 처리
# ══════════════════════════════════════════════════════════════
if st.session_state.regen_idx is not None and api_key:
    idx = st.session_state.regen_idx
    st.session_state.regen_idx = None
    client = genai.Client(api_key=api_key)
    with st.spinner(f"컷 {idx+1} 재생성 중..."):
        regen_single(client, idx, style_prefix, character_b64, language, aspect_ratio)
    st.rerun()

# ══════════════════════════════════════════════════════════════
# 결과 출력
# ══════════════════════════════════════════════════════════════
cuts     = st.session_state.cuts
sections = st.session_state.sections
prompts  = st.session_state.prompts
scenes   = st.session_state.scenes
images   = st.session_state.images

if st.session_state.step >= 1 and cuts:

    # 분할 미리보기 (이미지 없을 때)
    if st.session_state.step == 1:
        st.success(f"✂️ 총 {len(cuts)}개 씬으로 분할됨 — '⚡ 일괄 생성' 버튼으로 이미지를 생성하세요.")
        n_intro = sum(1 for s in sections if s=="intro")
        st.caption(f"🎬 인트로 {n_intro}컷 + 📖 본문 {len(cuts)-n_intro}컷")
        for i, (cut, sec) in enumerate(zip(cuts, sections)):
            badge = "intro" if sec=="intro" else "body"
            label = f"{'🎬' if sec=='intro' else '📖'} SCENE {i+1}"
            st.markdown(f'<div class="scene-card"><div class="scene-header"><span>{label}</span><span class="{badge}-badge">{"인트로" if sec=="intro" else "본문"}</span></div><div class="scene-script">{cut}</div></div>', unsafe_allow_html=True)

    # 이미지 결과
    if st.session_state.step >= 3:
        ok = sum(1 for img in images if img is not None)
        st.success(f"✅ {ok}/{len(cuts)}개 생성 완료")

        if st.session_state.errors:
            with st.expander(f"⚠️ 오류 {len(st.session_state.errors)}건"):
                for e in st.session_state.errors: st.caption(e)

        # ZIP 다운로드
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf,"w") as zf:
            for i, img in enumerate(images):
                if img:
                    b = io.BytesIO(); img.save(b, format="PNG")
                    zf.writestr(f"scene_{i+1:02d}.png", b.getvalue())
        st.download_button("📦 생성된 모든 이미지 .ZIP 다운로드",
                           zip_buf.getvalue(), "vision_maker.zip",
                           "application/zip", type="primary", use_container_width=True)

        st.markdown("---")

        # 씬 카드 목록
        n_intro = sum(1 for s in sections if s=="intro")
        if n_intro > 0:
            st.markdown("### 🎬 인트로")

        for i, (cut, sec) in enumerate(zip(cuts, sections)):
            if sec == "body" and i == n_intro and n_intro > 0:
                st.markdown("### 📖 본문")

            badge_cls  = "intro-badge" if sec=="intro" else "body-badge"
            badge_text = "인트로" if sec=="intro" else "본문"
            scene_label = f"SCENE {i+1}"

            col_img, col_info = st.columns([1, 1.3])

            with col_img:
                if images[i]:
                    st.image(images[i], use_container_width=True)
                    buf = io.BytesIO(); images[i].save(buf, format="PNG")
                    st.download_button(f"⬇️ 다운로드", buf.getvalue(),
                                       f"scene_{i+1:02d}.png", "image/png",
                                       key=f"dl_{i}", use_container_width=True)
                else:
                    st.warning("생성 실패")

            with col_info:
                st.markdown(f'<div class="scene-header"><span class="status-done">✅ 완성</span> &nbsp; <span class="{badge_cls}">{badge_text}</span> &nbsp; <b>{scene_label}</b></div>', unsafe_allow_html=True)
                st.markdown("📄 **SCRIPT**")
                st.markdown(f'<div class="scene-script">{cut}</div>', unsafe_allow_html=True)

                if scenes[i]:
                    with st.expander("🎬 장면 해석"):
                        st.write(scenes[i])
                if prompts[i]:
                    with st.expander("🔍 프롬프트"):
                        st.code(prompts[i], language="text")

                if st.button("🔄 다시 생성", key=f"regen_{i}", use_container_width=True):
                    st.session_state.regen_idx = i
                    st.rerun()

            st.markdown("---")

# ══════════════════════════════════════════════════════════════
# 라이브러리 (localStorage)
# ══════════════════════════════════════════════════════════════
if st.session_state.step >= 3 and cuts:
    st.markdown("---")
    st.markdown("### 💾 라이브러리에 저장")
    save_title = st.text_input("저장 제목",
        value=(project_title.strip() or (cuts[0][:20] if cuts else "작업")) + "...",
        key="save_title_input")

    if st.button("📚 라이브러리에 저장 (48시간)", type="secondary"):
        items = []
        for i, (cut, img) in enumerate(zip(cuts, images)):
            img_b64 = ""
            if img:
                buf = io.BytesIO(); img.save(buf, format="PNG")
                img_b64 = base64.b64encode(buf.getvalue()).decode()
            items.append({"cut": cut, "img": img_b64,
                           "section": sections[i] if i < len(sections) else "body"})
        entry = {
            "id": str(int(datetime.datetime.now().timestamp()*1000)),
            "title": save_title,
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "expire": (datetime.datetime.now()+datetime.timedelta(days=2)).timestamp(),
            "items": items,
        }
        entry_json = json.dumps(entry, ensure_ascii=False)
        st.components.v1.html(f"""<script>
(function(){{
  var key='imggen_library';
  var arr=JSON.parse(localStorage.getItem(key)||'[]');
  var now=Date.now()/1000;
  arr=arr.filter(function(e){{return e.expire>now;}});
  arr.unshift({entry_json});
  localStorage.setItem(key,JSON.stringify(arr));
  var d=document.createElement('div');
  d.style.cssText='background:#d4edda;color:#155724;padding:10px 16px;border-radius:8px;font-size:13px;font-weight:600;';
  d.textContent='✅ 라이브러리에 저장됐습니다! (48시간 후 자동 삭제)';
  document.body.appendChild(d);
  setTimeout(function(){{d.remove();}},3000);
}})();
</script>""", height=50)
        st.success("✅ 저장 완료!")

st.markdown("---")
st.markdown("### 📚 라이브러리")
st.caption("저장된 작업물 — 클릭하면 펼쳐집니다. 48시간 후 자동 삭제.")

st.components.v1.html("""
<style>
  body{font-family:sans-serif;margin:0;background:transparent;}
  .li{border:1px solid #e0e0e0;border-radius:10px;padding:12px 16px;margin-bottom:8px;background:#fafafa;cursor:pointer;}
  .li:hover{background:#f0f4ff;}
  .lt{font-weight:600;font-size:13px;color:#333;}
  .lm{font-size:11px;color:#888;margin-top:2px;}
  .ld{float:right;background:none;border:none;color:#cc4444;cursor:pointer;font-size:12px;}
  .imgs{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;}
  .imgs img{width:85px;height:85px;object-fit:cover;border-radius:6px;border:1px solid #ddd;}
  .icap{font-size:10px;color:#555;text-align:center;width:85px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;}
  .ibadge{font-size:9px;border-radius:8px;padding:1px 5px;background:#fff3cd;color:#856404;}
  .ibadge.body{background:#d1ecf1;color:#0c5460;}
</style>
<div id="lib"></div>
<script>
(function(){
  var key='imggen_library';
  var el=document.getElementById('lib');
  function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
  function render(){
    var arr;try{arr=JSON.parse(localStorage.getItem(key)||'[]');}catch(e){arr=[];}
    var now=Date.now()/1000;
    arr=arr.filter(function(e){return e.expire>now;});
    localStorage.setItem(key,JSON.stringify(arr));
    el.innerHTML='';
    if(!arr.length){el.innerHTML='<div style="color:#aaa;font-size:12px;padding:8px 0;">저장된 항목이 없습니다.</div>';return;}
    arr.forEach(function(entry,idx){
      var card=document.createElement('div');card.className='li';
      var exp=new Date(entry.expire*1000);
      var expStr=(exp.getMonth()+1)+'/'+exp.getDate()+' '+exp.getHours()+':'+String(exp.getMinutes()).padStart(2,'0')+' 까지';
      card.innerHTML='<button class="ld" data-i="'+idx+'">🗑</button>'
        +'<div class="lt">'+esc(entry.title)+'</div>'
        +'<div class="lm">'+entry.date+' · '+(entry.items||[]).length+'컷 · ⏳'+expStr+'</div>';
      var imgArea=document.createElement('div');imgArea.className='imgs';imgArea.style.display='none';
      (entry.items||[]).forEach(function(item){
        var w=document.createElement('div');
        if(item.img){var im=document.createElement('img');im.src='data:image/png;base64,'+item.img;w.appendChild(im);}
        var cap=document.createElement('div');cap.className='icap';cap.textContent=item.cut;w.appendChild(cap);
        var badge=document.createElement('div');
        badge.className='ibadge'+(item.section==='body'?' body':'');
        badge.textContent=item.section==='intro'?'인트로':'본문';
        w.appendChild(badge);
        imgArea.appendChild(w);
      });
      card.appendChild(imgArea);
      card.addEventListener('click',function(e){
        if(e.target.classList.contains('ld'))return;
        imgArea.style.display=imgArea.style.display==='none'?'flex':'none';
      });
      card.querySelector('.ld').addEventListener('click',function(e){
        e.stopPropagation();
        var arr2=JSON.parse(localStorage.getItem(key)||'[]');
        arr2.splice(parseInt(this.getAttribute('data-i')),1);
        localStorage.setItem(key,JSON.stringify(arr2));render();
      });
      el.appendChild(card);
    });
  }
  render();
})();
</script>
""", height=380, scrolling=True)




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
