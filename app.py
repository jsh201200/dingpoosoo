import streamlit as st
from google import genai
from google.genai import types
import base64, io, re, time, json, datetime, zipfile
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── 페이지 설정 ────────────────────────────────────────────────
st.set_page_config(page_title="딩푸수 메이커", page_icon="🎬", layout="wide", initial_sidebar_state="expanded")

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
        "Pixar and Disney CGI animation style, high-quality 3D render. "
        "When character reference is provided: render that character with large soulful eyes, soft detailed fur, "
        "fluid proportions, richly detailed outfit matching scene context. "
        "When NO character reference: use an expressive anthropomorphic animal character "
        "OR a stylized Pixar-style human character — whichever fits the scene better. "
        "Cinematic depth of field, vibrant saturated colors, warm rim lighting, volumetric light rays. "
        "Background is a fully realized stylized 3D environment matching the scene content exactly. "
        "Foreground, midground, background depth layers. "
        "Any text sharply rendered, legible, correctly spelled. "
        "Polished, warm, emotionally engaging — Pixar feature film quality."
    ),
    "📰 뉴스/시사 다큐": (
        "Editorial illustration in hand-drawn ink-and-wash style of Quentin Blake, news urgency aesthetic. "
        "Loose expressive scribbled ink line work — thick where dramatic, thin where delicate. "
        "High-contrast: stark white areas against deep charcoal black shadows. "
        "Minimal transparent watercolor wash — washed deep crimson red, cold navy blue, urgent ochre yellow. "
        "Any text (속보, 긴급, headlines, labels) as bold hand-lettered stenciled text on banners or torn paper. "
        "Characters show exaggerated emotion through body language. "
        "Raw, unfinished, powerful — breaking news illustration drawn under deadline pressure. "
        "Background environment must match the script topic exactly — NOT a news desk unless script is literally about news."
    ),
    "😊 실사 다큐 포토": (
        "National Geographic photojournalism aesthetic, cinematic documentary photography. "
        "When character reference is provided: render that character with extreme photorealistic fur/skin detail. "
        "When NO character reference: focus on environment and situation — "
        "use silhouetted anonymous human figures (no identifiable face), hands, symbolic objects, "
        "or pure environmental storytelling. NO random animals unless script mentions animals. "
        "Shallow depth of field — subject razor sharp, background bokeh. "
        "Volumetric natural lighting matching scene mood: golden-hour / cold fluorescence / dramatic spotlight. "
        "Background is a fully detailed real-world environment matching script content exactly. "
        "Shot on Canon EOS R5, 85mm f/1.4, 8K. Cinematic LUT color grade. World Press Photo award quality."
    ),
    "🎨 퀜틴 블레이크 수채화": (
        "Quentin Blake hand-drawn illustration — loose, joyful, humanistic. "
        "Scribbled expressive black ink lines with deliberate imperfection and energy. "
        "Layered transparent watercolor washes: warm blues, pale greens, golden ochre, dusty rose, soft reds. "
        "Pure white background preserved in key areas for luminosity. "
        "Characters with elastic exaggerated proportions — rubbery limbs, tilted heads, enormous expressive eyes. "
        "Background loosely suggested with gestural strokes establishing location. "
        "Any text as hand-lettered script organically woven into illustration. "
        "Background setting must reflect scene content — could be outdoors, indoors, abstract, anywhere."
    ),
    "🎭 흑백 드라마 잉크": (
        "Stark black-and-white ink illustration — political cartoon meets graphic novel. "
        "Bold deliberate brush strokes: razor-thin detail lines, thick slashing impact strokes. "
        "Chiaroscuro: deep black shadow pools, sharp white highlights, zero mid-tones. "
        "Strong diagonals, extreme angles, silhouettes against harsh white. "
        "Characters anatomically exaggerated for emotional effect. "
        "Background as bold graphic shapes matching scene environment. "
        "Any text as bold high-contrast block lettering. Zero color. Only black ink on white."
    ),
    "✏️ 모던 인포그래픽": (
        "Clean sophisticated modern editorial illustration — information design meets fine art. "
        "Precise consistent 1pt outlines, purely geometric. "
        "Flat color fills: 4-5 color palette maximum, one neutral, two accents, one dark anchor. "
        "Data visualization elements (charts, graphs, maps, timelines) as crisp graphic elements. "
        "Any text typographically clean, correctly spelled, sized as core compositional element. "
        "Background environment simplified into graphic shapes matching scene content. "
        "Prestigious Korean economics magazine cover aesthetic."
    ),
    "📊 경제학 유튜브": (
        "Korean economics/documentary YouTube illustration style. "
        "Bold, high-energy visual storytelling with dramatic color contrasts. "
        "Color palette: freely chosen to best match the specific scene's content and emotion. "
        "When the script involves economics/geopolitics: integrate world maps, trade arrows, charts, "
        "currency symbols, flag icons, statistics naturally into the background if relevant. "
        "When the script involves other topics: use fitting environments in the same bold energetic style. "
        "Characters expressive and dynamic, mid-action. "
        "Korean text labels only when adding clear informational value. "
        "Overall energy: MBC documentary meets Kurzgesagt — urgent, informative, visually exciting."
    ),
    "🖌️ 커스텀": "",
}

# 캐릭터 없을 때 fallback 지시
STICKMAN_FALLBACK = (
    "No specific character reference provided. "
    "Represent the human element using ONE of these approaches (choose what fits the scene best): "
    "1. SILHOUETTE — dark human outline against dramatic backlit background, no facial features visible. "
    "2. BACK VIEW — person seen from behind, facing toward the scene, viewer follows their gaze. "
    "3. SIDE PROFILE — partial face visible, no identifiable features, focus on expression/posture. "
    "4. HANDS/BODY ONLY — close-up on hands interacting with objects, or body from neck down. "
    "5. ANONYMOUS CROWD — multiple figures without individual facial detail. "
    "6. STICKMAN — simple 2D stick figure with expressive pose if the style suits it. "
    "Choose whichever creates the most cinematic and emotionally resonant image for this scene. "
    "Never generate an identifiable or realistic human face. "
)

# 모든 스타일에 공통 적용되는 품질 기본 지시
# (스타일 프롬프트 뒤에 항상 자동 추가됨)
BASE_QUALITY = (
    "HIGH DETAIL: richly detailed background environment that matches the script content exactly — "
    "NOT a generic office or news desk unless the script is literally about that. "
    "The background tells the story as much as the character. "
    "Expressive character with clear emotion visible in face and body posture. "
    "Dynamic lighting that matches the scene mood. "
    "Foreground, midground, and background layers for depth. "
    "Cinematic quality, highly detailed, masterpiece level rendering."
)


LANGUAGE_SETTINGS = {
    "언어 없음": "NO text, letters, words, or numbers anywhere in the image.",
    "한국어": "MINIMAL Korean text only — maximum 1~2 short words on signs or key visual elements if absolutely essential to the scene. Default to NO text unless critical.",
    "일본어": "MINIMAL Japanese text only — maximum 1~2 short words if absolutely essential. Default to NO text.",
    "영어": "MINIMAL English text only — maximum 1~2 short words if absolutely essential. Default to NO text.",
}

# ── 세션 초기화 ────────────────────────────────────────────────
for k, v in [("cuts",[]),("sections",[]),("styles",[]),("prompts",[]),
             ("scenes",[]),("images",[]),("step",0),("errors",[]),
             ("regen_idx",None),("last_intro",""),("last_body",""),
             ("last_intro_sec",4),("last_body_sec",20),("last_tts",1.2)]:
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════════
# 헬퍼 함수들
# ══════════════════════════════════════════════════════════════

def chars_per_second(s, tts_speed=1.0):
    # 한국어 기본 낭독 속도: 4.5자/초
    # TTS 1.2배속이면 실제 읽는 속도 = 4.5 * 1.2 = 5.4자/초
    return round(s * 4.5 * tts_speed)

def split_semantic(client, script, seconds, tts_speed=1.2):
    """
    대본 분할 — Python 직접 분할 방식 (100% 안정적)
    Gemini에게 맡기지 않고 문장 단위로 직접 묶음
    """
    chars = chars_per_second(seconds, tts_speed)
    script = script.strip()
    if not script:
        return []

    # 1단계: 문장 단위로 분리 (마침표/느낌표/물음표/줄바꿈)
    raw = re.split(r'(?<=[.!?。])\s*|\n+', script)
    sentences = [s.strip() for s in raw if s.strip() and len(s.strip()) >= 3]

    if not sentences:
        return [script]

    # 2단계: chars 기준으로 문장 묶기
    cuts = []
    current = ""
    for sent in sentences:
        if not current:
            current = sent
        elif len(current) + len(sent) + 1 <= chars * 1.2:
            current += " " + sent
        else:
            cuts.append(current.strip())
            current = sent
    if current:
        cuts.append(current.strip())

    # 3단계: 너무 짧은 컷(10자 미만) 앞 컷에 합치기
    merged = []
    for cut in cuts:
        if merged and len(cut) < 10:
            merged[-1] = merged[-1] + " " + cut
        else:
            merged.append(cut)

    return merged if merged else [script]


def _call_split_api(client, script, seconds, chars, est):
    """Gemini API로 분할 요청. 실패 시 1회 재시도."""
    prompt = f"""아래 대본을 이미지 컷으로 분할하세요.

⚠️ 가장 중요한 규칙: 반드시 {est}개로 분할할 것 (±1 허용)
한 컷 = 약 {chars}글자 = 약 {seconds}초

규칙:
- 처음부터 끝까지 빠짐없이 (한 문장도 생략 금지)
- 문장/절 단위로 자르기 (문장 중간 절대 금지)
- 5글자 미만 절은 앞뒤와 합치기
- 번호. 내용 형식만 출력 (설명·주석·빈줄 없이)

총 글자수: {len(script)}자 ÷ {chars}자 = 약 {est}컷이 나와야 정상입니다.
{est}개보다 적게 분할하면 틀린 것입니다.

출력:
1. 내용
2. 내용
...{est}. 내용

대본:
{script}"""

    for attempt in range(2):
        try:
            r = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=5000,
                )
            )
            cuts = []
            for line in r.text.strip().split("\n"):
                m = re.match(r'^\d+[\.\)]\s*(.+)', line.strip())
                if m and m.group(1).strip():
                    cuts.append(m.group(1).strip())
            if cuts:
                return cuts
        except Exception:
            if attempt == 0:
                time.sleep(3)
    return []


def _fallback_split(script, chars):
    """API 실패 시 문장 단위 fallback 분할."""
    sentences = re.split(r'(?<=[.!?。])\s+', script.strip())
    cuts, current = [], ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if not current:
            current = sent
        elif len(current) + len(sent) + 1 <= chars * 1.3:
            current += " " + sent
        else:
            cuts.append(current)
            current = sent
    if current:
        cuts.append(current)
    return cuts if cuts else [script]



def build_prompt(client, cut, style_prefix, character_b64, language, idx, total):
    """대본 내용 최우선 → 배경/구도/감정 자동 결정"""
    lang = LANGUAGE_SETTINGS[language]

    # 캐릭터 있으면: 스타일 프롬프트가 뭐든 이 캐릭터가 주인공
    char_note = (
        "CRITICAL: The main character MUST be the exact same character as in the reference image. "
        "Preserve species, face shape, body proportions, fur/skin color and texture EXACTLY. "
        "ONLY change: expression (match scene emotion), outfit (match scene context), pose/action. "
        "This applies regardless of the art style — same character, different style rendering. "
    ) if character_b64 else STICKMAN_FALLBACK

    comp_hints = [
        "Consider an extreme close-up if emotion is intense.",
        "Consider a wide shot to show the environment's scale.",
        "Consider a low angle to make the subject feel powerful.",
        "Consider an over-the-shoulder shot for a point-of-view feel.",
        "Consider a bird's eye view for an overview feel.",
        "Consider a dutch angle for tension or unease.",
        "Consider silhouetting the character against a dramatic backdrop.",
        "Consider showing hands or a key object in the foreground.",
        "Consider placing the character small against a vast background.",
        "Consider a side profile shot showing movement or direction.",
        "Consider a worm's eye view looking up dramatically.",
        "Consider a two-thirds composition with environment telling the story.",
    ]
    comp_hint = comp_hints[(idx - 1) % len(comp_hints)]

    sys = f"""You are a visual interpreter — your job is to READ the Korean script deeply and translate its TRUE MEANING into a vivid visual scene.

MOST IMPORTANT: Don't just describe what the words say literally. Capture what they MEAN and FEEL.

HOW TO INTERPRET:
- Metaphors → visualize them literally: "뚱냥이처럼 늘어진 몸" = a fat lazy cat melting into a bed
- Abstract concepts → make them physical: "의지력이 바닥났다" = an empty fuel gauge, a drained battery
- Emotional states → show in body and environment: "뇌가 파업" = factory shutdown, workers sitting down, machines stopped
- Comparisons → show both sides visually: "기름 없는 차" = car broken down, empty gauge, person pushing it
- Irony/contrast → show the tension: "성공하고 싶은데 못 움직인다" = person with fire in eyes but body stuck in quicksand

PROCESS:
1. What does this script REALLY mean? (not just the surface words)
2. What single image would make someone instantly GET it without reading?
3. What emotion hits you first when you read this?
4. What's the most DIRECT visual metaphor for this idea?

Then describe that scene: who, doing what, where, in what light, with what emotion.
Be SPECIFIC and VISUAL. 80-100 words, English only. No style words."""

    r = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f'Script segment {idx}/{total}:\n"{cut}"\n\nDescribe the scene:',
        config=types.GenerateContentConfig(
            system_instruction=sys,
            temperature=0.7,
            max_output_tokens=200,
        )
    )
    scene = r.text.strip().strip('"').strip("'")

    # 캐릭터가 있으면 스타일에서 동물/캐릭터 관련 지시를 덮어쓰기
    if character_b64:
        effective_style = f"{style_prefix} {BASE_QUALITY}"
        full = f"{effective_style} {char_note}SCENE: {scene}. {lang}"
    else:
        effective_style = f"{style_prefix} {BASE_QUALITY}" if style_prefix.strip() else BASE_QUALITY
        full = f"{effective_style} {char_note}SCENE: {scene}. {lang}"
    return full, scene


def generate_image(client, prompt, cut, character_b64, language, aspect_ratio="1:1"):
    """이미지 생성 — 캐릭터 참조 이미지를 최우선 기준으로"""
    ratio_map = {
        "16:9": "wide landscape 16:9",
        "1:1":  "square 1:1",
        "9:16": "vertical portrait 9:16",
    }
    ratio_note = ratio_map.get(aspect_ratio, "square 1:1")

    char_fallback_note = "" if character_b64 else "No character reference — use stickman or anonymous figure as appropriate. "
    final = f"{prompt} {char_fallback_note}Aspect ratio: {ratio_note}."

    if character_b64:
        contents = [
            types.Content(role="user", parts=[
                types.Part(inline_data=types.Blob(
                    mime_type="image/jpeg",
                    data=base64.b64decode(character_b64)
                )),
                types.Part(text=(
                    f"THIS IS THE CHARACTER REFERENCE IMAGE. "
                    f"The main character in the generated image MUST look identical to this character — "
                    f"same species, same face, same body shape, same fur/skin color. "
                    f"Apply the art style to THIS character, not a random one. "
                    f"Only adapt their expression, outfit, and pose to match the scene.\n\n{final}"
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
    st.markdown("## 🎬 딩푸수 메이커")

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

    # TTS 속도
    st.markdown("**🔊 TTS 재생 속도**")
    tts_speed = st.select_slider(
        "TTS 속도",
        options=[0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5],
        value=1.2,
        format_func=lambda x: f"{x}배속",
        label_visibility="collapsed",
        help="TTS 재생 속도에 맞게 글자 수 기준이 자동 조정됩니다."
    )
    chars_intro = chars_per_second(1, tts_speed)  # 1초당 글자수
    st.caption(f"1초당 약 **{chars_intro}글자** 기준 (기본 4.5 × {tts_speed}배속)")
    st.divider()

    st.markdown("**🎬 인트로**")
    intro_seconds = st.slider("인트로 컷 시간", 4, 8, 4, step=1,
                               format="%d초", label_visibility="collapsed")
    intro_chars = chars_per_second(intro_seconds, tts_speed)
    st.caption(f"컷당 약 **{intro_chars}글자**")

    st.markdown("**📖 본문**")
    body_seconds = st.select_slider(
        "본문 컷 시간",
        options=[15, 20, 25, 30, 35, 40, 45, 50, 60],
        value=30,
        format_func=lambda x: f"{x}초",
        label_visibility="collapsed"
    )
    body_chars = chars_per_second(body_seconds, tts_speed)
    st.caption(f"컷당 약 **{body_chars}글자**")
    st.divider()

    # 스타일
    st.markdown("### 🎨 비주얼 스타일")
    style_name = st.selectbox("스타일 선택", list(STYLE_PRESETS.keys()), index=list(STYLE_PRESETS.keys()).index("📊 경제학 유튜브"), label_visibility="collapsed")
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
    st.markdown("## 딩푸수 메이커 **v1.0**")
    st.caption("스크립트를 고품질 AI 비주얼 프로덕션으로 즉시 전환하세요.")
with col_btn1:
    split_only_btn = st.button("✂️ 장면 분할", use_container_width=True)
with col_btn2:
    gen_btn = st.button("⚡ 일괄 생성", type="primary", use_container_width=True)

st.markdown("---")

# 입력 영역 — 인트로 / 본문 2칸
INTRO_MAX = 400
BODY_MAX  = 12000
col_intro, col_body = st.columns(2)
with col_intro:
    st.markdown("**🎬 인트로 스크립트**")
    intro_script = st.text_area(
        "intro", label_visibility="collapsed", height=160,
        placeholder="강렬한 도입부 스크립트를 여기에 붙여넣으세요...",
        key="intro_input",
        max_chars=INTRO_MAX,
    )
    intro_len_now = len(intro_script)
    color = "🔴" if intro_len_now >= INTRO_MAX else "🟡" if intro_len_now > INTRO_MAX * 0.8 else "🟢"
    st.caption(f"⏱ 인트로 분할: {intro_seconds}s　　{color} {intro_len_now} / {INTRO_MAX}자")

with col_body:
    st.markdown("**📖 메인 본문 스크립트**")
    body_script = st.text_area(
        "body", label_visibility="collapsed", height=160,
        placeholder="본문 내용을 여기에 입력하세요...",
        key="body_input",
        max_chars=BODY_MAX,
    )
    body_len_now = len(body_script)
    color = "🔴" if body_len_now >= BODY_MAX else "🟡" if body_len_now > BODY_MAX * 0.8 else "🟢"
    st.caption(f"⏱ 본문: {body_seconds}s 기준　　{color} {body_len_now:,} / {BODY_MAX:,}자")

# 컷 수 실시간 예상
if intro_script.strip() or body_script.strip():
    intro_len = len(intro_script.strip())
    body_len  = len(body_script.strip())
    est_intro = max(1, round(intro_len / chars_per_second(intro_seconds, tts_speed))) if intro_len > 0 else 0
    est_body  = max(1, round(body_len  / chars_per_second(body_seconds,  tts_speed))) if body_len  > 0 else 0
    est_total = est_intro + est_body

    # 실제 분할된 컷 수가 있으면 함께 표시
    actual_total = len(st.session_state.cuts) if st.session_state.cuts else None
    actual_intro = sum(1 for s in st.session_state.get("sections",[]) if s=="intro") if actual_total else None
    actual_body  = (actual_total - actual_intro) if actual_total and actual_intro is not None else None

    col_e1, col_e2, col_e3 = st.columns(3)
    col_e1.metric(
        "🎬 인트로",
        f"실제 {actual_intro}컷" if actual_intro else (f"약 {est_intro}컷" if est_intro else "-"),
        delta=f"예상 {est_intro}컷" if actual_intro and actual_intro != est_intro else None
    )
    col_e2.metric(
        "📖 본문",
        f"실제 {actual_body}컷" if actual_body else (f"약 {est_body}컷" if est_body else "-"),
        delta=f"예상 {est_body}컷" if actual_body and actual_body != est_body else None
    )
    col_e3.metric(
        "📦 총",
        f"실제 {actual_total}컷" if actual_total else f"약 {est_total}컷",
        delta=f"예상 {est_total}컷" if actual_total and actual_total != est_total else None
    )
    if est_total > 30 and not actual_total:
        st.warning(f"⚠️ 예상 {est_total}컷 — 본문 컷 시간을 늘리면 컷 수가 줄어듭니다.")

# 대본·설정이 바뀌면 이전 분할 결과 자동 초기화
_cur_intro = intro_script.strip()
_cur_body  = body_script.strip()
_changed = (
    _cur_intro != st.session_state.last_intro or
    _cur_body  != st.session_state.last_body  or
    intro_seconds != st.session_state.last_intro_sec or
    body_seconds  != st.session_state.last_body_sec  or
    tts_speed     != st.session_state.last_tts
)
if _changed and st.session_state.step > 0:
    for k in ["cuts","sections","styles","prompts","scenes","images","errors"]:
        st.session_state[k] = []
    st.session_state.step = 0
# 현재 값 저장
st.session_state.last_intro     = _cur_intro
st.session_state.last_body      = _cur_body
st.session_state.last_intro_sec = intro_seconds
st.session_state.last_body_sec  = body_seconds
st.session_state.last_tts       = tts_speed

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

    if intro_script.strip():
        with st.spinner(f"✂️ 인트로 분할 중... ({len(intro_script.strip())}자)"):
            try:
                ic = split_semantic(client, intro_script.strip(), intro_seconds, tts_speed)
                all_cuts += ic; all_sections += ["intro"] * len(ic)
            except Exception as e:
                st.session_state.errors.append(f"인트로 분할 오류: {e}")

    if body_script.strip():
        with st.spinner(f"✂️ 본문 분할 중... ({len(body_script.strip())}자)"):
            try:
                bc = split_semantic(client, body_script.strip(), body_seconds, tts_speed)
                all_cuts += bc; all_sections += ["body"] * len(bc)
            except Exception as e:
                st.session_state.errors.append(f"본문 분할 오류: {e}")

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

    # ── 분할: 인트로·본문 각각 spinner로 진행 표시 ──
    all_cuts, all_sections = [], []

    if intro_script.strip():
        with st.spinner(f"✂️ 인트로 분할 중... ({len(intro_script.strip())}자)"):
            try:
                ic = split_semantic(client, intro_script.strip(), intro_seconds, tts_speed)
                all_cuts += ic
                all_sections += ["intro"] * len(ic)
                st.toast(f"✅ 인트로 {len(ic)}컷 분할 완료")
            except Exception as e:
                st.session_state.errors.append(f"인트로 분할 오류: {e}")

    if body_script.strip():
        with st.spinner(f"✂️ 본문 분할 중... ({len(body_script.strip())}자)"):
            try:
                bc = split_semantic(client, body_script.strip(), body_seconds, tts_speed)
                all_cuts += bc
                all_sections += ["body"] * len(bc)
                st.toast(f"✅ 본문 {len(bc)}컷 분할 완료")
            except Exception as e:
                st.session_state.errors.append(f"본문 분할 오류: {e}")

    if not all_cuts:
        st.error("분할 실패. 대본을 확인하거나 다시 시도해주세요.")
        st.stop()

    n = len(all_cuts)
    n_intro_cuts = sum(1 for s in all_sections if s == "intro")
    n_body_cuts  = n - n_intro_cuts
    st.success(f"✂️ 분할 완료 — 인트로 {n_intro_cuts}컷 + 본문 {n_body_cuts}컷 = 총 {n}컷")

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
        # 실패 시 최대 2회 재시도
        for attempt in range(3):
            try:
                img = generate_image(client, prompt, cut, character_b64, language, aspect_ratio)
                if img is not None:
                    return i, img, None
                # img가 None이면 재시도
                if attempt < 2:
                    time.sleep(2)
            except Exception as e:
                if attempt < 2:
                    time.sleep(3)  # 재시도 전 3초 대기
                else:
                    return i, None, str(e)
        return i, None, "3회 시도 후 실패"

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

    # ── 자동 라이브러리 저장 ──────────────────────────────────
    _auto_title = (
        project_title.strip()
        or (all_cuts[0][:20] if all_cuts else "작업")
    )
    _auto_items = []
    for _i, (_cut, _img) in enumerate(zip(all_cuts, images_out)):
        _img_b64 = ""
        if _img:
            _buf = io.BytesIO(); _img.save(_buf, format="PNG")
            _img_b64 = base64.b64encode(_buf.getvalue()).decode()
        _auto_items.append({
            "cut": _cut,
            "img": _img_b64,
            "section": all_sections[_i] if _i < len(all_sections) else "body"
        })
    _auto_entry = {
        "id": str(int(datetime.datetime.now().timestamp() * 1000)),
        "title": _auto_title,
        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "expire": (datetime.datetime.now() + datetime.timedelta(days=2)).timestamp(),
        "items": _auto_items,
    }
    _auto_json = json.dumps(_auto_entry, ensure_ascii=False)
    st.components.v1.html(f"""<script>
(function(){{
  var key='imggen_library';
  var arr=JSON.parse(localStorage.getItem(key)||'[]');
  var now=Date.now()/1000;
  arr=arr.filter(function(e){{return e.expire>now;}});
  arr.unshift({_auto_json});
  localStorage.setItem(key,JSON.stringify(arr));
}})();
</script>""", height=0)

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

        # ZIP 파일명 — 프로젝트 제목 or 인트로 첫 문장 자동 사용
        _zip_title = (
            project_title.strip()
            or (cuts[0][:20].strip() if cuts else "딩푸수메이커")
        )
        # 파일명에 쓸 수 없는 문자 제거
        import re as _re
        _safe_title = _re.sub(r'[\\/*?:"<>|]', '', _zip_title).strip()[:30]
        _zip_filename = f"{_safe_title}.zip" if _safe_title else "딩푸수메이커.zip"

        # ZIP 다운로드
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf,"w") as zf:
            for i, img in enumerate(images):
                if img:
                    b = io.BytesIO(); img.save(b, format="PNG")
                    zf.writestr(f"scene_{i+1:02d}.png", b.getvalue())
        st.download_button("📦 생성된 모든 이미지 .ZIP 다운로드",
                           zip_buf.getvalue(), _zip_filename,
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
