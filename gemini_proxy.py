#!/usr/bin/env python3
"""
Gemini → Ollama 프록시 서버 for Bethesda Strings Editor
=======================================================
BSE는 Ollama API(/api/generate) 형식으로 번역 요청을 보냅니다.
이 프록시는 그 요청을 받아 Gemini API로 변환해서 호출하고,
Ollama 형식 응답으로 돌려줍니다.

설치:
    pip install fastapi uvicorn google-genai

실행:
    python gemini_proxy.py --api-key YOUR_GEMINI_API_KEY
    또는 환경변수로: GEMINI_API_KEY=xxx python gemini_proxy.py

BSE 설정:
    Settings > Ollama AI Settings > API URL: http://localhost:11435
    Model: gemini-2.5-flash (또는 아무 이름이나 — Gemini 모델로 라우팅됨)

무료 API 키 발급:
    https://aistudio.google.com/apikey
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import Optional

# ── 의존성 체크 ───────────────────────────────────────────────────────────────
try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import StreamingResponse, JSONResponse
    import uvicorn
except ImportError:
    print("fastapi/uvicorn이 없습니다. 설치하세요:")
    print("    pip install fastapi uvicorn")
    sys.exit(1)

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    print("google-genai가 없습니다. 설치하세요:")
    print("    pip install google-genai")
    sys.exit(1)

# ── 설정 ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 번역 품질에 맞는 Gemini 모델
# - gemini-2.5-flash: 무료 티어, 품질 좋음, 추천
# - gemini-2.5-flash-lite: 더 빠름/저렴, 약간 품질 낮음
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

app = FastAPI(title="Gemini Ollama Proxy for BSE")
_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY 환경변수 또는 --api-key 인자가 필요합니다.")
        _client = genai.Client(api_key=api_key)
    return _client


# ── Ollama /api/tags (모델 목록) ────────────────────────────────────────────
@app.get("/api/tags")
async def list_models():
    """BSE가 Settings 열 때 모델 목록을 요청합니다."""
    return {
        "models": [
            {
                "name": "gemini-2.5-flash",
                "model": "gemini-2.5-flash",
                "modified_at": "2026-01-01T00:00:00Z",
                "size": 0,
                "digest": "gemini",
                "details": {"family": "gemini", "parameter_size": "unknown"},
            },
            {
                "name": "gemini-2.5-flash-lite",
                "model": "gemini-2.5-flash-lite",
                "modified_at": "2026-01-01T00:00:00Z",
                "size": 0,
                "digest": "gemini-lite",
                "details": {"family": "gemini", "parameter_size": "unknown"},
            },
        ]
    }


# ── Ollama /api/generate ────────────────────────────────────────────────────
@app.post("/api/generate")
async def generate(request: Request):
    """
    BSE가 번역 요청을 보내는 핵심 엔드포인트.
    Ollama 형식을 Gemini API 호출로 변환합니다.
    """
    body = await request.json()

    prompt: str = body.get("prompt", "")
    system: str = body.get("system", "")
    model_name: str = body.get("model", DEFAULT_GEMINI_MODEL)
    options: dict = body.get("options", {})
    do_stream: bool = body.get("stream", True)

    # Ollama 모델명 → Gemini 모델명 매핑
    # BSE Settings에서 어떤 모델명을 써도 Gemini로 라우팅
    gemini_model = _resolve_gemini_model(model_name)

    temperature = options.get("temperature", 0.3)
    max_tokens = options.get("num_predict", 4096)

    logger.info(
        f"번역 요청 | 모델: {gemini_model} | "
        f"프롬프트 길이: {len(prompt)} chars"
    )

    try:
        client = get_client()

        # Gemini API 호출 설정
        gen_config = genai_types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system if system else None,
        )

        if do_stream:
            return StreamingResponse(
                _stream_response(client, gemini_model, prompt, gen_config),
                media_type="application/x-ndjson",
            )
        else:
            response = client.models.generate_content(
                model=gemini_model,
                contents=prompt,
                config=gen_config,
            )
            text = response.text or ""
            return JSONResponse({
                "model": model_name,
                "response": text,
                "done": True,
                "total_duration": 0,
            })

    except Exception as e:
        logger.error(f"Gemini API 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _resolve_gemini_model(name: str) -> str:
    """
    BSE Settings에 넣은 모델 이름을 실제 Gemini 모델명으로 변환.
    gemini- 로 시작하면 그대로, 아니면 기본 모델 사용.
    """
    name = name.lower().strip()
    if name.startswith("gemini"):
        return name
    # translategemma3-st, exaone 같은 Ollama 모델명이 들어오면 기본 Gemini 사용
    return DEFAULT_GEMINI_MODEL


async def _stream_response(client, model_name, prompt, config):
    """Gemini 스트리밍을 Ollama NDJSON 스트리밍 형식으로 변환."""
    try:
        full_text = ""
        with client.models.generate_content_stream(
            model=model_name,
            contents=prompt,
            config=config,
        ) as stream:
            for chunk in stream:
                delta = chunk.text or ""
                full_text += delta
                # Ollama 스트리밍 형식: 각 청크를 JSON 줄로
                yield json.dumps({
                    "model": model_name,
                    "response": delta,
                    "done": False,
                }) + "\n"

        # 마지막 done=True 청크
        yield json.dumps({
            "model": model_name,
            "response": "",
            "done": True,
            "total_duration": 0,
        }) + "\n"

        logger.info(f"번역 완료 | 출력: {len(full_text)} chars")

    except Exception as e:
        logger.error(f"스트리밍 오류: {e}")
        yield json.dumps({
            "model": model_name,
            "response": "",
            "done": True,
            "error": str(e),
        }) + "\n"


# ── Ollama 상태 확인 엔드포인트들 ──────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "ok", "service": "Gemini Ollama Proxy for BSE"}


@app.get("/api/version")
async def version():
    return {"version": "0.1.0-gemini-proxy"}


@app.head("/")
async def head_root():
    return JSONResponse({})


# ── 진입점 ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Gemini → Ollama 프록시 (BSE용)")
    parser.add_argument(
        "--api-key", "-k",
        default="",
        help="Gemini API 키 (https://aistudio.google.com/apikey 에서 발급)",
    )
    parser.add_argument("--port", "-p", type=int, default=11435)
    parser.add_argument("--host", default="127.0.0.1")
    global DEFAULT_GEMINI_MODEL
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_GEMINI_MODEL,
        help=f"기본 Gemini 모델 (기본값: {DEFAULT_GEMINI_MODEL})",
    )
    args = parser.parse_args()

    if args.api_key:
        os.environ["GEMINI_API_KEY"] = args.api_key

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: Gemini API 키가 없습니다.")
        print("  방법 1: python gemini_proxy.py --api-key YOUR_KEY")
        print("  방법 2: set GEMINI_API_KEY=YOUR_KEY  (Windows)")
        print("  API 키 발급: https://aistudio.google.com/apikey")
        sys.exit(1)

    DEFAULT_GEMINI_MODEL = args.model

    print(f"""
╔════════════════════════════════════════════════════╗
║     Gemini Ollama Proxy for BSE                    ║
╠════════════════════════════════════════════════════╣
║  프록시 주소: http://{args.host}:{args.port:<26} ║
║  Gemini 모델: {args.model:<36} ║
╠════════════════════════════════════════════════════╣
║  BSE 설정 방법:                                    ║
║  Settings > API URL: http://localhost:{args.port:<14}║
║  Settings > Model: gemini-2.5-flash                ║
╚════════════════════════════════════════════════════╝
""")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
