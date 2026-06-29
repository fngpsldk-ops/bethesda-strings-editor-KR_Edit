# BSE Korean Localization - 수정 내역

원본: https://github.com/0xra0/bethesda-strings-editor  
포크: https://github.com/fngpsldk-ops/bethesda-strings-editor-KR_Edit

이 문서는 원본 BSE에서 변경된 모든 내용을 기록합니다.  
새 대화에서 AI가 이 파일을 읽으면 맥락을 바로 파악할 수 있도록 작성되었습니다.

---

## 버그 수정

### `gui/main_window.py`
**GPU 모니터 비활성화** (1092~1093번째 줄 주석 처리)
- 원인: `GpuMonitorWidget`이 nvidia-smi를 2초마다 메인 스레드에서 동기 호출
- 증상: UI 멈춤 + cmd 창 깜빡임
- 수정: 두 줄 주석 처리로 위젯 생성 자체를 막음

**한국어 드롭다운 누락 수정** (`SUPPORTED_LANGUAGES` 리스트)
- 원인: `("Korean", "ko")` 항목이 목록에서 빠져 있었음 (개발자 실수)
- 수정: 해당 항목 추가. 백엔드(번역 로직, QC 등)는 이미 한국어 지원하고 있었음

### `gui/app_settings.py`
**Windows Python 3.10 크래시 수정** (`get_cache_dir()`)
- 원인: `Path("/mnt/ssd").is_mount()` 호출이 Windows Python 3.12 미만에서 `NotImplementedError` 발생
- 수정: `try/except (NotImplementedError, OSError)` 로 감싸서 False로 폴백

### `gui/settings_dialog.py`
**Settings OK 버튼 크래시 수정** (`accept()`, `_start_model_fetch()`)
- 원인: v0.2.3 버그. Settings 열 때 백그라운드에서 Ollama 모델 목록을 가져오는 `_OllamaModelsFetcher` QThread가 뜨는데, OK 클릭 시 이미 삭제된 C++ 객체에 접근해서 `RuntimeError: libshiboken: Internal C++ object already deleted` 발생
- 수정: `accept()`와 `_start_model_fetch()` 양쪽에 `try/except RuntimeError` 추가
- 참고: 원본 개발자도 NexusMods 댓글에서 이 버그를 인지하고 "소스로 직접 실행하라"고 안내함

---

## 기능 개선

### `gui/ollama_worker.py`
**한국어 번역 품질 개선**

1. **`_LANG_EXAMPLES` 한국어 예시 교체** (373번째 줄)
   - 기존: 단순 문장 3개
   - 변경: 이디엄(`Knock yourself out → 마음껏 하세요`), 구어체 톤, 고유명사 처리 예시 포함한 6개로 교체
   - 목적: few-shot으로 자연스러운 한국어 어체 유도

2. **시스템 프롬프트 Rule 추가** (577번째 줄 이후)
   - Rule 8: 영어 메타설명/주석 출력 금지 (`More appropriately...` 같은 누출 방지)
   - Rule 9: 번역 중복 출력 금지

3. **설정 해시 기반 캐시 자동 무효화**
   - `_compute_settings_hash()` 메서드 추가
   - glossary 내용 변경 시 캐시 키가 자동으로 달라져 재번역됨
   - 프롬프트 규칙 변경 시: `_compute_settings_hash()` 안의 `PROMPT_VERSION` 숫자를 올리면 전체 재번역
   - `translate_batch()` 시작 시 `self._settings_hash` 계산
   - `TranslationCache.make_key()` 두 곳에 `settings_hash=self._settings_hash` 전달

### `gui/translation_cache.py`
**캐시 키에 settings_hash 파라미터 추가**
- `make_key()` 시그니처에 `settings_hash: str = ""` 추가
- `raw` 문자열에 `\x00{settings_hash}\x00` 포함
- 기본값이 `""` 라 기존 코드와 하위호환 유지

---

## 추가 스크립트 (저장소 루트)

### `gemini_proxy.py`
Gemini API를 Ollama 형식으로 감싸는 로컬 프록시 서버.
- BSE가 Gemini를 직접 지원하지 않아서 제작
- BSE Settings에서 API URL을 `http://localhost:11435`로 변경하면 사용 가능
- 모델 드롭다운에서 `gemini-2.5-flash` 선택
- 실행: `python gemini_proxy.py --api-key YOUR_GEMINI_API_KEY`
- 의존성: `pip install fastapi uvicorn google-genai`
- Gemini API 키 발급: https://aistudio.google.com/apikey
- Gemini 2.5 Flash 무료 티어: 하루 1,500 요청, 신용카드 불필요

### `convert_translate_to_glossary.py`
팀 왈도 한글 패치의 `translate_en.txt`를 BSE glossary JSON으로 변환.
- 입력: Starfield 한글 패치의 `interface/translate_en.txt` (UTF-16 LE)
- 출력: BSE glossary JSON (`{"entries": [...]}` 형식)
- 필터: 완성 문장, 내부 변수명, 숫자 시작 항목 등 제거
- 실행: `python convert_translate_to_glossary.py --input translate_en.txt --output ko_glossary.json`

### `clean_bse_cache.py`
번역 캐시에서 불량 항목만 선택적으로 제거.
- 제거 대상: 중국어/일본어/키릴 문자 포함, 영어 메타설명 포함, 중복 번역
- 전체 캐시 삭제 없이 문제 항목만 골라냄
- `--dry-run` 옵션으로 미리보기 가능
- 실행: `python clean_bse_cache.py [--dry-run]`

---

## 데이터 파일

### `ko_glossary.json`
팀 왈도 `translate_en.txt`에서 추출한 UI 용어 2,067개.
- BSE Glossary Editor > Import JSON 으로 불러오기
- Glossary: Global 로 설정해야 모든 번역에 적용됨

### `ko_glossary_propernouns.json`
수동으로 정의한 스타필드 고유명사 20개.
- EVA→EVA, Den→덴, The Eye→디 아이, The Key→더 키
- heatleech→열거머리, Cora Coe→코라 코, Sam Coe→샘 코
- ZeroG→무중력, Freestar→자유 항성 공동체, UC→식민지 연합
- Deimos→데이모스, Stroud-Eklund→스트라우드 에클룬드
- Staryard→우주 조선소, Trident→트라이던트, Constellation→컨스텔레이션
- Cheyenne→샤이엔, ERROR→에러, Welder→용접기, Hatch→해치

---

## 현재 권장 설정

| 항목 | 값 |
|------|-----|
| 번역 엔진 | Gemini (gemini_proxy.py 경유) 또는 EXAONE 3.5 7.8B |
| Ollama 모델 (로컬) | exaone3.5:7.8b-instruct-q8_0 |
| Gemini 프록시 포트 | 11435 |
| Max workers | 2 (로컬 모델 안정성) |
| Target language | Korean |
| Glossary | ko_glossary.json + ko_glossary_propernouns.json 둘 다 import |

---

## 알려진 미해결 이슈

- 일부 600자 이상 긴 문자열에서 로컬 모델 타임아웃 발생 (Gemini로 우회)
- `Knock yourself out` 같은 영어 이디엄은 로컬 모델이 처리 못함 (Gemini 권장)
- 반말/존댓말 구분은 로컬 7.8B 모델 한계, Gemini가 유의미하게 나음
- 원본 번역 모델(`translategemma3-st`) 미배포 상태 (개발자가 NexusMods에서 확인)
- 한국어가 원본 UI 드롭다운에서 누락된 버그는 개발자가 인지, 향후 업데이트 예정

---

## 원본 업데이트 반영 방법

원본 저장소에 업데이트가 올라왔을 때:
```powershell
git remote add upstream https://github.com/0xra0/bethesda-strings-editor
git fetch upstream
git merge upstream/main
# 충돌 해결 후
git push
```
