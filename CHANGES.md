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

### ~~`gemini_proxy.py`~~ (제거됨 — 2차 세션에서 대체)
Gemini API를 Ollama 형식으로 감싸는 로컬 프록시 서버였으나, 이제 BSE가 자체
OpenAI 호환 백엔드(`gui/openai_compat_worker.py`)로 Gemini/ChatGPT를 직접 호출하므로
불필요해져 저장소에서 삭제됨. Settings > Translation Backend > Cloud AI에서
API 키만 입력하면 됨 — 별도 프록시 서버 실행 불필요.

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
| 번역 백엔드 | Cloud AI (Settings > Translation Backend에서 선택) |
| 클라우드 모델 | gemini-3.5-flash (기본값, 콤보박스에서 변경 가능) |
| API 키 | Settings > Cloud AI Settings에 직접 입력 (SecretStore에 안전하게 저장, 프록시 서버 불필요) |
| 로컬 대안 | exaone3.5:7.8b-instruct-q8_0 (반말/존댓말 구분 등에서 클라우드보다 품질 낮음) |
| Max workers (로컬 사용 시) | 2 (안정성) |
| Source / Target language | English / Korean (기본값) |
| UI 언어 | 한국어 (Settings > Appearance > Interface Language) |
| Glossary | ko_glossary.json + ko_glossary_propernouns.json 둘 다 import, Global로 설정 |

---

## 2차 세션: OpenAI 호환 백엔드 GUI 통합 + 한글 UI + 안정화

### GUI 안에서 Gemini/ChatGPT 선택 (계획 1)

외부 프록시(`gemini_proxy.py`, 이제 저장소에서 제거됨) 없이, BSE 자체가 OpenAI 호환 API를
직접 호출하도록 새 백엔드를 추가했습니다.

- **`gui/openai_compat_worker.py`** (신규): `OllamaWorker`를 상속하지 않는 독립 워커.
  버그 격리를 위해 의도적으로 분리. `TranslationRequest.to_system_prompt()` /
  `to_prompt()`를 그대로 재사용해 Ollama 경로와 동일한 튜닝된 프롬프트를 씀.
  API 호출은 `openai` SDK가 아닌 `requests` 라이브러리로 직접 수행 — SDK가 Qt 스레드
  안에서 httpx/SSL 충돌로 "Connection error"를 내는 문제가 있어 우회함.
- **`gui/openai_compat_client.py`** (신규): API 키를 SecretStore(시스템 키링)에
  저장/조회. `claude_client.py`와 동일한 패턴.
- **`gui/app_settings.py`**: `backend_type`("ollama"|"claude"|"openai_compat"),
  `openai_compat_base_url`, `openai_compat_model` 필드 추가.
- **`gui/settings_dialog.py`**: "Translation Backend" 라디오 버튼(Local LLM / Cloud AI),
  "Cloud AI Settings" 그룹(Base URL, 모델 콤보박스 프리셋, API 키 입력+표시/숨김
  체크박스) 추가.
- **`gui/main_window.py`**: `_init_translation_worker()`를 3-way 분기로 확장
  (ollama / claude / openai_compat).

**디버깅 과정에서 잡은 버그들** (전부 실사용 중 발견 및 수정):
1. `_init_translation_worker()`가 워커를 openai_compat용으로 만들어도, Settings에서
   OK를 누르면 무조건 `update_config(base_url=ollama_url, model=ollama_model, ...)`가
   호출되어 URL/모델이 Ollama 값으로 덮어써짐 → 백엔드 종류에 따라 분기하도록 수정,
   변경 시 워커를 통째로 재생성.
2. `_cleanup_workers()`가 워커 객체는 정리하지만 `_worker_signals_connected` 플래그를
   리셋하지 않아, 백엔드 전환 후 새 워커에 `translation_requested` 시그널이 다시
   연결되지 않는 문제 → 플래그 리셋 추가 + `open_settings()`에서
   `_disconnect_worker_signals()` → `_init_translation_worker()` →
   `_connect_worker_signals()` 순서로 재연결하도록 수정.
3. `TranslationCache.put()` 호출 — 실제 메서드명은 `set()` → 수정.
4. Gemini 3.x 모델은 reasoning 모델이라 `temperature=0.3`이 루핑을 유발할 수 있음
   → 기본값 `1.0`으로 변경 (Google 권장값).

### 메뉴 한글화 (계획 2)

`gui/translations/ko_KR.ts`(1,587개 항목, 커뮤니티 번역)는 있었지만 컴파일된
`gui/translations/ko_KR.qm`이 없어서 항상 조용히 영어로 폴백되던 문제를 해결.
`lrelease`로 컴파일해 저장소에 커밋 (`.gitignore`의 `*.qm` 규칙을 `-f`로 우회).

### bat 실행기 (계획 3)

`run_bsek.bat` — 더블클릭 실행, 경로 독립적(`%~dp0` 사용), `main.py` 존재 확인,
오류 시 창 유지.

### 언어 범위 축소: en/ja/ko만 지원

원본 BSE는 11개 언어를 지원했지만, BSEK는 영어→한국어 전용 도구이므로 다음으로 정리:
- `gui/main_window.py`의 `SUPPORTED_LANGUAGES`를 English/Japanese/Korean 3개로 축소
  (일본어는 삭제하지 않고 유지 — Bethesda 공식 일본어 로컬라이제이션이 존댓말/반말
  구분을 갖고 있어, 한국어 번역 시 반말/존댓말 참고 자료로 쓸 수 있음).
- `gui/settings_dialog.py`에 **별도로 정의되어 있던** 언어 목록(`SUPPORTED_LANGUAGES =
  ['English', 'Russian', 'Ukrainian', 'Korean']`, 형식도 `main_window.py`와 다름 —
  표시 이름 문자열만 있고 로케일 코드가 없었음)도 발견하여 `(이름, 코드)` 튜플
  형식으로 통일. 이 형식 불일치 때문에 `combo_source`/`combo_target`의
  `findData()`가 항상 실패해 드롭다운이 항상 첫 항목(Russian)으로 떨어지던
  잠재 버그도 같이 수정됨.
- `gui/app_settings.py`: `default_source_lang`/`default_target_lang` 기본값을
  `"ru"`/`"uk"` → `"en"`/`"ko"`로 변경.
- **v36 마이그레이션 추가**: 옛 config(원본 BSE 또는 이전 BSEK 빌드)에
  `default_source_lang`/`default_target_lang`이 이제 지원하지 않는 언어 코드
  (de/es/fr/it/pl/ptbr/zhhans/ru/uk)로 남아있으면 자동으로 `en`/`ko`로 정규화.
  방치하면 언어 드롭다운의 `findData()`가 실패해 선택이 깨지는 문제를 예방.
- 우크라이나어 전용 "Check Gender Agreement…"(Ctrl+Alt+G) 메뉴 제거 — 한국어에는
  형용사-명사 성 일치 문법이 없어 해당 기능 자체가 무의미함.

### UI 가독성 수정 (다크 테마 대비 문제)

세 가지 별개의 색상 버그를 발견 및 수정 (전부 16개 내장 테마 검증 완료):

1. **Settings 다이얼로그의 안내문 텍스트**: `color: palette(mid)`를 쓰던 10곳이
   일부 다크 테마(Slate 등)에서 배경과 거의 구분 안 됨 → `ThemeManager.get_hint_color()`
   헬퍼 추가, 각 테마가 이미 갖고 있는 QStatusBar 텍스트 색을 재사용하도록 변경.
   테마 변경 시 자동 재적용됨 (`_register_hint_label()` / `_refresh_hint_colors()`).
2. **명령 팔레트(Ctrl+K)의 같은 문제**: `command_palette.py`의 `palette(mid)` 3곳도
   동일한 방식으로 수정 — `CommandPaletteDialog`가 `theme_manager`를 생성자에서
   받도록 확장.
3. **테이블 셀 선택 시 글자색 문제**: 셀을 클릭(선택)하면 테마의
   `selection-color`가 적용되는데, 일부 테마에서 이 색이 일반 글자색과 크게 달라
   커스텀 배경(QA 에러 행 등)과 겹쳐 안 보이는 문제 발생. 근본 해결로 16개 테마
   전부 `selection-color`를 일반 `color`와 동일하게 통일 — 셀 선택 시 글자색이
   바뀌지 않고 배경 강조로만 표시되도록 변경.
4. 한국어 UI에서 "품질: 7/10" 스핀박스 폭이 좁아 숫자가 잘리는 문제 →
   `setFixedWidth(72)` → `85`로 조정.

### 프롬프트 튜닝 (PROMPT_VERSION 1 → 2)

`TranslationRequest.to_system_prompt()`에 규칙 2개 추가 (Ollama/OpenAI-compat
양쪽 경로에서 공유):
- **Rule 10**: 퀘스트 목표/미션 로그/플레이어 행동 지시문은 서술형이 아니라
  존댓말 명령형(~하십시오/~하세요)으로 번역하도록 지시.
  예: "Attempt to undetectably steal any available fuel from a docked vessel."
  → "도킹 중인 함선에서 감지되지 않고 사용 가능한 연료를 훔치십시오."
- **Rule 11**: 반말/존댓말 선택을 화자의 맥락(거칠고 적대적인 대사=반말 경향,
  전문적/상업적/공적 대사=존댓말 경향)에 따라 판단하도록 가이드. 불확실하면
  존댓말을 기본값으로.

`gui/ollama_worker.py`와 `gui/openai_compat_worker.py` 양쪽의 `PROMPT_VERSION`을
1→2로 올려, 이 변경 이후 기존 캐시가 자동으로 무효화되고 새 규칙으로
재번역되도록 함.

---

## 3차 세션: TM 정확도/성능, 동시성 버그, 신규 워크플로 기능, 현지화 완성

이번 세션은 실제 모드 파일(rbt_RealFuel_RE, rbt_RealO2, du_overtime, EAA_TAFightOrFlight,
H0LZPOIExpansion 등)을 반복적으로 번역해보면서 드러난 문제를 하나씩 재현 →
근본 원인 진단 → 수정 → 실제 데이터로 검증하는 방식으로 진행했습니다.

### Translation Memory 정확도 (여러 차례에 걸친 수정)

`gui/translation_memory.py`:
- **성능**: `get_fuzzy()`가 조회마다 전체 코퍼스(17만+ 항목)를 선형 스캔 →
  단어 단위 역색인(inverted index) 도입, 원문과 공유 단어가 있는 후보만 채점.
  3~10초 → ~70ms (약 45배 개선). 기존 결과와 100% 동일함을 다수 쿼리로 회귀 검증.
- **짧은 문자열 오매칭 (1차)**: `"The Fuel Box"`가 무관한 `"Play the music box"`와
  퍼지 매칭됨 (공유 단어가 "the"/"box"뿐인데도 통과). 8단어 이하 문자열은
  원문-후보 단어가 양방향 85% 이상 겹쳐야만 재사용하도록 게이트 추가.
- **짧은 문자열 오매칭 (2차)**: `get_by_source()`(완전 일치 경로)에는 이 게이트가
  없어서 `"OFF"`→`실탄 중량 없음`, `on"`→`"대상:"` 같은 문맥 무관 완전 일치가
  그대로 통과됨. `on`/`off`처럼 3글자 이하인 단일 단어는 완전 일치라도 재사용
  금지(무조건 AI가 새로 번역)하도록 `get_by_source()`/`get_fuzzy()` 양쪽에 적용.
  `ENABLED`처럼 다의성 없는 긴 단일 단어는 그대로 재사용 유지.
- **숫자 불일치 거부**: 퍼지 매칭 시 원문/후보의 숫자 시퀀스가 다르면
  (`28LY` vs `30LY`) 무조건 거부하도록 이미 존재하던 로직 유지·검증.

### esp_handler.py — 필드 매핑 오류 및 환각 방지

`bethesda_strings/esp_handler.py`:
- **`DOOR/CNAM` 필드 제거**: "닫기 대체 텍스트"로 추정하고 번역 대상에
  포함시켰으나, 실제로는 애니메이션 리소스 경로(`setdressing\animated\...`)가
  들어있음이 확인됨. 번역 시 해당 애니메이션이 깨질 수 있는 심각한 버그였음.
- **경로처럼 생긴 문자열 전역 필터 추가**: 역슬래시/슬래시가 있고 공백이 없는
  텍스트는 어떤 필드에서 나왔든 번역 대상에서 자동 제외 (`_looks_like_resource_path`).
  유사한 미발견 필드 매핑 오류에 대한 안전망.
- **`QUST/FULL` 환각 방지 안내문**: 스크립트 전용 "유틸리티 퀘스트"의 짧고
  맥락 없는 이름(`"Item Spawn"`, `"Travel Handler"`)을 AI가 `"볼텍스 스폰"`,
  `"안전하게 다니세요"` 등 완전히 무관한 내용으로 창작하는 문제 확인.
  모든 `QUST/FULL` 항목에 "내부 CK 이름이며 플레이어에게 안 보일 수 있음,
  창작하지 말고 문자 그대로 번역"이라는 context_note를 자동 부여.

### 캐시 — 수동 교정 및 재시도 관련 버그

- **수동 교정이 캐시에 반영 안 됨 (`gui/main_window.py`)**: `_on_string_corrected`에
  캐시 쓰기 로직 추가. 워커가 사용하는 것과 동일한 캐시 키
  (`TranslationCache.make_key`)를 생성하는지 검증 완료.
- **더블클릭 편집 팝업만 이 로직을 안 탐 (`gui/string_table.py`)**: 인라인 편집/
  포커스 모드는 `string_manually_corrected` 시그널을 정상 발신했으나,
  `_open_edit_dialog`(더블클릭 팝업)만 `set_translated_text()`만 호출하고
  시그널을 안 보내서 캐시 저장 로직이 아예 트리거되지 않음. 시그널 발신 추가.
- **품질검토 재번역이 캐시에 의해 무력화됨**: `is_retry`(재번역 힌트) 요청에
  캐시 조회 가드가 없어서, 문제로 지적된 바로 그 번역을 캐시에서 다시
  가져와 반환 → AI 재호출 자체가 안 일어남. TM은 원래 이 가드가 있었음
  (이유: TM 자체에 결함 있으면 무한 재시도 루프 위험) — 캐시에도 동일 가드
  추가 (`openai_compat_worker.py`, `claude_translation_worker.py`).
  `claude_translation_worker.py`는 TM 쪽에도 이 가드가 원래 없었음 — 같이 추가.

### 429 요청 제한 및 동시성

`gui/openai_compat_worker.py`:
- **429 재시도 로직 부재**: TM 조회 최적화로 요청 속도가 빨라지면서, Gemini
  무료 티어의 분당 10회 제한을 순식간에 초과 → 대량 429 발생, 재시도 없이
  즉시 실패 처리되던 문제. `Retry-After` 헤더 존중 + 지수 백오프(최대 5회)
  추가.
- **중복 문자열 API 재사용 부재 → 사전 스캔 방식으로 통일**: 배치에 동일
  원문이 여러 번 있을 때(`"Chunks (105 Credits)"` x50 등), 병렬 작업자 수만큼
  동시에 캐시 미스 상태로 API를 각각 호출하는 문제. 처음엔 락/이벤트 기반
  in-flight 병합으로 구현했으나, `ollama_worker.py`에 이미 있던 더 안전한
  사전 스캔(pre-flight scan) + 결과 팬아웃 방식으로 재작성 (경쟁 상태 자체가
  발생 불가능한 구조). `claude_translation_worker.py`도 동일하게 통일.
  - 부수 발견: `claude_translation_worker.py`가 `TranslationCache.put()`
    (존재하지 않는 메서드, 실제로는 `set()`)을 호출해 성공한 번역도 예외로
    실패 처리되던 버그, 그리고 캐시 키 포맷이 다른 두 워커와 달라 수동 교정이
    Claude 백엔드에서 인식 안 되던 문제도 같이 수정.
  - 리팩터링 중 발견한 후속 버그: 일반 중복과 "강제 재번역" 요청이 같은
    캐시 키를 공유해 팔로워 목록을 서로 가로채 잘못된 결과로 덮어쓰는 문제 →
    팔로워 목록 "소유권"을 명시적으로 추적하도록 수정, 10회 반복 재현 테스트로 검증.

### 테이블 정렬 및 번역 중 데이터 무결성

`gui/string_table.py`, `gui/main_window.py`:
- **열 클릭 정렬 기능 추가**: FormID/Original/Translated/EDID/Type/Status
  전 열에서 오름차순/내림차순 토글 가능.
- **정렬이 번역 배치 중 행을 오염시키는 버그**: 번역 결과는 배치 시작 시점의
  행 "위치"(index)로 라우팅되는데, Qt는 정렬이 켜진 상태에서 데이터가
  바뀌면 자동으로 재정렬을 시도함 → 배치 도중 재정렬되면 이미 전송된 요청의
  결과가 엉뚱한 행에 적용됨 (실제로 재현: `Unobtainium` 행에
  `"Receiver that is destroyed..."` 번역문이 들어가는 사고 확인).
  - 1차 수정: `_start_translation`에 정렬 잠금 추가 — 그러나 "전체 번역"만
    켜지는 자체 검토(품질검사 후 재번역) 파이프라인이 `_start_translation`을
    거치지 않고 별도 경로로 배치를 시작해 여전히 무방비였음.
  - 2차 수정: 배치를 시작하는 경로 4곳(`_start_translation`,
    `_retranslate_with_hints`, `_ai_fix_with_hints`, TXT 모드 번역) 전부에
    잠금 추가, 무조건 해제하던 로직을 "체인이 진짜로 끝나는 지점"
    (`_announce_batch_complete` 또는 `_self_review_finish`)으로 재배치.
  - 이중 안전장치: `StringTableModel.sort()` 자체에도 번역 진행 중엔
    무조건 무시하는 락 추가 — `setSortingEnabled` 토글 하나에만 의존하지
    않도록 방어적으로 설계.

### 신규 기능

- **Force Retranslate Selected (Ctrl+Alt+T)**: `translate_selected()`가 이미
  번역된 행은 조용히 건너뛰는 사양이라, 버그 수정 후 재번역이 필요한 행을
  강제로 다시 돌릴 방법이 없던 문제 해결. 번역칸을 비운 뒤 정상 번역 흐름 재사용.
- **Apply to All Identical Originals (Ctrl+Alt+D)**: 동일 원문이 여러 번
  등장할 때 AI가 매번 다르게 번역하는 문제(예: `"Heretical Writings"`가
  `"이단 문헌"`/`"이단의 저작"`로 제각각)를 근본적으로 우회 — 한 행을
  검수한 뒤 파일 내 동일 원문 전체에 그 번역을 그대로 복제.
- **Translation Memory 뷰어**: 상태바에 상시 "TM: N entries" 표시(클릭 시
  뷰어 열림) + 검색 가능한 브라우저 다이얼로그. TM이 실제로 로드됐는지
  확인할 방법이 기존엔 1회성 상태 메시지뿐이었음.
- **번역 출처 색상 표시**: TM/캐시/API 중 어디서 왔는지 행 배경색으로 구분
  (캐시=`#03593E`, API=`#0C906B`, TM/수동교정=무색). 세 워커의
  `translation_ready` 시그널에 출처 인자를 추가해 전달. 완료 메시지 및 자체
  검토 요약에도 `(TM: N, Cache: N, API: N)` 통계 표시.
- **포터블 모드**: exe 옆에 `PortableData` 폴더가 있으면 설정/캐시를 그
  안에 저장(배포용), 없으면 기존 `%APPDATA%` 그대로 사용(자동 감지,
  기존 설치에 영향 없음).

### UI/UX 개선

- 설정 화면 "다른 이름으로 저장" 다이얼로그가 매번 기본 홈 폴더로 초기화되던
  문제 → `QSettings`에 마지막 저장 폴더 기억.
- `Ctrl+Shift+A` 단축키가 "전체 번역"과 "오디오 미리듣기 패널"에 중복 등록되어
  전체 번역이 눌리지 않던 문제 → 오디오 패널을 `Ctrl+Shift+U`로 이동.
- 크래시 복구 스냅샷이 저장(Save/다른 이름으로 저장) 후에도 안 지워져서,
  정상 저장했는데도 다음 실행 시 "복원하시겠습니까?"가 계속 뜨던 문제 →
  저장 성공 시점에 스냅샷 삭제하도록 수정.
- 첫 실행 안내(Quick-Start Tips) 다이얼로그를 도움말 메뉴에서 언제든 다시
  열 수 있도록 분리, 이후 사용자 요청으로 **매 실행 시 항상 표시**하도록 변경.
  단축키 목록에 `Ctrl+S`/`Ctrl+Shift+S`/`Ctrl+T`/`Ctrl+Alt+T`/`Ctrl+Shift+A`/
  `Ctrl+Alt+D`/`Ctrl+F`/`Shift+F7`/`Ctrl+R`/`Ctrl+F7` 등 추가, 실제 바인딩과
  달랐던 옛 `Ctrl+A` 항목 수정.

### 현지화 완성

- `gui/translations/ko_KR.qm`이 오래되어 `.ts`에 이미 있던 최신 한국어
  번역(1625개 중 사실상 전부)이 실제 앱에는 반영 안 되고 있던 문제 →
  `pyside6-lrelease`로 재컴파일.
- `self.tr()`로 감싸지지 않아 애초에 번역 카탈로그에 들어갈 수 없었던
  하드코딩 영어 문자열 66개 발견 (`diff_viewer.py`, `nexusmods_upload_dialog.py`,
  `main_window.py`, `app_settings.py`, `audio_preview_panel.py`) → 전부
  `self.tr()`/`QCoreApplication.translate()`로 감싸고 `.ts`에 한국어 번역
  추가 후 재컴파일. `.ts` 총 1625 → 1691개.

---

## 알려진 미해결 이슈

- `Knock yourself out` 같은 영어 이디엄은 로컬 모델(EXAONE 등)이 처리 못함;
  Gemini/ChatGPT 백엔드 사용 권장 (Settings > Translation Backend > Cloud AI)
- 반말/존댓말 구분은 로컬 7.8B급 모델의 근본적 한계 (세계관 지식 부족).
  Gemini 3.5 Flash는 유의미하게 나으나 완벽하지 않음 — Rule 11(맥락 기반
  반말/존댓말 가이드)로 개선 시도했으나 지속적인 검증 필요.
- 원본 번역 모델(`translategemma3-st`)은 개발자가 NexusMods에서 미배포 상태로
  확인함 — 현재는 EXAONE 3.5 또는 Gemini/ChatGPT 백엔드 사용.
- `.ts`/`.qm`은 수동 동기화 방식 — 새 UI 문자열을 `self.tr()`로 추가한 뒤엔
  `.ts`에 번역을 채우고 `pyside6-lrelease`로 재컴파일해야 실제 화면에 반영됨
  (자동화된 빌드 스텝 없음, 3차 세션에서 이 격차로 인한 "메뉴가 영어로 보임"
  이슈가 실제로 발생했었음).

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
