"""
상세페이지 자동 분할 웹앱 (Streamlit)
"""

import io
import re
import zipfile
from PIL import Image, ImageDraw
import numpy as np
import streamlit as st

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
N_PARTS       = 10
THRESHOLD     = 245
MIN_ZONE_H    = 3
PREVIEW_LINE  = (255, 50, 50)
PREVIEW_WIDTH = 6      # 미리보기 컷 라인 두께 (원본 픽셀 기준)
DISPLAY_WIDTH = 1440   # 미리보기 표시 가로 해상도 (원본 크기 유지)

# ──────────────────────────────────────────────
# 핵심 함수
# ──────────────────────────────────────────────

def find_whitespace_zones(img_array, threshold=THRESHOLD, min_height=MIN_ZONE_H):
    row_means = img_array[:, :, :3].mean(axis=(1, 2))
    is_white = row_means >= threshold
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
    ideal_positions = [img_height * i / (n_cuts + 1) for i in range(1, n_cuts + 1)]
    selected = []
    if zones:
        zone_centers = [(s + e) // 2 for s, e in zones]
        available = zone_centers.copy()
        for ideal in ideal_positions:
            if not available:
                break
            closest = min(available, key=lambda x: abs(x - ideal))
            selected.append(closest)
            available.remove(closest)
    while len(selected) < n_cuts:
        all_points = sorted(selected + [0, img_height])
        gaps = [
            (all_points[i + 1] - all_points[i], (all_points[i] + all_points[i + 1]) // 2)
            for i in range(len(all_points) - 1)
        ]
        gaps.sort(reverse=True)
        mid = gaps[0][1]
        if mid not in selected:
            selected.append(mid)
        else:
            break
    return sorted(selected)[:n_cuts]


def make_preview(img, cut_points):
    """컷 라인이 표시된 미리보기 이미지 생성 (원본 해상도)"""
    preview = img.copy()
    draw = ImageDraw.Draw(preview)
    for idx, y in enumerate(cut_points):
        # 컷 라인
        draw.rectangle(
            [0, y - PREVIEW_WIDTH // 2, img.width, y + PREVIEW_WIDTH // 2],
            fill=PREVIEW_LINE
        )
        # 컷 번호 표시
        label = f" {idx + 1} "
        draw.rectangle([0, y - PREVIEW_WIDTH // 2 - 30, 80, y - PREVIEW_WIDTH // 2], fill=PREVIEW_LINE)
        draw.text((4, y - PREVIEW_WIDTH // 2 - 28), f"컷{idx + 1}", fill=(255, 255, 255))
    return preview


def split_to_zip(img, cut_points, stem, suffix):
    boundaries = [0] + cut_points + [img.height]
    zip_buffer = io.BytesIO()
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


def to_rgb(img):
    if img.mode == 'RGBA':
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        return bg
    return img.convert('RGB')


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

        img = Image.open(uploaded_file)
        img = to_rgb(img)
        img_array = np.array(img)
        suffix = "." + uploaded_file.name.rsplit(".", 1)[-1].lower()
        stem = uploaded_file.name.rsplit(".", 1)[0]
        stem = re.sub(r'_\d{2}$', '', stem)
        img_h = img.height
        img_w = img.width

        st.text(f"크기: {img_w} x {img_h}px")

        # 자동 컷 포인트 계산
        zones = find_whitespace_zones(img_array)
        auto_cuts = select_cut_points(zones, N_PARTS - 1, img_h)

        # ── 세션 상태 초기화 (파일별로 독립 관리) ──
        state_key = f"cuts_{uploaded_file.name}_{img_w}_{img_h}"
        if state_key not in st.session_state:
            st.session_state[state_key] = auto_cuts.copy()

        # ── 컷 위치 조정 슬라이더 ──
        with st.expander("✏️ 컷 위치 조정 (선택사항)", expanded=False):
            st.caption("슬라이더를 드래그하면 미리보기가 즉시 업데이트됩니다.")

            col_reset, _ = st.columns([1, 3])
            with col_reset:
                if st.button("자동 위치로 초기화", key=f"reset_{state_key}"):
                    st.session_state[state_key] = auto_cuts.copy()
                    st.rerun()

            adjusted_cuts = []
            for i in range(N_PARTS - 1):
                current_val = st.session_state[state_key][i]
                # 슬라이더 범위: 앞 컷보다 크고, 뒤 컷보다 작게 제한
                min_v = adjusted_cuts[-1] + 5 if adjusted_cuts else 5
                max_v = img_h - (N_PARTS - 1 - i) * 5

                # 값이 범위 밖이면 보정
                current_val = max(min_v, min(max_v, current_val))

                y = st.slider(
                    f"컷 {i + 1}  (현재: {current_val}px)",
                    min_value=min_v,
                    max_value=max_v,
                    value=current_val,
                    step=1,
                    key=f"slider_{state_key}_{i}"
                )
                adjusted_cuts.append(y)

            st.session_state[state_key] = adjusted_cuts

        cut_points = st.session_state[state_key]
        boundaries = [0] + cut_points + [img_h]

        # 컷 구간 요약
        with st.expander("📐 컷 구간 상세", expanded=False):
            for i in range(N_PARTS):
                h = boundaries[i + 1] - boundaries[i]
                st.text(f"  [{i + 1:02d}] {boundaries[i]}px ~ {boundaries[i+1]}px  (높이 {h}px)")

        # ── 미리보기 (원본 가로 해상도 유지) ──
        preview_img = make_preview(img, cut_points)

        # 가로를 기준으로 리사이즈 → 화질 유지
        if preview_img.width != DISPLAY_WIDTH:
            ratio = DISPLAY_WIDTH / preview_img.width
            preview_display = preview_img.resize(
                (DISPLAY_WIDTH, int(preview_img.height * ratio)),
                Image.LANCZOS
            )
        else:
            preview_display = preview_img

        st.image(
            preview_display,
            caption="빨간선 = 컷 위치  |  스크롤하여 전체 확인",
            use_container_width=True
        )

        # ── 다운로드 ──
        zip_buf = split_to_zip(img, cut_points, stem, suffix)
        st.download_button(
            label=f"⬇️ {stem} 분할 파일 다운로드 (ZIP, {N_PARTS}장)",
            data=zip_buf,
            file_name=f"{stem}_분할.zip",
            mime="application/zip",
            use_container_width=True
        )

    st.divider()
    st.success("모든 파일 준비 완료!")
