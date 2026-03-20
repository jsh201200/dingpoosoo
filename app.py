import streamlit as st
from google import genai
from google.genai import types
import base64, io, re, time, json, datetime, zipfile
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

# Pillow 최신버전 호환성 패치
from PIL import Image as _PILImage
if not hasattr(_PILImage, 'ANTIALIAS'):
    _PILImage.ANTIALIAS = _PILImage.LANCZOS

def _apply_motion(clip, mode):
    """항상 화면 꽉 찬 상태로 시작, 5가지 패턴 + 줌"""
    import random
    w, h = clip.size
    dur = clip.duration
    SCALE = 1.25  # 항상 1.25배 크롭 상태로 시작

    if mode == "none":
        return clip

    if mode == "random":
        mode = random.choice([
            "zoom_in", "zoom_out",
            "pan_left", "pan_right",
            "pan_up", "pan_down", "pan_diagonal"
        ])

    if mode == "zoom_in":
        # 1.25 → 1.5 (항상 꽉 찬 상태)
        def zoom(t): return 1.25 + 0.25 * (t / dur)
        return clip.resize(zoom)

    elif mode == "zoom_out":
        # 1.5 → 1.25
        def zoom(t): return 1.5 - 0.25 * (t / dur)
        return clip.resize(zoom)

    elif mode == "pan_left":
        # 오른쪽에서 왼쪽으로
        big = clip.resize(SCALE)
        bw, bh = int(w * SCALE), int(h * SCALE)
        max_x = bw - w
        def pos(t): return (-int(max_x * (t / dur)), -int((bh - h) / 2))
        return big.set_position(pos).set_duration(dur).crop(x1=0, y1=0, width=w, height=h)

    elif mode == "pan_right":
        # 왼쪽에서 오른쪽으로
        big = clip.resize(SCALE)
        bw, bh = int(w * SCALE), int(h * SCALE)
        max_x = bw - w
        def pos(t): return (-int(max_x * (1 - t / dur)), -int((bh - h) / 2))
        return big.set_position(pos).set_duration(dur).crop(x1=0, y1=0, width=w, height=h)

    elif mode == "pan_up":
        # 아래에서 위로
        big = clip.resize(SCALE)
        bw, bh = int(w * SCALE), int(h * SCALE)
        max_y = bh - h
        def pos(t): return (-int((bw - w) / 2), -int(max_y * (t / dur)))
        return big.set_position(pos).set_duration(dur).crop(x1=0, y1=0, width=w, height=h)

    elif mode == "pan_down":
        # 위에서 아래로
        big = clip.resize(SCALE)
        bw, bh = int(w * SCALE), int(h * SCALE)
        max_y = bh - h
        def pos(t): return (-int((bw - w) / 2), -int(max_y * (1 - t / dur)))
        return big.set_position(pos).set_duration(dur).crop(x1=0, y1=0, width=w, height=h)

    elif mode == "pan_diagonal":
        # 사선 이동 (랜덤 방향)
        import random as _r
        dx = _r.choice([-1, 1])
        dy = _r.choice([-1, 1])
        big = clip.resize(SCALE)
        bw, bh = int(w * SCALE), int(h * SCALE)
        max_x = bw - w
        max_y = bh - h
        def pos(t):
            px = -int((max_x / 2) + dx * (max_x / 2) * (t / dur))
            py = -int((max_y / 2) + dy * (max_y / 2) * (t / dur))
            return (px, py)
        return big.set_position(pos).set_duration(dur).crop(x1=0, y1=0, width=w, height=h)

    return clip


def _get_shuffled_motions(n):
    """n개 클립에 대해 5가지 패턴을 골고루 섞어서 반환"""
    import random
    patterns = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "pan_diagonal"]
    result = []
    while len(result) < n:
        shuffled = patterns[:]
        random.shuffle(shuffled)
        result.extend(shuffled)
    return result[:n]



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
             ("last_intro_sec",4),("last_body_sec",20),("last_tts",1.2),
             ("auto_zip_ready",False),("auto_zip_data",None),("auto_zip_name",""),
             ("supertone_voices",[]),("supertone_voice_id","")]:
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
        index=0,
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
    st.divider()

    # 슈퍼톤 TTS
    st.markdown("### 🎙️ 슈퍼톤 TTS (자동생성)")
    supertone_key = st.text_input("Supertone API Key", type="password", placeholder="sup-...", label_visibility="collapsed", key="supertone_key_input")
    if supertone_key:
        st.success("✓ 연결됨", icon="✅")
        if st.button("🔄 목소리 목록 불러오기", use_container_width=True, key="load_voices_btn"):
            try:
                import requests as _req
                # 한국어 목소리 전체 + 커스텀 목소리
                all_voices = []
                # 일반 목소리 (한국어)
                next_token = None
                while True:
                    params = {"language": "ko"}
                    if next_token:
                        params["page_token"] = next_token
                    resp = _req.get("https://supertoneapi.com/v1/voices/search", headers={"x-sup-api-key": supertone_key}, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("items", [])
                        all_voices.extend(items)
                        next_token = data.get("next_page_token")
                        if not next_token or not items:
                            break
                    else:
                        break
                # 커스텀 목소리 (Soulless 등 클론보이스)
                next_token2 = None
                while True:
                    params2 = {}
                    if next_token2:
                        params2["page_token"] = next_token2
                    resp2 = _req.get("https://supertoneapi.com/v1/custom-voices", headers={"x-sup-api-key": supertone_key}, params=params2)
                    if resp2.status_code == 200:
                        data2 = resp2.json()
                        custom = data2.get("items", [])
                        for c in custom:
                            c["name"] = f"⭐ {c.get('name', 'Custom')}"
                        all_voices.extend(custom)
                        next_token2 = data2.get("next_page_token")
                        if not next_token2 or not custom:
                            break
                    else:
                        break
                st.session_state.supertone_voices = all_voices
                st.success(f"✅ 목소리 {len(all_voices)}개 로드됨! (⭐는 내 커스텀 목소리)")
            except Exception as e:
                st.error(f"오류: {e}")
    
    if st.session_state.supertone_voices:
        voice_options = {f"{v.get('name','Unknown')} ({v.get('gender','')}/{v.get('age','')})": v.get('voice_id') or v.get('id','') for v in st.session_state.supertone_voices if v.get('voice_id') or v.get('id')}
        selected_voice_name = st.selectbox("목소리 선택", list(voice_options.keys()), label_visibility="collapsed", key="voice_select")
        st.session_state.supertone_voice_id = voice_options[selected_voice_name]
        
        # 선택된 목소리 스타일 목록 동적으로
        selected_voice_data = next((v for v in st.session_state.supertone_voices if (v.get("voice_id") or v.get("id")) == st.session_state.supertone_voice_id), None)
        available_styles = selected_voice_data.get("styles", ["neutral"]) if selected_voice_data else ["neutral"]
        if not available_styles:
            available_styles = ["neutral"]
        supertone_style = st.selectbox("스타일", available_styles, label_visibility="collapsed", key="supertone_style")
        supertone_speed = st.select_slider("배속", options=[0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5], value=1.2, format_func=lambda x: f"{x}x", label_visibility="collapsed", key="supertone_speed")
        sup_col1, sup_col2 = st.columns(2)
        with sup_col1:
            supertone_pitch = st.slider("음높이", -24, 24, 0, step=1, key="supertone_pitch")
            st.caption(f"pitch_shift: {supertone_pitch}")
        with sup_col2:
            supertone_pitch_var = st.slider("음높이 변화", 0.0, 2.0, 1.0, step=0.1, key="supertone_pitch_var")
            st.caption(f"pitch_variance: {supertone_pitch_var}")
        # 미리듣기
        if selected_voice_data and selected_voice_data.get("samples"):
            sample = next((s for s in selected_voice_data["samples"] if s.get("language") == "ko"), selected_voice_data["samples"][0])
            if sample.get("url"):
                st.audio(sample["url"], format="audio/wav")
    else:
        st.caption("API 키 입력 후 목소리 목록을 불러오세요")
        supertone_style = "neutral"
        supertone_speed = 1.2

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
BODY_MAX  = 14000
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

    # ── 슈퍼톤 TTS 자동 생성 ─────────────────────────────────────
    if supertone_key and st.session_state.get("supertone_voice_id"):
        st.markdown("---")
        st.markdown("### 🎙️ 슈퍼톤 TTS 자동 생성 중...")
        try:
            import requests as _req
            import os as _os
            from pydub import AudioSegment as _AS
            import tempfile as _tmp2

            tts_dir = _os.path.join(_os.path.expanduser("~"), "Downloads", "딩푸수_TTS")
            _os.makedirs(tts_dir, exist_ok=True)

            tts_prog = st.progress(0, text="🎙️ TTS 생성 중...")
            tts_segments = []
            voice_id = st.session_state.supertone_voice_id

            # 300자 제한 → 구간별로 나눠서 생성 후 합치기
            for idx, cut in enumerate(all_cuts):
                # 300자 초과시 청크로 분할
                chunks = [cut[i:i+280] for i in range(0, len(cut), 280)]
                seg_audio = _AS.empty()
                for chunk in chunks:
                    tts_resp = _req.post(
                        f"https://supertoneapi.com/v1/text-to-speech/{voice_id}",
                        headers={"x-sup-api-key": supertone_key, "Content-Type": "application/json"},
                        json={
                            "text": chunk,
                            "language": "ko",
                            "style": supertone_style,
                            "model": "sona_speech_2",
                            "output_format": "wav",
                            "voice_settings": {
                                "pitch_shift": supertone_pitch,
                                "pitch_variance": supertone_pitch_var,
                                "speed": supertone_speed
                            }
                        },
                        timeout=60
                    )
                    if tts_resp.status_code == 200:
                        with _tmp2.NamedTemporaryFile(delete=False, suffix=".wav") as tf:
                            tf.write(tts_resp.content)
                            tf_path = tf.name
                        seg_audio += _AS.from_wav(tf_path)
                    else:
                        st.warning(f"컷{idx+1} TTS 오류: {tts_resp.status_code}")
                tts_segments.append(seg_audio)
                tts_prog.progress((idx+1)/len(all_cuts), text=f"🎙️ TTS 생성 중... {idx+1}/{len(all_cuts)}")

            # 전체 합치기
            full_audio = tts_segments[0]
            for seg in tts_segments[1:]:
                full_audio += seg

            tts_path = _os.path.join(tts_dir, f"voice_full.wav")
            full_audio.export(tts_path, format="wav")
            st.success(f"✅ 음성 생성 완료! {len(full_audio)/1000:.1f}초 → {tts_path}")
            st.session_state["tts_full_path"] = tts_path
            st.session_state["tts_cuts_durations"] = [len(seg)/1000 for seg in tts_segments]
        except Exception as e:
            st.error(f"TTS 오류: {e}")

    # ── 자동 ZIP 생성 & 즉시 다운로드 ───────────────────────────
    _auto_title = (
        project_title.strip()
        or (all_cuts[0][:20] if all_cuts else "작업")
    )
    import re as _re
    _safe_title = _re.sub(r'[\/*?:"<>|]', '', _auto_title).strip()[:30] or "딩푸수메이커"

    _zip_buf = io.BytesIO()
    with zipfile.ZipFile(_zip_buf, "w") as _zf:
        for _i, (_img, _cut) in enumerate(zip(images_out, all_cuts)):
            if _img:
                _b = io.BytesIO()
                _img.save(_b, format="PNG")
                _zf.writestr(f"scene_{_i+1:02d}.png", _b.getvalue())
        _script_lines = [f"딩푸수 메이커 — {_auto_title}", "=" * 40, ""]
        for _i, (_cut, _sec) in enumerate(zip(all_cuts, all_sections)):
            _label = "인트로" if _sec == "intro" else "본문"
            _script_lines.append(f"[scene_{_i+1:02d}] [{_label}]")
            _script_lines.append(_cut)
        _zf.writestr("대본_목록.txt", "\n".join(_script_lines).encode("utf-8"))

    st.session_state["auto_zip_data"]  = _zip_buf.getvalue()
    st.session_state["auto_zip_name"]  = f"{_safe_title}.zip"
    st.session_state["auto_zip_ready"] = True

    # ── 슈퍼톤 TTS + 이미지 → 자동 영상 합성 ──────────────────────
    if st.session_state.get("tts_full_path") and _os.path.exists(st.session_state["tts_full_path"]):
        st.markdown("### 🎬 영상 자동 합성 중...")
        try:
            from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
            import tempfile as _tmp, time as _time2

            tts_path = st.session_state["tts_full_path"]
            audio_clip = AudioFileClip(tts_path)
            total_dur = audio_clip.duration

            # 실제 TTS 구간 시간으로 배분 (있으면), 없으면 글자수 비율
            if st.session_state.get("tts_cuts_durations") and len(st.session_state["tts_cuts_durations"]) == len(images_out):
                clip_durations = st.session_state["tts_cuts_durations"]
                st.success("✅ TTS 실제 시간 기준 싱크 적용!")
            else:
                total_chars = sum(len(c) for c in all_cuts)
                clip_durations = [total_dur * (len(c) / total_chars) for c in all_cuts]

            motion_list = _get_shuffled_motions(len(images_out))
            clips = []
            auto_prog = st.progress(0, text="클립 생성 중...")
            for idx, img in enumerate(images_out):
                if img is None:
                    continue
                dur = clip_durations[idx] if idx < len(clip_durations) else total_dur / len(images_out)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                buf.seek(0)
                with _tmp.NamedTemporaryFile(delete=False, suffix=".png") as tf:
                    tf.write(buf.read())
                    tp = tf.name
                clip = ImageClip(tp, duration=dur).set_fps(30)
                clip = _apply_motion(clip, motion_list[idx])
                clips.append(clip)
                auto_prog.progress((idx+1)/len(images_out), text=f"클립 생성 {idx+1}/{len(images_out)}")

            import os as _os2
            auto_out = _os2.path.join(_os2.path.expanduser("~"), "Downloads", f"딩푸수_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
            est = int(total_dur * 0.8)
            m, s = divmod(est, 60)
            render_info = st.info(f"⚙️ 렌더링 중... (예상 {'%d분 %d초' % (m,s) if m else '%d초' % s} 소요)")
            final_clip = concatenate_videoclips(clips, method="compose").set_audio(audio_clip)
            final_clip.write_videofile(auto_out, fps=30, codec="libx264", audio_codec="aac", threads=4, logger=None)
            render_info.success(f"✅ 렌더링 완료!")
            st.balloons()
            st.success(f"🎉🎉 완전 자동화 완성!! → {auto_out}")
            st.session_state["tts_full_path"] = None
        except Exception as e:
            st.error(f"영상 합성 오류: {e}")

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
# 자동 ZIP 다운로드 배너
# ══════════════════════════════════════════════════════════════
if st.session_state.get("auto_zip_ready") and st.session_state.get("auto_zip_data"):
    st.balloons()
    st.success("🎉 이미지 생성 완료! ZIP 파일을 바로 받으세요!")
    st.download_button(
        "📦 ⬇️ ZIP 지금 바로 다운로드 (이미지 + 대본 목록)",
        data=st.session_state["auto_zip_data"],
        file_name=st.session_state["auto_zip_name"],
        mime="application/zip",
        type="primary",
        use_container_width=True,
        key="auto_zip_dl"
    )
    st.caption("⚠️ 새로고침하면 사라져요 — 지금 바로 받으세요!")
    if st.button("✅ 받았어요", key="zip_confirm", use_container_width=False):
        st.session_state["auto_zip_ready"] = False
        st.session_state["auto_zip_data"]  = None
        st.rerun()
    st.markdown("---")

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
# 🎬 영상 만들기
# ══════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("## 🎬 영상 만들기")

video_tab1, video_tab2, video_tab3 = st.tabs(["⚡ 로컬 자동생성", "📋 스크립트 방식", "📦 나중에 작업하기"])

# ──────────────────────────────────────────────────────────────
# TAB 1: 로컬 자동생성
# ──────────────────────────────────────────────────────────────
with video_tab1:
    st.caption("로컬(내 컴퓨터)에서 실행할 때 사용해요. 음성 업로드 → 버튼 하나 → mp4 완성!")

    # 무음 제거 설정
    st.markdown("#### ✂️ 무음 제거 설정")
    local_sil_col1, local_sil_col2 = st.columns(2)
    with local_sil_col1:
        local_audio_file = st.file_uploader("🔊 슈퍼톤 음성파일 업로드", type=["mp3","wav","m4a"], key="local_audio_file")
    with local_sil_col2:
        local_keep_silence = st.slider("무음 유지 길이 (ms)", 100, 500, 200, step=50, key="local_keep_silence")
        st.caption(f"무음 구간을 {local_keep_silence}ms({local_keep_silence/1000}초)로 줄여요")

    st.markdown("#### 🎥 영상 설정")
    local_kb_style = st.selectbox("Ken Burns 효과", ["랜덤 (자동)", "줌인만", "줌아웃만", "좌→우 패닝", "우→좌 패닝", "없음"], key="local_kb_style")
    import os as _os
    local_output_path = _os.path.join(_os.path.expanduser("~"), "Downloads", f"딩푸수_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
    st.info(f"💾 저장 위치: {local_output_path}")

    n_imgs_local = len([img for img in st.session_state.get("images", []) if img])
    if n_imgs_local > 0:
        st.info(f"✅ 현재 세션 이미지 {n_imgs_local}개 준비됨")
    else:
        st.warning("⚠️ 먼저 이미지를 생성해주세요!")

    if st.button("🎬 영상 자동 생성 시작", type="primary", use_container_width=True, key="local_gen_btn"):
        if not local_audio_file:
            st.error("음성파일을 업로드해주세요.")
        elif n_imgs_local == 0:
            st.error("먼저 이미지를 생성해주세요.")
        else:
            try:
                from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
                from pydub import AudioSegment, silence as pydub_silence
                import tempfile, random

                kb_map = {"랜덤 (자동)": "random", "줌인만": "zoom_in", "줌아웃만": "zoom_out", "좌→우 패닝": "pan_left", "우→좌 패닝": "pan_right", "없음": "none"}
                kb_mode = kb_map[local_kb_style]

                with st.spinner("✂️ 무음 제거 중..."):
                    audio_bytes = local_audio_file.read()
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_in:
                        tmp_in.write(audio_bytes)
                        tmp_in_path = tmp_in.name
                    audio_seg = AudioSegment.from_file(tmp_in_path)
                    orig_dur = len(audio_seg) / 1000
                    chunks = pydub_silence.split_on_silence(audio_seg, min_silence_len=400, silence_thresh=-40, keep_silence=local_keep_silence)
                    if not chunks:
                        chunks = [audio_seg]
                    trimmed = chunks[0]
                    for c in chunks[1:]:
                        trimmed += c
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_out:
                        trimmed.export(tmp_out.name, format="mp3", bitrate="192k")
                        tmp_audio_path = tmp_out.name
                    trimmed_dur = len(trimmed) / 1000
                    st.success(f"✅ 무음 제거 완료: {orig_dur:.1f}초 → {trimmed_dur:.1f}초 ({orig_dur-trimmed_dur:.1f}초 단축)")

                with st.spinner("🎬 영상 생성 중... (잠깐 기다려요)"):
                    images_list = st.session_state.get("images", [])
                    valid_images = [(i, img) for i, img in enumerate(images_list) if img is not None]

                    audio_clip = AudioFileClip(tmp_audio_path)
                    total_dur = audio_clip.duration
                    per_clip = total_dur / len(valid_images)

                    def apply_kb(clip, mode):
                        if mode == "none": return clip
                        if mode == "random": mode = random.choice(["zoom_in", "zoom_out", "pan_left", "pan_right"])
                        w, h = clip.size
                        dur = clip.duration
                        if mode == "zoom_in":
                            return clip.resize(lambda t: 1.0 + 0.25 * (t / dur))
                        elif mode == "zoom_out":
                            return clip.resize(lambda t: 1.25 - 0.25 * (t / dur))
                        elif mode == "pan_left":
                            big = clip.resize(1.16)
                            return big.set_position(lambda t: (-int(w*0.08*(t/dur)), 0)).set_duration(dur).crop(x1=0,y1=0,width=w,height=h)
                        elif mode == "pan_right":
                            big = clip.resize(1.16)
                            return big.set_position(lambda t: (int(w*0.08*(t/dur)), 0)).set_duration(dur).crop(x1=0,y1=0,width=w,height=h)
                        return clip

                    clips = []
                    prog = st.progress(0, text="클립 생성 중...")
                    for idx, (i, img) in enumerate(valid_images):
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        buf.seek(0)
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_img:
                            tmp_img.write(buf.read())
                            tmp_img_path = tmp_img.name
                        clip = ImageClip(tmp_img_path, duration=per_clip).set_fps(30)
                        clip = apply_kb(clip, kb_mode)
                        clips.append(clip)
                        prog.progress((idx+1)/len(valid_images), text=f"클립 생성 중... {idx+1}/{len(valid_images)}")

                    final = concatenate_videoclips(clips, method="compose")
                    final = final.set_audio(audio_clip)
                    final.write_videofile(local_output_path, fps=30, codec="libx264", audio_codec="aac", threads=4, logger=None)

                st.balloons()
                st.success(f"🎉 영상 완성! → {local_output_path}")

            except ImportError as e:
                st.error(f"패키지 오류: {e}")
            except Exception as e:
                st.error(f"오류 발생: {e}")

# ──────────────────────────────────────────────────────────────
# TAB 2: 스크립트 방식
# ──────────────────────────────────────────────────────────────
with video_tab2:
    st.caption("스크립트를 받아서 로컬 cmd에서 실행하는 방식이에요. 경로는 자동으로 다운로드 폴더로 설정돼요!")

    st.markdown("#### ✂️ 1단계: 무음 제거 스크립트")
    st.info("📂 원본 음성파일을 다운로드 폴더에 넣어두면 자동으로 인식해요!")
    sil_col1, sil_col2 = st.columns(2)
    with sil_col1:
        silence_input_filename = st.text_input("원본 음성파일명", placeholder="예: voice.mp3", key="silence_input_filename")
        st.caption("다운로드 폴더 안의 파일명만 입력하세요")
    with sil_col2:
        silence_output_filename = st.text_input("출력 음성파일명", placeholder="예: voice_trimmed.mp3", key="silence_output_filename")
        st.caption("비워두면 자동으로 원본명_trimmed.mp3로 저장")

    if st.button("✂️ 무음 제거 스크립트 생성", use_container_width=True, key="gen_silence_script"):
        if not silence_input_filename:
            st.error("원본 음성파일명을 입력해주세요.")
        else:
            out_name = silence_output_filename.strip() if silence_output_filename.strip() else silence_input_filename.rsplit(".",1)[0] + "_trimmed.mp3"
            silence_script = f'''#!/usr/bin/env python3
import os
from pydub import AudioSegment, silence
DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")
INPUT_FILE  = os.path.join(DOWNLOADS, r"{silence_input_filename}")
OUTPUT_FILE = os.path.join(DOWNLOADS, r"{out_name}")
KEEP_SILENCE_MS = 200
MIN_SILENCE_MS  = 400
SILENCE_THRESH  = -40
print(f"📂 불러오는 중: {{INPUT_FILE}}")
audio = AudioSegment.from_file(INPUT_FILE)
orig = len(audio)/1000
print(f"원본: {{orig:.1f}}초")
chunks = silence.split_on_silence(audio, min_silence_len=MIN_SILENCE_MS, silence_thresh=SILENCE_THRESH, keep_silence=KEEP_SILENCE_MS)
if not chunks: chunks = [audio]
output = chunks[0]
for c in chunks[1:]: output += c
trimmed = len(output)/1000
print(f"처리후: {{trimmed:.1f}}초 ({{orig-trimmed:.1f}}초 단축)")
output.export(OUTPUT_FILE, format="mp3", bitrate="192k")
print(f"✅ 완성! → {{OUTPUT_FILE}}")
'''
            st.success("✅ 생성 완료!")
            st.download_button("⬇️ remove_silence.py 다운로드", silence_script.encode("utf-8"), "remove_silence.py", "text/x-python", use_container_width=True, key="dl_silence_script")
            st.code("pip install pydub\npython remove_silence.py", language="bash")

    st.markdown("---")
    st.markdown("#### 🎬 2단계: 영상 합치기 스크립트")
    st.info("📂 이미지 ZIP 압축 푼 폴더와 음성파일을 다운로드 폴더에 넣어두세요!")
    vid_col1, vid_col2 = st.columns(2)
    with vid_col1:
        img_folder_name = st.text_input("📁 이미지 폴더명", placeholder="예: 딩푸수이미지", key="img_folder_name")
        st.caption("다운로드 폴더 안의 폴더명만 입력하세요")
    with vid_col2:
        audio_file_name = st.text_input("🔊 음성파일명", placeholder="예: voice_trimmed.mp3", key="audio_file_name")
        st.caption("다운로드 폴더 안의 파일명만 입력하세요")
    ken_burns_style = st.selectbox("🎥 Ken Burns 효과", ["랜덤 (자동)", "줌인만", "줌아웃만", "좌→우 패닝", "우→좌 패닝", "없음"], key="ken_burns_style")

    if st.button("🎬 영상 제작 스크립트 생성", type="primary", use_container_width=True, key="gen_video_script"):
        if not img_folder_name or not audio_file_name:
            st.error("이미지 폴더명과 음성파일명을 입력해주세요.")
        else:
            kb_map = {"랜덤 (자동)": "random", "줌인만": "zoom_in", "줌아웃만": "zoom_out", "좌→우 패닝": "pan_left", "우→좌 패닝": "pan_right", "없음": "none"}
            kb_mode = kb_map[ken_burns_style]
            script_code = f'''#!/usr/bin/env python3
import os, glob, random
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
from datetime import datetime
DOWNLOADS   = os.path.join(os.path.expanduser("~"), "Downloads")
IMG_FOLDER  = os.path.join(DOWNLOADS, r"{img_folder_name}")
AUDIO_FILE  = os.path.join(DOWNLOADS, r"{audio_file_name}")
OUTPUT_FILE = os.path.join(DOWNLOADS, f"딩푸수_{{datetime.now().strftime('%Y%m%d_%H%M%S')}}.mp4")
KB_MODE = "{kb_mode}"
FPS = 30
def apply_ken_burns(clip, mode):
    if mode == "none": return clip
    if mode == "random": mode = random.choice(["zoom_in","zoom_out","pan_left","pan_right"])
    w, h = clip.size
    dur = clip.duration
    if mode == "zoom_in": return clip.resize(lambda t: 1.0+0.04*(t/dur))
    elif mode == "zoom_out": return clip.resize(lambda t: 1.04-0.04*(t/dur))
    elif mode == "pan_left":
        big=clip.resize(1.16)
        return big.set_position(lambda t:(-int(w*0.08*(t/dur)),0)).set_duration(dur).crop(x1=0,y1=0,width=w,height=h)
    elif mode == "pan_right":
        big=clip.resize(1.16)
        return big.set_position(lambda t:(int(w*0.08*(t/dur)),0)).set_duration(dur).crop(x1=0,y1=0,width=w,height=h)
    return clip
imgs = sorted([f for ext in ["*.png","*.jpg"] for f in glob.glob(os.path.join(IMG_FOLDER,ext))])
print(f"이미지 {{len(imgs)}}개 발견")
audio = AudioFileClip(AUDIO_FILE)
per_clip = audio.duration / len(imgs)
print(f"음성 {{audio.duration:.1f}}초 → 이미지당 {{per_clip:.1f}}초")
clips = []
for i,p in enumerate(imgs):
    clip = apply_ken_burns(ImageClip(p,duration=per_clip).set_fps(FPS), KB_MODE)
    clips.append(clip)
    print(f"  {{i+1}}/{{len(imgs)}} 처리중...")
final = concatenate_videoclips(clips,method="compose").set_audio(audio)
final.write_videofile(OUTPUT_FILE,fps=FPS,codec="libx264",audio_codec="aac",threads=4,logger="bar")
print(f"✅ 완성! → {{OUTPUT_FILE}}")
'''
            st.success("✅ 생성 완료!")
            st.download_button("⬇️ make_video.py 다운로드", script_code.encode("utf-8"), "make_video.py", "text/x-python", use_container_width=True)
            st.code("pip install moviepy pillow\npython make_video.py", language="bash")

# ──────────────────────────────────────────────────────────────
# TAB 3: 나중에 작업하기
# ──────────────────────────────────────────────────────────────
with video_tab3:
    st.caption("이미지 생성을 해놓고 나중에 음성이랑 합칠 때 사용해요. 대본 파일 넣으면 글자수 기준으로 싱크 맞춰줘요!")

    st.markdown("#### 📁 파일 업로드")
    later_col1, later_col2 = st.columns(2)
    with later_col1:
        later_zip = st.file_uploader("🖼️ 이미지 ZIP", type=["zip"], key="later_zip")
        if later_zip:
            st.success(f"✅ {later_zip.name}")
    with later_col2:
        later_audio = st.file_uploader("🔊 음성파일", type=["mp3","wav","m4a"], key="later_audio")
        if later_audio:
            st.success(f"✅ {later_audio.name}")

    later_script = st.file_uploader("📄 대본 txt 파일 (있으면 글자수 기준 싱크 자동 적용!)", type=["txt"], key="later_script")
    if later_script:
        st.success(f"✅ {later_script.name} — 글자수 기준 싱크 적용!")
    else:
        st.caption("대본 없으면 이미지 균등 분배로 진행해요.")

    later_kb = st.selectbox("🎥 Ken Burns 효과", ["랜덤 (자동)", "줌인만", "줌아웃만", "좌→우 패닝", "우→좌 패닝", "위→아래", "아래→위", "사선", "없음"], key="later_kb")

    if later_script:
        later_sync_col1, later_sync_col2, later_sync_col3 = st.columns(3)
        with later_sync_col1:
            later_tts_speed = st.select_slider("TTS 배속", options=[0.8,0.9,1.0,1.1,1.2,1.3,1.5], value=1.2, format_func=lambda x: f"{x}배속", key="later_tts_speed")
        with later_sync_col2:
            later_intro_sec = st.slider("인트로 컷(초)", 4, 8, 6, key="later_intro_sec")
        with later_sync_col3:
            later_body_sec = st.select_slider("본문 컷(초)", options=[15,20,25,30,35,40,45,50,60], value=30, key="later_body_sec")

    import os as _os
    later_output = _os.path.join(_os.path.expanduser("~"), "Downloads", f"딩푸수_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
    st.info(f"💾 저장 위치: {later_output}")
    later_silence = st.slider("무음 유지 길이 (ms)", 100, 500, 200, step=50, key="later_silence")

    if st.button("🎬 영상 생성 시작", type="primary", use_container_width=True, key="later_gen_btn"):
        if not later_zip or not later_audio:
            st.error("ZIP 파일과 음성파일을 업로드해주세요.")
        else:
            try:
                from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
                from pydub import AudioSegment, silence as pydub_silence
                import tempfile, random, zipfile as zf_module, os

                with st.spinner("✂️ 무음 제거 중..."):
                    audio_bytes = later_audio.read()
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_in:
                        tmp_in.write(audio_bytes)
                        tmp_in_path = tmp_in.name
                    audio_seg = AudioSegment.from_file(tmp_in_path)
                    orig_dur = len(audio_seg) / 1000
                    chunks = pydub_silence.split_on_silence(audio_seg, min_silence_len=400, silence_thresh=-40, keep_silence=later_silence)
                    if not chunks: chunks = [audio_seg]
                    trimmed = chunks[0]
                    for c in chunks[1:]: trimmed += c
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_out:
                        trimmed.export(tmp_out.name, format="mp3", bitrate="192k")
                        tmp_audio_path = tmp_out.name
                    st.success(f"✅ 무음 제거: {orig_dur:.1f}초 → {len(trimmed)/1000:.1f}초")

                with st.spinner("📦 ZIP에서 이미지 추출 중..."):
                    tmp_dir = tempfile.mkdtemp()
                    zip_bytes = later_zip.read()
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_zip:
                        tmp_zip.write(zip_bytes)
                        tmp_zip_path = tmp_zip.name
                    with zf_module.ZipFile(tmp_zip_path, "r") as zref:
                        img_files = sorted([f for f in zref.namelist() if f.endswith((".png",".jpg",".jpeg"))])
                        zref.extractall(tmp_dir)
                    img_paths = sorted([os.path.join(tmp_dir, f) for f in img_files])
                    st.success(f"✅ 이미지 {len(img_paths)}개 추출됨")

                audio_clip = AudioFileClip(tmp_audio_path)
                total_dur = audio_clip.duration

                if later_script:
                    with st.spinner("📄 대본 기반 싱크 계산 중..."):
                        later_script.seek(0)
                        script_text = later_script.read().decode("utf-8", errors="ignore")
                        raw = re.split(r'(?<=[.!?。])\s*|\n+', script_text.strip())
                        sentences = [s.strip() for s in raw if s.strip() and len(s.strip()) >= 3]
                        def cps(sec): return round(sec * 4.5 * later_tts_speed)
                        intro_chars = cps(later_intro_sec)
                        body_chars = cps(later_body_sec)
                        cuts_list = []
                        intro_done = False
                        current = ""
                        intro_total = 0
                        for sent in sentences:
                            if not intro_done:
                                if intro_total + len(sent) <= 400:
                                    current = (current + " " + sent).strip()
                                    intro_total += len(sent)
                                    if len(current) >= intro_chars:
                                        cuts_list.append(current)
                                        current = ""
                                else:
                                    if current:
                                        cuts_list.append(current)
                                    current = sent
                                    intro_done = True
                            else:
                                if not current:
                                    current = sent
                                elif len(current) + len(sent) + 1 <= body_chars * 1.2:
                                    current += " " + sent
                                else:
                                    cuts_list.append(current.strip())
                                    current = sent
                        if current:
                            cuts_list.append(current.strip())

                        total_chars = sum(len(c) for c in cuts_list)
                        clip_durations = [total_dur * (len(c) / total_chars) for c in cuts_list]

                        n_imgs = len(img_paths)
                        n_cuts = len(cuts_list)
                        if n_imgs != n_cuts:
                            st.warning(f"⚠️ 이미지 {n_imgs}개 vs 대본 컷 {n_cuts}개 — 균등 분배로 전환")
                            clip_durations = [total_dur / n_imgs] * n_imgs
                        else:
                            st.success(f"✅ 대본 {n_cuts}컷 기준 싱크 적용!")
                else:
                    clip_durations = [total_dur / len(img_paths)] * len(img_paths)

                import time as _time
                with st.spinner("🎬 영상 생성 중..."):
                    kb_map = {"랜덤 (자동)": "random", "줌인만": "zoom_in", "줌아웃만": "zoom_out", "좌→우 패닝": "pan_right", "우→좌 패닝": "pan_left", "위→아래": "pan_down", "아래→위": "pan_up", "사선": "pan_diagonal", "없음": "none"}
                    kb_mode = kb_map.get(later_kb, "random")

                    # 랜덤이면 7가지 패턴 골고루 셔플
                    if kb_mode == "random":
                        motion_list = _get_shuffled_motions(len(img_paths))
                    else:
                        motion_list = [kb_mode] * len(img_paths)

                    # 1단계: 클립 생성 (진행바 + 시간 예측)
                    clips = []
                    prog = st.progress(0, text="🎬 클립 생성 중...")
                    time_status = st.empty()
                    clip_start = _time.time()
                    for idx, img_path in enumerate(img_paths):
                        dur = clip_durations[idx] if idx < len(clip_durations) else total_dur / len(img_paths)
                        clip = ImageClip(img_path, duration=dur).set_fps(30)
                        clip = _apply_motion(clip, motion_list[idx])
                        clips.append(clip)
                        elapsed = _time.time() - clip_start
                        done_ratio = (idx+1) / len(img_paths)
                        if idx > 0:
                            remaining = (elapsed / (idx+1)) * (len(img_paths) - idx - 1)
                            mins, secs = divmod(int(remaining), 60)
                            time_str = f"{mins}분 {secs}초" if mins > 0 else f"{secs}초"
                            time_status.info(f"⏱ 클립 생성 중... {idx+1}/{len(img_paths)} — 예상 남은 시간: 약 {time_str}")
                        prog.progress(done_ratio, text=f"클립 생성 {idx+1}/{len(img_paths)}")

                    time_status.success(f"✅ 클립 {len(img_paths)}개 생성 완료!")

                    # 2단계: 렌더링 (예상 시간 안내)
                    est_render = int(total_dur * 0.8)
                    mins, secs = divmod(est_render, 60)
                    render_str = f"약 {mins}분 {secs}초" if mins > 0 else f"약 {secs}초"
                    render_status = st.info(f"⚙️ 영상 렌더링 중... (예상 {render_str} 소요) 잠깐 기다려요!")
                    render_start = _time.time()
                    final = concatenate_videoclips(clips, method="compose").set_audio(audio_clip)
                    final.write_videofile(later_output, fps=30, codec="libx264", audio_codec="aac", threads=4, logger=None)
                    render_elapsed = int(_time.time() - render_start)
                    r_mins, r_secs = divmod(render_elapsed, 60)
                    render_str2 = f"{r_mins}분 {r_secs}초" if r_mins > 0 else f"{r_secs}초"
                    render_status.success(f"✅ 렌더링 완료! (실제 소요: {render_str2})")

                st.balloons()
                st.success(f"🎉 영상 완성! → {later_output}")

            except ImportError as e:
                st.error(f"패키지 오류: {e}")
            except Exception as e:
                st.error(f"오류 발생: {e}")


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
    st.info("👈 사이드바에서 설정 후, 대본을 입력하고 **⚡ 일괄 생성**을 눌러주세요.")
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
