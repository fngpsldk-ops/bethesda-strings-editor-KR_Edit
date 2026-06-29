#!/usr/bin/env python3
"""
BSE 번역 캐시 선택적 정제 스크립트
- 중국어/일본어 포함 항목 제거
- 영어 메타설명/주석이 섞인 항목 제거
- 번역이 반복되는 항목 제거
- 원문을 한국어로 번역 안 한 항목 제거

사용법:
    python clean_bse_cache.py [--dry-run]  # dry-run: 실제 삭제 없이 미리보기
    python clean_bse_cache.py              # 실제 정제 실행
"""
import json
import re
import sys
import argparse
from pathlib import Path

CACHE_PATH = Path(r"C:\Users\fngps\AppData\Roaming\BethesdaModTools\translation_cache.json")

# 중국어 음절 범위
CHINESE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
# 일본어 (히라가나 + 카타카나)
JAPANESE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
# 키릴 문자 (러시아/우크라이나어)
CYRILLIC = re.compile(r"[\u0400-\u04ff]")
# 영어 메타설명 패턴 (번역 후 영어 주석이 붙는 패턴)
META_ENGLISH = re.compile(
    r"\("
    r"(More appropriately|A better translation|Note:|In context|Alternatively|"
    r"fitting the context|polished tone|more natural|"
    r"This translation)"
    , re.IGNORECASE
)
# 한국어 글자
HANGUL = re.compile(r"[\uac00-\ud7a3]")


def is_bad(value: str) -> tuple[bool, str]:
    """번역 결과가 불량인지 판단. (불량여부, 이유) 반환."""
    if CHINESE.search(value):
        return True, "중국어 포함"
    if JAPANESE.search(value):
        return True, "일본어 포함"
    if CYRILLIC.search(value):
        return True, "키릴문자 포함"
    if META_ENGLISH.search(value):
        return True, "영어 메타설명 포함"
    # 번역이 반복되는 패턴 (→ 기호로 구분된 동일 텍스트)
    if "→" in value:
        parts = value.split("→")
        if len(parts) == 2 and parts[0].strip() == parts[1].strip():
            return True, "번역 중복 반복"
    # 한국어가 전혀 없는데 영어가 많은 경우 (번역 안 된 것)
    # 단, EVA 같은 고유명사는 한국어 없어도 정상이므로 길이로 판단
    if not HANGUL.search(value) and len(value) > 20:
        return True, "한국어 없음 (번역 실패 의심)"
    return False, ""


def main():
    parser = argparse.ArgumentParser(description="BSE 번역 캐시 선택적 정제")
    parser.add_argument("--dry-run", action="store_true", help="실제 삭제 없이 미리보기만")
    args = parser.parse_args()

    if not CACHE_PATH.exists():
        print(f"캐시 파일 없음: {CACHE_PATH}")
        sys.exit(0)

    with open(CACHE_PATH, encoding="utf-8") as f:
        data = json.load(f)

    total = len(data)
    bad_keys = []
    reasons = {}

    print(f"전체 캐시 항목: {total}개\n")
    print("=== 제거 대상 ===")

    for key, value in data.items():
        bad, reason = is_bad(value)
        if bad:
            bad_keys.append(key)
            reasons[key] = (reason, value[:80].replace('\n', ' '))
            print(f"  [{reason}] {value[:70].replace(chr(10), ' ')}")

    print(f"\n제거 대상: {len(bad_keys)}개 / 전체 {total}개")
    print(f"남을 항목: {total - len(bad_keys)}개")

    if not bad_keys:
        print("\n제거할 항목이 없습니다. 캐시가 깨끗해요.")
        return

    if args.dry_run:
        print("\n[DRY-RUN] 실제 삭제 없이 미리보기만 했습니다.")
        print("실제로 정제하려면: python clean_bse_cache.py")
        return

    # 백업 먼저
    backup_path = CACHE_PATH.with_suffix(".json.bak")
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"\n백업 저장: {backup_path}")

    # 불량 항목 제거
    for key in bad_keys:
        del data[key]

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print(f"정제 완료: {len(bad_keys)}개 제거 → {len(data)}개 남음")
    print("\n앱을 재시작하면 제거된 항목만 다시 번역됩니다.")


if __name__ == "__main__":
    main()
