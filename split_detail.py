"""
상세페이지 자동 분할 스크립트
- 이미지를 여백 기준으로 정확히 10장으로 분할
- 화질 무손실 처리 (PNG 완전 무손실 / JPG 최고 품질)
- 컷팅 위치 미리보기 후 저장
- PNG, JPG 지원 / 결과물은 output 폴더에 저장
"""

import re
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np


# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
N_PARTS       = 10      # 분할 장 수
THRESHOLD     = 245     # 여백 감지 밝기 기준 (0~255, 높을수록 엄격)
MIN_ZONE_H    = 3       # 여백으로 인정할 최소 높이(px)
PREVIEW_LINE  = (255, 50, 50)   # 미리보기 컷 라인 색상 (빨간색)
PREVIEW_WIDTH = 4       # 미리보기 컷 라인 두께(px)


# ──────────────────────────────────────────────
# 핵심 함수
# ──────────────────────────────────────────────

def find_whitespace_zones(img_array, threshold=THRESHOLD, min_height=MIN_ZONE_H):
    """이미지에서 여백(밝은 행) 구간 감지"""
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
    """여백 구간에서 최적 컷 포인트 선택, 부족하면 균등 분할로 보완"""
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

    # 여백 부족 시 균등 분할로 보완
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


def save_preview(img, cut_points, output_dir, stem):
    """컷 라인이 표시된 미리보기 이미지 저장"""
    preview = img.copy()
    draw = ImageDraw.Draw(preview)
    width = img.width

    for y in cut_points:
        draw.rectangle([0, y - PREVIEW_WIDTH // 2, width, y + PREVIEW_WIDTH // 2],
                       fill=PREVIEW_LINE)

    preview_path = output_dir / f"{stem}_미리보기.jpg"
    preview.convert('RGB').save(preview_path, format='JPEG', quality=90)
    return preview_path


def split_and_save(img, cut_points, output_dir, stem, suffix):
    """실제 분할 및 저장 (무손실)"""
    boundaries = [0] + cut_points + [img.height]

    for i in range(N_PARTS):
        top, bottom = boundaries[i], boundaries[i + 1]
        if top >= bottom:
            print(f"  경고: {i + 1}번 섹션이 비어있어 건너뜁니다.")
            continue

        section = img.crop((0, top, img.width, bottom))
        out_name = f"{stem}_{i + 1:02d}{suffix}"
        out_path = output_dir / out_name

        if suffix == '.png':
            # PNG: 완전 무손실
            section.save(out_path, format='PNG', optimize=False, compress_level=0)
        else:
            # JPG: 최고 품질, 서브샘플링 없음 (최대한 무손실에 가깝게)
            section.convert('RGB').save(
                out_path, format='JPEG', quality=100, subsampling=0
            )

        print(f"  저장: {out_name}  ({top}px ~ {bottom}px, 높이 {bottom - top}px)")


def process_image(image_path, output_dir):
    """이미지 한 장 처리: 미리보기 → 확인 → 저장"""
    img = Image.open(image_path)

    # RGB 변환 (RGBA, P 모드 등 처리)
    if img.mode == 'RGBA':
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    img_array = np.array(img)
    height, width = img_array.shape[:2]
    suffix = image_path.suffix.lower()
    stem = image_path.stem

    print(f"\n{'=' * 55}")
    print(f"파일: {image_path.name}  ({width} x {height}px)")
    print(f"{'=' * 55}")

    # 여백 감지 & 컷 포인트 계산
    zones = find_whitespace_zones(img_array)
    cut_points = select_cut_points(zones, N_PARTS - 1, height)
    boundaries = [0] + cut_points + [height]

    print(f"여백 구간 감지: {len(zones)}개")
    print(f"컷 포인트 (y좌표): {cut_points}")
    print()
    for i in range(N_PARTS):
        h = boundaries[i + 1] - boundaries[i]
        print(f"  [{i + 1:02d}] {boundaries[i]}px ~ {boundaries[i+1]}px  (높이 {h}px)")

    # 미리보기 저장
    preview_path = save_preview(img, cut_points, output_dir, stem)
    print(f"\n미리보기 저장됨: {preview_path.name}")
    print(">>> 미리보기 파일을 열어서 컷 위치를 확인하세요.")

    # 사용자 확인
    while True:
        answer = input("\n이 컷 위치로 저장하시겠습니까? (y = 저장 / n = 건너뜀 / q = 종료): ").strip().lower()
        if answer in ('y', 'yes', 'ㅛ'):
            split_and_save(img, cut_points, output_dir, stem, suffix)
            print(f"  → {N_PARTS}장 저장 완료!")
            break
        elif answer in ('n', 'no', 'ㅜ'):
            print("  → 건너뜁니다.")
            break
        elif answer in ('q', 'quit', 'ㅂ'):
            print("종료합니다.")
            raise SystemExit
        else:
            print("  y / n / q 중 하나를 입력하세요.")


# ──────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────

def main():
    work_dir = Path(__file__).parent
    output_dir = work_dir / "output"
    output_dir.mkdir(exist_ok=True)

    # 이미지 수집 (이미 분할된 파일 및 미리보기 제외)
    exts = ['.png', '.jpg', '.jpeg']
    images = []
    for ext in exts:
        images.extend(work_dir.glob(f'*{ext}'))
        images.extend(work_dir.glob(f'*{ext.upper()}'))

    images = sorted(set(
        img for img in images
        if not re.search(r'_\d{2}$', img.stem)
        and '미리보기' not in img.stem
    ))

    if not images:
        print("처리할 이미지가 없습니다.")
        print(f"이미지를 이 폴더에 넣어주세요:\n{work_dir}")
        input("\n엔터를 눌러 종료...")
        return

    print(f"발견된 이미지: {len(images)}개")
    print(f"결과물 저장 위치: {output_dir}\n")

    for image_path in images:
        try:
            process_image(image_path, output_dir)
        except SystemExit:
            break
        except Exception as e:
            print(f"\n오류 ({image_path.name}): {e}")

    print(f"\n모든 작업 완료! → {output_dir}")
    input("엔터를 눌러 종료...")


if __name__ == "__main__":
    main()
