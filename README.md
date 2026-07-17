# BSEK — Bethesda Strings Editor: Korean Edition

> **이 프로젝트는 [0xra0/bethesda-strings-editor](https://github.com/0xra0/bethesda-strings-editor)의 포크입니다.**
> 원본은 다국어(9개 공식 언어 + 러시아어/우크라이나어) 지원 도구이며, 이 포크(BSEK)는
> **한국 이용자를 위해 영어 → 한국어 Starfield 모드 번역에 특화**해 개조한 버전입니다.
> 원본 도구나 다른 언어 지원이 필요하면 위 원본 저장소를 이용하세요.

AI 기반 Starfield 모드 로컬라이제이션 도구. `.strings`, `.dlstrings`, `.ilstrings`,
BA2 아카이브, ESP/ESM 플러그인 파일, Starfield 인터페이스 TXT 파일을 영어에서
한국어로 번역합니다. 로컬 Ollama 모델 또는 클라우드 AI(Gemini/ChatGPT/Claude)를
번역 백엔드로 사용하며, 번역 후 정확성·자연스러움·말투(존댓말/반말)까지 검토해주는
Claude AI 어시스턴트, 자체 품질 검사, 번역 메모리(TM) 등을 갖춘 전체 로컬라이제이션
워크플로우를 제공합니다.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PySide6](https://img.shields.io/badge/UI-PySide6%20%2F%20Qt6-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython)
[![Ollama](https://img.shields.io/badge/AI-Ollama%20(local)-0D0D0D?style=for-the-badge&logo=ollama&logoColor=white)](https://ollama.com)
[![Claude](https://img.shields.io/badge/AI-Claude%20API-7C3AED?style=for-the-badge&logo=anthropic&logoColor=white)](https://claude.ai)
[![License](https://img.shields.io/badge/License-MIT-F59E0B?style=for-the-badge)](LICENSE)

---

## 목차

1. [사전 준비물](#사전-준비물)
2. [설치](#설치)
3. [빠른 시작 (사용법)](#빠른-시작-사용법)
4. [번역 메모리(TM)와 캐시](#번역-메모리tm와-캐시)
5. [추천 Ollama 모델](#추천-ollama-모델)
6. [추천 환경 세팅](#추천-환경-세팅)
7. [Claude AI 어시스턴트](#claude-ai-어시스턴트)
8. [클라우드 AI 배치 번역 (선택)](#클라우드-ai-배치-번역-선택)
9. [지원 언어](#지원-언어)
10. [원본 대비 주요 변경점](#원본-대비-주요-변경점)
11. [원본에서 계속 지원하는 기능](#원본에서-계속-지원하는-기능)
11. [문제 해결](#문제-해결)
12. [소스에서 빌드/실행 (개발자용)](#소스에서-빌드실행-개발자용)
13. [변경 이력 및 라이선스](#변경-이력-및-라이선스)

---

## 사전 준비물

BSEK 자체는 압축 풀고 실행 파일만 더블클릭하면 되는 포터블 프로그램입니다.
번역을 실제로 돌리려면 아래 중 **최소 하나**의 번역 백엔드가 필요합니다.

| 방법 | 필요한 것 | 비용 | 특징 |
|---|---|---|---|
| **로컬 Ollama** (권장) | [Ollama](https://ollama.com) 설치 + GPU(권장, VRAM 8GB+) | 무료 | 인터넷 불필요, 속도는 GPU 성능에 좌우 |
| **클라우드 AI (Gemini/ChatGPT)** | API 키 | API 종량 과금 | 배치 번역 품질이 준수하고 빠름 |
| **Claude API** (AI 어시스턴트용) | [Anthropic API 키](https://console.anthropic.com) | API 종량 과금 | 번역 검토/제안 전용, 배치 번역에도 쓸 수 있음 |

로컬 Ollama만 쓸 경우에도 GPU 없이 CPU로 돌아가긴 하지만 매우 느립니다.
NVIDIA GPU + 최소 8GB VRAM을 권장하며, 아래 [추천 Ollama 모델](#추천-ollama-모델)의
26B 모델을 쓰려면 16GB급을 권장합니다.

---

## 설치

### 1. BSEK 다운로드

[Releases](../../releases) 페이지에서 최신 버전의 `bethesda-strings-editor-windows-x64.zip`을
받아 원하는 폴더에 압축을 풉니다. 압축 해제 후 구조는 다음과 같습니다:

```
bethesda-strings-editor\
├─ bethesda-strings-editor.exe   ← 이걸 더블클릭해서 실행
├─ PortableData\                  ← 설정·캐시·용어집이 여기 저장됨 (폴더째 옮겨도 그대로 동작)
└─ (기타 실행에 필요한 파일들)
```

Python이나 별도 런타임 설치가 필요 없습니다. `bethesda-strings-editor.exe`를
더블클릭하면 바로 실행됩니다.

> ⚠️ Windows Defender/백신이 처음 실행 시 경고를 띄울 수 있습니다 (서명되지 않은
> 개인 배포 실행 파일이라 그렇습니다). "추가 정보 → 실행"으로 진행하세요.

### 2. Ollama 설치 (AI 품질 검사를 쓰려면 사실상 필수)

Cloud AI/Claude만으로 배치 번역·강제 재번역·일반 품질 검사(Ctrl+F7)까지는
Ollama 없이도 전부 됩니다. 다만 **"AI 품질 검사"(설정의 별도 체크박스)는
선택한 번역 백엔드와 무관하게 항상 Ollama를 사용**하도록 돼 있어서, 이 기능을
쓰려면 Cloud AI/Claude만 쓰는 경우에도 Ollama가 설치·실행 중이어야 합니다.

1. [ollama.com](https://ollama.com)에서 설치 프로그램을 받아 설치합니다.
2. 설치 후 자동으로 백그라운드 서비스(트레이 아이콘)로 실행됩니다.
3. PowerShell을 열고 원하는 모델을 받습니다 (아래 [추천 모델](#추천-ollama-모델) 참고):
   ```powershell
   ollama pull gemma4:26b-a4b-it-qat
   ```

### 3. (선택) Claude API 키 발급

번역 검토/제안 기능(AI 어시스턴트 패널)을 쓰려면 [Anthropic Console](https://console.anthropic.com)에서
API 키를 발급받아 BSEK 안에서 입력하면 됩니다 (아래 [Claude AI 어시스턴트](#claude-ai-어시스턴트) 참고).
이 키는 시스템 키링(또는 암호화 파일)에 안전하게 저장됩니다.

---

## 빠른 시작 (사용법)

1. **파일 열기** — `File > Open`으로 번역할 `.esp`/`.esm`/`.strings`/BA2 등을 엽니다.
2. **번역 백엔드 선택** — `Settings`에서 Local LLM(Ollama) 또는 Cloud AI를 고르고,
   모델을 선택합니다. (Ollama라면 미리 `ollama pull`로 받아둔 모델이 드롭다운에 보입니다.)
3. **전체 번역** — `Translate All` (또는 선택한 행만 `Translate Selected`)로 배치 번역을 시작합니다.
   진행 중 상태바에서 TM/캐시/API 출처별 통계를 실시간으로 확인할 수 있습니다.
4. **(선택) 품질 검사** — `Ctrl+F7`로 규칙 기반 품질 검사를 돌립니다. 문제 있는 행이 빨간색/노란색으로
   표시됩니다.
5. **(선택) 애매한 문자열만 정밀 검토** — 문제로 표시됐거나 말투가 걱정되는 문자열을 선택하고
   `Ctrl+Shift+C`로 Claude AI 어시스턴트 패널을 열어 "번역 검토"를 눌러봅니다.
6. **저장** — `File > Save`로 원본 파일 형식 그대로 저장합니다.

### 자주 쓰는 단축키

| 단축키 | 기능 |
|---|---|
| `Ctrl+Alt+T` | 강제 재번역 (이미 번역돼 있어도 캐시 무시하고 새로 번역) |
| `Ctrl+Alt+D` | 선택한 행의 번역을 파일 내 동일 원문 전체에 일괄 적용 |
| `Ctrl+F7` | 품질 검사 실행 |
| `Ctrl+Shift+C` | Claude AI 어시스턴트 패널 열기/닫기 |
| `Ctrl+Alt+K` | 일관성 검사기 |
| `Ctrl+K` | 커맨드 팔레트 |
| `F11` | Zen/Focus 모드 |

---

## 번역 메모리(TM)와 캐시

BSEK는 번역을 두 가지 별도의 저장소에 기록합니다. 헷갈리기 쉬운데, 하는 역할이
다릅니다.

- **번역 메모리(TM)** — 외부에서 불러온 참고 자료입니다. 공식 로컬라이제이션이나
  다른 사람이 이미 번역해둔 파일을 `Translation > Load Translation Memory…`로
  읽어들이면, 원문이 정확히 일치하는 문자열은 AI 호출 없이 TM의 번역을 그대로
  가져다 씁니다. **큐레이션된(사람이 검수한) 참고 자료**로 취급되어 우선순위가
  가장 높습니다.
- **캐시** — BSEK가 **자기가 직접 번역한 결과를 스스로 기억해두는 저장소**입니다.
  같은 원문(+같은 모델+같은 설정)을 다시 번역할 일이 생기면, API를 또 호출하지
  않고 이전에 냈던 결과를 그대로 재사용합니다. 그래서:
  - 모드가 업데이트돼서 파일을 다시 열고 재번역해도, 안 바뀐 문자열들은 즉시
    캐시에서 채워지고 **새로 추가/변경된 문자열만** 실제로 API를 호출합니다.
  - 파일 안에 완전히 동일한 원문이 여러 번 나오면, 한 번만 API를 호출하고
    나머지는 캐시로 채워집니다.

### 캐시에 남은 오역을 고치면, 그 수정도 캐시에 반영됩니다

아래 방법 중 어떤 걸로 번역을 고치든, **고친 내용이 캐시에도 같이 저장**됩니다.
그래서 나중에 같은 원문을 다시 번역하거나 파일의 다른 곳에 같은 원문이 있으면,
AI가 예전 오역을 다시 반복하는 대신 이미 고쳐둔 버전을 그대로 씁니다.

- 문자열 편집 팝업에서 "번역된 텍스트" 직접 수정 후 OK
- 표에서 셀 더블클릭해서 인라인으로 직접 수정
- 고급 검색/바꾸기(`찾기/바꾸기` 다이얼로그)로 일괄 치환
- Claude 어시스턴트에서 "번역으로 사용"으로 제안 적용

즉 한 번 손으로 고쳐두면 그 수정이 그냥 그 자리에서만 끝나는 게 아니라, **이후
같은 문자열이 나올 때마다 계속 재사용**됩니다. 반대로 용어집(Glossary)에서 용어를
하나 고치면, 그 용어가 실제로 들어간 문자열들의 캐시만 골라서 자동으로 무효화되고
나머지는 그대로 유지됩니다 (용어 하나 고쳤다고 전체를 다시 번역할 필요 없음).

### "무조건 새로 번역"이 필요할 때는 강제 재번역

캐시가 있으면 같은 문자열은 기본적으로 재사용되기 때문에, "이 캐시 값 자체가
마음에 안 드니 새로 뽑고 싶다"면 `Ctrl+Alt+T`(강제 재번역)를 쓰세요. 이건 캐시를
무시하고 실제로 API를 다시 호출한 뒤, 새 결과로 캐시를 덮어씁니다.

### 번역 출처 색상

표에서 각 행의 배경색으로 그 번역이 어디서 왔는지 바로 알 수 있습니다.

| 색상 | 출처 | 의미 |
|---|---|---|
| 🟩 진한 청록 (`#03593E`) | 캐시 | 예전에 이미 번역해둔 걸 재사용함 (API 호출 없었음) |
| 🟢 밝은 녹색 (`#0C906B`) | API | 방금 실제로 AI를 호출해서 새로 번역함 |
| (기본 배경색, 별도 강조 없음) | TM / 수동 편집 | 번역 메모리에서 가져왔거나, 사람이 직접 입력/수정함 |

배치 번역이 끝나면 상태바/완료 메시지에 TM·캐시·API 건수가 각각 몇 건이었는지도
표시됩니다.

---

## 추천 Ollama 모델

아래는 이 포크 관리자가 실제로 사용 중인 조합입니다 (RTX 4080, VRAM 16GB 기준).

| 모델 | 용도 | 다운로드 용량 | 비고 |
|---|---|---|---|
| **`gemma4:26b-a4b-it-qat`** | 주력 번역 모델 | 약 15GB | MoE(26B 중 4B만 활성화)라 크기 대비 빠름. 번역 정확도가 가장 좋음 |
| **`gemma4:12b-it-qat`** | 가벼운 대안 | 약 7GB | VRAM이 빠듯할 때, 또는 빠른 초벌 번역용 |

```powershell
ollama pull gemma4:26b-a4b-it-qat
ollama pull gemma4:12b-it-qat
```

받은 모델은 BSEK 환경설정의 모델 드롭다운에서 자동으로 인식됩니다. 아직 안 받은
모델명을 미리 등록해두고 싶다면 드롭다운 옆의 **Add** 버튼으로 이름만 저장해둘 수도
있습니다 (나중에 `ollama pull`로 실제로 받으면 바로 작동).

### VRAM 관련 주의사항

`gemma4:26b-a4b-it-qat`는 가중치만 약 15GB라, **16GB급 GPU에서는 VRAM이 거의 꽉 찹니다.**
BSEK 하단 상태바의 GPU 사용률(`GPU N% · 사용량/전체 · 온도`)로 항상 확인할 수 있습니다.
90% 이상이면 여유가 거의 없다는 뜻이니:
- 다른 GPU 사용 프로그램(브라우저 하드웨어 가속, 게임 등)과 동시 실행을 피하세요.
- 버벅이거나 실패하면 환경설정에서 컨텍스트 제한을 낮추거나, `gemma4:12b-it-qat`로 바꿔보세요.
- BSEK는 매 요청에 `keep_alive: -1`을 보내 모델을 VRAM에 계속 로드해둡니다(재로드
  지연 방지 목적). 번역을 한동안 안 쓸 예정이면 `ollama stop <모델명>`으로 수동으로
  내려서 VRAM을 다른 용도로 돌려줄 수 있습니다.

---

## 추천 환경 세팅

`Settings` 창에서 아래와 같이 맞추는 것을 권장합니다.

| 항목 | 권장값 | 이유 |
|---|---|---|
| 자동 용어 보호 활성화 | ✅ 켜기 | 게임 태그(`<Alias=…>`, `[Attack]` 등)가 번역 중 깨지는 것 방지 |
| 고유 명사 및 설정 용어 보호 | ✅ 켜기 | 세력/캐릭터/자원 이름 등이 임의로 번역되는 것 방지 |
| 캐시 사용 | ✅ 켜기 | 동일 문자열 재번역 시 API 호출 절약 |
| 컨텍스트 제한 | 모델 기본값 또는 16384 | 너무 낮으면 긴 대사가 잘릴 수 있음 |
| 자동 후속 검토(self-review) | ✅ 켜기 (전체 번역 후) | 번역 직후 규칙 기반 품질 검사를 자동으로 한 번 더 돌려 명백한 오류를 스스로 재시도 |
| AI 품질 검사 | 선택 | 켜면 현재 선택된 Ollama 모델로 의미론적 검사까지 추가 수행 (느려짐) |
| 용어집 (Glossary) | 사용 | 팀 왈도 한글 패치 용어집이 기본 내장되어 있음 — 자체 용어 추가도 가능 |
| 캐릭터 프로필 | 주요 NPC에 설정 | 화자별 말투(존댓말/반말, 성격)를 지정해두면 번역·검토 모두에 반영됨 |

---

## Claude AI 어시스턴트

`Ctrl+Shift+C`로 여는 도킹 패널입니다. Anthropic API 키가 필요합니다(위 [사전 준비물](#사전-준비물) 참고).

- **번역 검토** — 선택한 행 하나의 원문·번역문을 Claude에게 보내 정확성, 자연스러움,
  게임 태그 보존, 그리고 **말투(존댓말/반말)가 맥락에 맞는지**까지 검토받습니다.
  캐릭터 프로필이 지정된 문자열이면 그 인물의 확립된 말투를 우선 기준으로 삼습니다.
- **번역 제안** — Claude에게 처음부터 번역을 새로 받아봅니다.
- **번역으로 사용** — 검토/제안 결과에 포함된 개선안을 표에 바로 적용합니다. 여러
  안이 제시된 경우 선택 창이 뜨니 원하는 것을 고르면 됩니다.

---

## 클라우드 AI 배치 번역 (선택)

`Settings > Translation Backend > Cloud AI`에서 설정합니다. OpenAI 호환 API를
제공하는 서비스라면 Base URL만 바꿔서 아무거나 연결할 수 있습니다.

| 항목 | 값 |
|---|---|
| Base URL 예시 (Gemini) | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| Base URL 예시 (ChatGPT) | `https://api.openai.com/v1` |
| API 키 발급 (Gemini) | https://aistudio.google.com/apikey |

---

## 지원 언어

| Code | Language | 비고 |
|---|---|---|
| `en` | English | 번역 원문 (기본 소스) |
| `ko` | Korean | 번역 대상 (기본 타겟) |
| `ja` | Japanese | 참고용 — 베데스다 공식 일본어 로컬라이제이션의 존댓말/반말 구분이 한국어와 가장 가까운 참고 자료가 될 수 있어 남겨둠 (번역 대상 아님) |

---

## 원본 대비 주요 변경점

- **클라우드 AI 백엔드 내장** — Gemini/ChatGPT 등 OpenAI 호환 API를 GUI에서 바로 설정, 키는 시스템 키링에 저장.
- **Claude AI 어시스턴트 패널** — 개별 문자열 검토/제안/적용, 말투 일관성 확인, 한국어 응답.
- **프롬프트 에디터** (`Translation > Prompt Editor…`) — 페르소나/규칙을 GUI에서 직접 편집, 프리셋 관리, 실시간 미리보기.
- **한국어 중심 언어 구성 + 전체 메뉴 한글화** (`gui/translations/ko_KR.ts`/`.qm`).
- **번역 품질 튜닝** — 팀 왈도 한글 패치 용어집 연동, 퀘스트 로그 존댓말 명령형 규칙, 화자 맥락 기반 반말/존댓말 판단, TM 조회 속도·정확도 개선.
- **모델 관리 개선** — Ollama 모델을 설정에서 바로 추가/저장, AI 품질 검사가 별도 모델 대신 현재 번역 모델을 그대로 사용.
- **캐시/재번역 정확도 개선** — 용어집 수정 시 관련 문자열만 선택적으로 캐시 무효화, 강제 재번역이 실제로 캐시를 무시하고 새로 번역, 태그만 남고 내용이 사라지는 실패를 자동 감지·재시도.
- **번역 메모리 뷰어**, **동일 원문 일괄 적용** (`Ctrl+Alt+D`), **강제 재번역** (`Ctrl+Alt+T`), **열 클릭 정렬**, **포터블 배포**.
- **정리** — 한국어와 무관한 우크라이나어 전용 기능 제거, 업데이트 확인 대상을 이 포크 저장소로 변경.

상세 변경 이력은 [CHANGES.md](CHANGES.md)를 참고하세요.

---

## 원본에서 계속 지원하는 기능

- **파일 지원**: `.strings`/`.dlstrings`/`.ilstrings`, BA2 아카이브, ESP/ESM 플러그인,
  VMAD(Papyrus) 스크립트 속성, Starfield 인터페이스 TXT, xTranslator SST XML,
  NexusMods 번역 브라우저.
- **품질 검사**: 20개 이상 자동 검사(태그 누락/추가, 미번역, 원문 언어 잔존, 줄바꿈
  불일치 등), Hunspell 맞춤법 검사, 폰트/글리프 검사기, 자동 수정, 일관성 검사기.
- **리뷰 도구**: 실제 게임 폰트 미리보기, 대화 트리 시각화, 오디오/TTS 미리듣기,
  버전 비교, Diff 뷰어, 고급 검색/바꾸기.
- **UI/워크플로우**: Zen 모드, 멀티모니터, 커맨드 팔레트, 번역 세션, 매크로 녹화,
  16개 테마, 크래시 복구.

전체 상세 기능 목록은 원본 저장소의 README를 참고하세요.

---

## 문제 해결

**Q. 실행이 안 되거나 Windows Defender가 막아요.**
서명되지 않은 개인 배포 실행 파일이라 그렇습니다. "추가 정보 → 실행"으로 진행하세요.

**Q. Ollama 모델이 드롭다운에 안 보여요.**
`ollama list`로 실제로 받아졌는지 먼저 확인하세요. 방금 받았다면 환경설정의
"새로 고침" 버튼을 눌러보세요.

**Q. 번역이 갑자기 다 실패해요 / "Empty response" 에러가 계속 떠요.**
VRAM 부족일 가능성이 높습니다. 상태바 GPU 사용량을 확인하고, 다른 GPU 프로그램을
끄거나 더 가벼운 모델(`gemma4:12b-it-qat`)로 바꿔보세요.

**Q. 강제 재번역을 해도 번역이 그대로예요.**
이미 최신 버전(캐시를 실제로 무시하고 재번역하도록 수정됨)인지 확인하세요. 그래도
같은 결과가 나온다면 모델 자체가 그 문자열에 대해 일관되게 같은 답을 내는 것일
수 있습니다 — Claude 어시스턴트로 개별 검토를 권장합니다.

**Q. 설정을 바꿨는데 다음 실행 시 안 남아있어요.**
`PortableData` 폴더가 실행 파일과 같은 위치에 있는지 확인하세요. 이 폴더가 없으면
설정이 사용자 프로필 폴더에 저장되니, 폴더째로 옮길 계획이면 항상 함께 있어야 합니다.

---

## 소스에서 빌드/실행 (개발자용)

일반 사용자는 이 섹션이 필요 없습니다 — 위 [설치](#설치)의 패키지 배포판을 쓰세요.

```bash
pip install -r requirements.txt
python main.py
```

핵심 의존성: `PySide6>=6.6`, `requests>=2.31`, `cryptography>=43.0`
선택 의존성: `keyring`(키링 저장), `anthropic`(Claude 백엔드), `curl-cffi`(NexusMods
무료 계정 다운로드), `py7zr`(`.7z` 해제).

UI 번역 파일을 수정했다면:
```bash
./scripts/compile_translations.sh
```
> `.ts` 파일을 다시 생성(`lupdate`)할 때는 **반드시 `gui/*.py` 전체**를 대상으로
> 실행하세요. 파일 하나만 대상으로 돌리면 나머지 파일의 기존 번역이 전부
> obsolete로 표시되어 컴파일 시 통째로 빠져버립니다.

패키징(PyInstaller):
```bash
pyinstaller bethesda_strings_editor.spec
```
`v*` 태그를 푸시하면 GitHub Actions가 Windows/Linux 빌드를 자동으로 만들어 릴리스에 올립니다.

테스트:
```bash
python -m pytest tests/
```

프로젝트 구조 개요:

```
bethesda_strings/        순수 파이썬 파싱 라이브러리 (Qt 비의존)
gui/                      PySide6 애플리케이션 레이어
  main_window.py            최상위 윈도우, 파일 I/O, 번역 오케스트레이션
  ollama_worker.py           로컬 Ollama 번역 워커 + 프롬프트 빌더
  openai_compat_worker.py    클라우드(OpenAI 호환) 번역 워커
  claude_translation_worker.py  Claude API 배치 번역 워커
  claude_chat_panel.py       Claude AI 어시스턴트 패널
  prompt_editor_dialog.py    프롬프트 에디터 GUI
  quality_checker.py         규칙 기반 품질 검사
  translation_memory.py      번역 메모리
  translation_cache.py       번역 캐시
  glossary.py                용어집
  app_settings.py            설정 저장/로드
gui/translations/         UI 다국어 번역 (.ts/.qm)
tests/                    pytest 테스트 스위트
```

---

## 변경 이력 및 라이선스

상세 변경 이력: [CHANGES.md](CHANGES.md)

MIT — [LICENSE](LICENSE) 참고. 원본 프로젝트인
[0xra0/bethesda-strings-editor](https://github.com/0xra0/bethesda-strings-editor) 역시 MIT 라이선스입니다.
