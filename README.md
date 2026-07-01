# BSEK — Bethesda Strings Editor: Korean Edition

> **이 프로젝트는 [0xra0/bethesda-strings-editor](https://github.com/0xra0/bethesda-strings-editor)의 포크입니다.**
> 원본은 다국어(9개 공식 언어 + 러시아어/우크라이나어/한국어) 지원 도구이며,
> 이 포크(BSEK)는 **한국 이용자를 위해 영어 → 한국어 Starfield 모드 번역에 특화하여 개조**한
> 버전입니다. 원본 도구 및 다른 언어 지원이 필요하시면 위 원본 저장소를 이용해주세요.

AI 기반 Starfield 모드 로컬라이제이션 도구. `.strings`, `.dlstrings`, `.ilstrings`,
BA2 아카이브, ESP/ESM 플러그인 파일, Starfield 인터페이스 TXT 파일을 영어에서
한국어로 번역합니다. Gemini/ChatGPT 같은 클라우드 AI 또는 로컬 Ollama 모델을 사용하며,
번역 프롬프트를 GUI에서 직접 편집·저장할 수 있고, 전체 품질 검수 워크플로우를
포함합니다.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PySide6](https://img.shields.io/badge/UI-PySide6%20%2F%20Qt6-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython)
[![Ollama](https://img.shields.io/badge/AI-Ollama%20(local)-0D0D0D?style=for-the-badge&logo=ollama&logoColor=white)](https://ollama.com)
[![Gemini](https://img.shields.io/badge/AI-Gemini%20%2F%20OpenAI%20compatible-4285F4?style=for-the-badge&logo=googlegemini&logoColor=white)](https://aistudio.google.com/apikey)
[![Claude](https://img.shields.io/badge/AI-Claude%20API-7C3AED?style=for-the-badge&logo=anthropic&logoColor=white)](https://claude.ai)
[![License](https://img.shields.io/badge/License-MIT-F59E0B?style=for-the-badge)](LICENSE)

---

## BSEK에서 새로 추가/변경된 것 (원본 대비)

원본 프로젝트의 핵심 번역·QA 엔진은 그대로 유지하면서, 다음을 새로 추가하거나 바꿨습니다:

- **클라우드 AI 번역 백엔드 (GUI 내장)** — Gemini, ChatGPT 등 OpenAI 호환 API를
  `Settings > Translation Backend`에서 직접 선택하고 API 키를 입력할 수 있습니다.
  외부 프록시 서버를 따로 실행할 필요가 없습니다. 모델은 콤보박스에서 선택하거나
  직접 입력할 수 있고(`gemini-3.5-flash` 등), API 키는 시스템 키링에 안전하게 저장됩니다.
- **프롬프트 에디터** (`Translation > Prompt Editor…`) — 번역 프롬프트의 정체성
  (페르소나)과 스타일 규칙을 GUI에서 직접 편집할 수 있습니다.
  - 이름을 붙여 프리셋으로 저장/불러오기/이름변경/삭제
  - 실시간 미리보기(모델에 실제로 전송될 전체 프롬프트 확인)
  - 규칙 칸을 비워두면 BSEK 기본 규칙(게임 태그 보존, 대괄호 처리, 용어집 강제,
    퀘스트 명령형 어투, 반말/존댓말 가이드)이 자동 적용됩니다
  - 규칙 칸에 직접 입력하면 기본 규칙 전체를 대체합니다 — 다른 베데스다 게임
    (Skyrim, Fallout 등)이나 다른 언어쌍용으로 프롬프트를 처음부터 새로 작성할 때
    사용하세요. "베이스 규칙 복사" 버튼으로 기존 규칙을 불러와 이어서 편집할 수도
    있습니다.
- **한국어 중심 언어 구성** — 지원 언어를 English / Japanese / Korean 세 가지로
  정리했습니다. 일본어는 번역 대상이 아니라 **참고용**으로 남겨뒀습니다 —
  베데스다 공식 일본어 로컬라이제이션이 존댓말/반말 구분을 갖고 있어, 한국어와
  가장 가까운 참고 자료가 될 수 있기 때문입니다. 기본 번역 방향은 English → Korean.
- **메뉴 한글화** — 인터페이스 전체가 한국어로 번역되어 있습니다
  (`gui/translations/ko_KR.ts`/`.qm`, 1,589개 UI 문자열).
- **한국어 번역 품질 튜닝**:
  - 팀 왈도(Team Wallo) 한글 패치 용어집(2,067개 UI 용어) 연동
  - 퀘스트 목표/미션 로그는 서술형이 아닌 존댓말 명령형(~하십시오/~하세요)으로
    번역하도록 규칙 추가
  - 반말/존댓말은 화자의 맥락(거친 대사=반말 경향, 공적/상업적 대사=존댓말 경향)에
    따라 판단하도록 가이드
- **안정성 수정** — GPU 모니터 프리징, Windows Python 3.10 크래시, Settings
  저장 시 앱이 조용히 종료되는 버그, 다크 테마에서 텍스트가 안 보이던 저대비
  문제, 셀 선택 시 글자색이 안 보이던 문제 등 다수 수정.
- **업데이트 확인 대상 변경** — 원본은 업데이트 확인 및 "새 소식" 패널이 원본
  저장소(`0xra0/bethesda-strings-editor`)를 가리키고 있었습니다. BSEK는 이
  포크 저장소를 가리키도록 변경하여, 원본 프로젝트의 업데이트가 이 개조판을
  덮어쓰는 일이 없도록 했습니다.
- **실행 편의성** — 더블클릭으로 실행하는 Windows용 `run_bsek.bat` 런처 추가.
- **정리** — 한국어와 무관한 우크라이나어 전용 문법 검사 메뉴(성 일치 검사)를
  제거했습니다.

원본에 있던 다른 언어(독일어, 스페인어, 프랑스어, 이탈리아어, 폴란드어,
포르투갈어, 중국어 간체, 러시아어, 우크라이나어) 지원과 관련 기능(우크라이나어
문법 검사, ти/ви 존비법 검사 등)이 필요하시면 [원본 저장소](https://github.com/0xra0/bethesda-strings-editor)를
이용해주세요.

---

## 번역 백엔드

### 클라우드 AI (권장)

`Settings > Translation Backend > Cloud AI`에서 설정합니다.

| 항목 | 값 |
|------|-----|
| Base URL 예시 (Gemini) | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| Base URL 예시 (ChatGPT) | `https://api.openai.com/v1` |
| 추천 모델 | `gemini-3.5-flash` |
| API 키 발급 (Gemini) | https://aistudio.google.com/apikey |

OpenAI 호환 API를 제공하는 서비스라면 어디든 Base URL만 바꿔서 연결할 수 있습니다.

### 로컬 Ollama (대안)

로컬 모델을 계속 사용할 수도 있습니다. `Settings > Translation Backend > Local LLM`에서 설정하세요.

| 모델 | 용도 | 비고 |
|-------|---------|-----|
| `exaone3.5:7.8b-instruct-q8_0` | 한국어 특화 (LG AI Research) | 로컬 사용 시 권장 |
| `translategemma3-st` | 원본 프로젝트의 다국어 번역 모델 | 원본 GGUF 필요 |
| `qcgemma4-st` | 번역 품질 검사 (16개 이슈 코드) | [0xra/bethesda-qc](https://ollama.com/0xra/bethesda-qc) |

```bash
ollama pull exaone3.5:7.8b-instruct-q8_0
```

로컬 모델은 반말/존댓말 구분처럼 세계관 지식이 필요한 판단에서 클라우드 AI보다
품질이 낮은 경향이 있습니다. 가능하면 클라우드 AI 사용을 권장합니다.

---

## 지원 언어

| Code | Language | 비고 |
|------|----------|-----|
| `en` | English | 번역 원문 (기본 소스) |
| `ko` | Korean | 번역 대상 (기본 타겟) |
| `ja` | Japanese | 참고용 (반말/존댓말 대조) |

---

## 설치 및 실행

```bash
pip install -r requirements.txt
python main.py
```

Windows에서는 `run_bsek.bat`을 더블클릭하면 됩니다 (BSE 폴더 안에 위치해야 함).

핵심 의존성: `PySide6>=6.6`, `requests>=2.31`, `cryptography>=43.0`

선택 의존성:
- `keyring>=25.0` — API 키를 시스템 키링에 저장 (없으면 암호화 파일로 폴백)
- `anthropic>=0.25` — Claude API 백엔드 사용 시
- `curl-cffi>=0.7` — NexusMods 무료 계정 다운로드
- `py7zr>=0.20` — `.7z` 아카이브 압축 해제

로그는 stdout과 프로젝트 루트의 `translator.log`에 기록됩니다.

---

## 프롬프트 에디터 사용법

`Translation > Prompt Editor…` (또는 메뉴에서 "프롬프트 편집기") 로 엽니다.

- **Persona (정체성/역할)** — 번역가의 정체성 문장. 비워두면 기본값 사용.
- **Additional Rules (추가 규칙)** — 스타일 규칙. 비워두면 BSEK 기본 규칙
  (게임 태그 보존 포함) 자동 적용. 내용을 입력하면 기본 규칙 전체를 대체합니다.
- **Preset** — Save / Save As / Rename / Delete로 여러 프롬프트 세트를 관리.
- **Preview Full Prompt** — 실제로 모델에 전송될 프롬프트 전체를 확인.
- **베이스 규칙 복사** — BSEK 기본 규칙 전체를 Additional Rules 칸으로 불러와서
  이어서 편집할 수 있습니다.

⚠️ Additional Rules에 내용을 입력하면 게임 태그 보존(`%s`, `[[STRUCT_BREAK...]]` 등)
규칙도 함께 사라집니다. 다른 게임/언어쌍용으로 완전히 새로 작성하는 게 아니라면
"베이스 규칙 복사"로 먼저 불러온 뒤 수정하는 것을 권장합니다.

---

## 원본 기능 (계속 지원)

아래는 원본 프로젝트에서 물려받아 계속 사용 가능한 기능들입니다.

### 파일 지원
- 바이너리 문자열 파일: `.strings`, `.dlstrings`, `.ilstrings`
- BA2 아카이브 (Starfield v2, GNRL 타입)
- ESP/ESM 플러그인 (비-로컬라이즈드 플러그인)
- ESP/ESM 모드 업데이트 마이그레이션 — 구버전/신버전 플러그인 diff 후 기존 번역 이전
- VMAD 스크립트 속성 분석 (Papyrus)
- Starfield 인터페이스 TXT (`translate_en.txt`)
- xTranslator SST XML 가져오기/내보내기
- NexusMods 번역 브라우저 — 기존 번역 모드 검색/다운로드/병합

### 품질 검사
- 20개 이상 자동 검사 (누락/추가 태그, 미번역, 원문 언어 잔존, 줄바꿈 불일치 등)
- Hunspell 맞춤법 검사
- AI 품질 검사 모델 (`qcgemma4-st`)
- 폰트/글리프 검사기 — 번역 글자가 게임 내 폰트에서 네모(□)로 깨지는지 검사
- 자동 수정 (Auto-Fix All)
- 일관성 검사기 (Ctrl+Alt+K)

### 리뷰 도구
- Visual Context Preview (Ctrl+Shift+P) — 실제 게임 폰트로 미리보기
- Dialogue Tree Visualizer — 퀘스트 대화 트리 시각화
- Audio/TTS Preview (Ctrl+Shift+A) — 음성 합성 미리듣기, 원본 Wwise 음성 재생
- 버전 비교, Diff 뷰어, 고급 검색

### UI / 워크플로우
- Zen/Focus 모드 (F11)
- 멀티모니터 / 분리 패널
- Command palette (Ctrl+K), vim 스타일 내비게이션
- 번역 세션, 매크로 녹화
- 16개 내장 테마
- 크래시 복구, 보안 감사 로그

전체 상세 기능 목록은 원본 저장소의 README를 참고하세요.

---

## 프로젝트 구조

```
bethesda_strings/              순수 파이썬 파싱 라이브러리 (Qt 비의존)
  core.py                      .strings/.dlstrings/.ilstrings 바이너리 파서
  ba2_handler.py                BA2 아카이브 리더/라이터
  esp_handler.py                ESP/ESM 플러그인 파서
  txt_handler.py                Starfield 인터페이스 TXT 파서
  ...

gui/                           PySide6 애플리케이션 레이어
  main_window.py                최상위 윈도우, 파일 I/O, 번역 오케스트레이션
  ollama_worker.py               로컬 Ollama 번역 워커 + 프롬프트 빌더
                                 (DEFAULT_PERSONA, DEFAULT_CUSTOM_RULES,
                                 default_rules_block(), set_prompt_overrides())
  openai_compat_worker.py        BSEK 신규 — OpenAI 호환(Gemini/ChatGPT) 번역 워커
  openai_compat_client.py        BSEK 신규 — 클라우드 API 키 SecretStore 저장
  prompt_editor_dialog.py        BSEK 신규 — 프롬프트 에디터 GUI
  prompt_presets.py              BSEK 신규 — 프롬프트 프리셋 CRUD 로직
  claude_translation_worker.py   Claude API 번역 워커
  quality_checker.py             번역 후 QA 검사 (20개 이상 코드)
  term_protector.py              고유명사 보호 (플레이스홀더 치환)
  translation_cache.py           SHA-256 키 기반 번역 캐시
  glossary.py                    용어집 데이터 모델
  theme_manager.py               16개 내장 테마 + get_hint_color() 헬퍼
  updater.py                     GitHub 릴리스 업데이트 확인 (이 포크 저장소 대상)
  app_settings.py                설정 저장/로드 (JSON + QSettings)
  ...

gui/translations/
  ko_KR.ts / ko_KR.qm            한국어 UI 번역 (1,589개 문자열)

run_bsek.bat                    Windows 더블클릭 실행기
CHANGES.md                      이 포크에서의 상세 변경 이력
```

---

## 변경 이력

상세 변경 이력은 [CHANGES.md](CHANGES.md)를 참고하세요.

---

## 테스트

```bash
python -m pytest tests/
```

---

## 라이선스

MIT — [LICENSE](LICENSE) 참고. 원본 프로젝트인
[0xra0/bethesda-strings-editor](https://github.com/0xra0/bethesda-strings-editor) 역시 MIT 라이선스입니다.
