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
PREVIEW_WIDTH = 4

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
    preview = img.copy()
    draw = ImageDraw.Draw(preview)
    for y in cut_points:
        draw.rectangle(
            [0, y - PREVIEW_WIDTH // 2, img.width, y + PREVIEW_WIDTH // 2],
            fill=PREVIEW_LINE
        )
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

        st.text(f"크기: {img.width} x {img.height}px")

        # 여백 감지 & 컷 포인트 계산
        zones = find_whitespace_zones(img_array)
        cut_points = select_cut_points(zones, N_PARTS - 1, img.height)
        boundaries = [0] + cut_points + [img.height]

        # 컷 정보 표시
        with st.expander("컷 위치 상세 보기"):
            for i in range(N_PARTS):
                h = boundaries[i + 1] - boundaries[i]
                st.text(f"  [{i + 1:02d}] {boundaries[i]}px ~ {boundaries[i+1]}px  (높이 {h}px)")

        # 미리보기
        preview_img = make_preview(img, cut_points)

        # 미리보기를 세로로 길면 축소해서 표시
        max_preview_h = 800
        if preview_img.height > max_preview_h:
            ratio = max_preview_h / preview_img.height
            preview_small = preview_img.resize(
                (int(preview_img.width * ratio), max_preview_h),
                Image.LANCZOS
            )
        else:
            preview_small = preview_img

        st.image(preview_small, caption="빨간선 = 컷 위치 미리보기", use_container_width=True)

        # ZIP 다운로드
        zip_buf = split_to_zip(img, cut_points, stem, suffix)
        st.download_button(
            label=f"⬇️ {stem} 분할 파일 다운로드 (ZIP)",
            data=zip_buf,
            file_name=f"{stem}_분할.zip",
            mime="application/zip",
            use_container_width=True
        )

    st.divider()
    st.success("모든 파일 처리 완료!")
