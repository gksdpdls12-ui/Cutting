"""
상세페이지 자동 분할 웹앱 (Streamlit)
"""

import base64
import io
import re
import zipfile
from pathlib import Path
from PIL import Image
import numpy as np
import streamlit as st
import streamlit.components.v1 as components

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
N_PARTS    = 10
THRESHOLD  = 245
MIN_ZONE_H = 3

# 커스텀 컴포넌트 등록
_CUT_EDITOR = components.declare_component(
    "cut_editor",
    path=str(Path(__file__).parent / "cut_editor")
)

# ──────────────────────────────────────────────
# 핵심 함수
# ──────────────────────────────────────────────

def find_whitespace_zones(img_array, threshold=THRESHOLD, min_height=MIN_ZONE_H):
    row_means = img_array[:, :, :3].mean(axis=(1, 2))
    is_white  = row_means >= threshold
    zones, in_zone, zone_start = [], False, 0
    for i, white in enumerate(is_white):
        if white and not in_zone:
            in_zone, zone_start = True, i
        elif not white and in_zone:
            in_zone = False
            if i - zone_start >= min_height:
                zones.append((zone_start, i - 1))
    if in_zone and len(img_array) - zone_start >= min_height:
        zones.append((zone_start, len(img_array) - 1))
    return zones


def select_cut_points(zones, n_cuts, img_height):
    ideal = [img_height * i / (n_cuts + 1) for i in range(1, n_cuts + 1)]
    selected = []
    if zones:
        centers   = [(s + e) // 2 for s, e in zones]
        available = centers.copy()
        for pos in ideal:
            if not available:
                break
            closest = min(available, key=lambda x: abs(x - pos))
            selected.append(closest)
            available.remove(closest)
    while len(selected) < n_cuts:
        all_pts = sorted(selected + [0, img_height])
        gaps    = [(all_pts[i+1]-all_pts[i], (all_pts[i]+all_pts[i+1])//2)
                   for i in range(len(all_pts)-1)]
        gaps.sort(reverse=True)
        mid = gaps[0][1]
        if mid not in selected:
            selected.append(mid)
        else:
            break
    return sorted(selected)[:n_cuts]


def to_rgb(img):
    if img.mode == 'RGBA':
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        return bg
    return img.convert('RGB')


def img_to_b64(img, quality=82):
    """PIL 이미지 → base64 JPEG 문자열 (컴포넌트 전송용)"""
    buf = io.BytesIO()
    img.convert('RGB').save(buf, format='JPEG', quality=quality)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def split_to_zip(img, cut_points, stem, suffix):
    boundaries  = [0] + cut_points + [img.height]
    zip_buffer  = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i in range(N_PARTS):
            top, bottom = boundaries[i], boundaries[i + 1]
            if top >= bottom:
                continue
            section = img.crop((0, top, img.width, bottom))
            buf = io.BytesIO()
            if suffix == '.png':
                section.save(buf, format='PNG', optimize=False, compress_level=0)
            else:
                section.convert('RGB').save(buf, format='JPEG', quality=100, subsampling=0)
            buf.seek(0)
            zf.writestr(f"{stem}_{i + 1:02d}{suffix}", buf.read())
    zip_buffer.seek(0)
    return zip_buffer


# ──────────────────────────────────────────────
# UI
# ──────────────────────────────────────────────

st.set_page_config(page_title="상세페이지 분할기", page_icon="✂️", layout="centered")

st.title("✂️ 상세페이지 자동 분할기")
st.caption("이미지를 여백 기준으로 자동으로 10장 분할합니다.")

uploaded_files = st.file_uploader(
    "이미지를 업로드하세요 (PNG / JPG, 여러 장 가능)",
    type=["png", "jpg", "jpeg"],
    accept_multiple_files=True
)

if uploaded_files:
    for uploaded_file in uploaded_files:
        st.divider()
        st.subheader(f"📄 {uploaded_file.name}")

        img       = to_rgb(Image.open(uploaded_file))
        img_array = np.array(img)
        suffix    = "." + uploaded_file.name.rsplit(".", 1)[-1].lower()
        stem      = re.sub(r'_\d{2}$', '', uploaded_file.name.rsplit(".", 1)[0])

        st.text(f"크기: {img.width} x {img.height}px")

        # 자동 컷 포인트 계산
        zones     = find_whitespace_zones(img_array)
        auto_cuts = select_cut_points(zones, N_PARTS - 1, img.height)

        # 세션 상태 초기화
        state_key = f"cuts_{uploaded_file.name}_{img.width}_{img.height}"
        if state_key not in st.session_state:
            st.session_state[state_key] = auto_cuts.copy()

        cut_points = st.session_state[state_key]

        # ── 컨트롤 버튼 ──
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("자동 위치로 초기화", key=f"reset_{state_key}"):
                st.session_state[state_key] = auto_cuts.copy()
                st.rerun()

        # ── 인터랙티브 컷 에디터 ──
        st.caption("빨간 선을 드래그하여 컷 위치를 조정하세요.")
        result = _CUT_EDITOR(
            img_b64   = img_to_b64(img),
            img_width = img.width,
            img_height= img.height,
            cut_points= cut_points,
            key       = f"editor_{state_key}",
        )

        # 드래그 결과 반영
        if result is not None:
            new_cuts = [int(v) for v in result]
            if new_cuts != st.session_state[state_key]:
                st.session_state[state_key] = new_cuts
                cut_points = new_cuts

        # ── 컷 구간 요약 ──
        boundaries = [0] + cut_points + [img.height]
        with st.expander("📐 컷 구간 상세", expanded=False):
            for i in range(N_PARTS):
                h = boundaries[i + 1] - boundaries[i]
                st.text(f"  [{i + 1:02d}] {boundaries[i]}px ~ {boundaries[i+1]}px  (높이 {h}px)")

        # ── 다운로드 ──
        zip_buf = split_to_zip(img, cut_points, stem, suffix)
        st.download_button(
            label          = f"⬇️ {stem} 분할 파일 다운로드 (ZIP, {N_PARTS}장)",
            data           = zip_buf,
            file_name      = f"{stem}_분할.zip",
            mime           = "application/zip",
            use_container_width=True
        )

    st.divider()
    st.success("모든 파일 준비 완료!")
