#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SMART DUB - Gemini AI Dubbing for Termux
----------------------------------------

Workflow:

    video.mp4
       |
       v
    FFmpeg -> audio.wav
       |
       v
    Gemini Files API
       |
       v
    Gemini Audio Understanding
       |
       +--> transcript
       +--> timestamps
       +--> Vietnamese translation
       |
       v
    TTS
       |
       v
    segment_*.wav
       |
       v
    FFmpeg concat/mix
       |
       v
    output_vi.mp4

Compatible conceptually with the smart.py workflow:
    translate_batch()
    segments[]
    item["translated"]

Environment:
    GEMINI_API_KEY=...

Usage:
    python smart_dub.py input.mp4

Optional:
    python smart_dub.py input.mp4 -o output_vi.mp4
    python smart.py input.mp4 --model gemini-3.6-flash
    python smart_dub.py input.mp4 --voice vi-VN-HoaiMyNeural
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import requests


# ============================================================
# CONFIG
# ============================================================

DEFAULT_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)

GEMINI_API_BASE = (
    "https://generativelanguage.googleapis.com"
)

UPLOAD_URL = (
    GEMINI_API_BASE +
    "/upload/v1beta/files"
)

GENERATE_URL = (
    GEMINI_API_BASE +
    "/v1beta/models/{model}:generateContent"
)

DEFAULT_VOICE = os.getenv(
    "TTS_VOICE",
    "Achernar"
)

GEMINI_TTS_MODEL = os.getenv(
    "GEMINI_TTS_MODEL",
    "gemini-3.1-flash-tts-preview"
)

# Two parallel requests reduce waiting time without needlessly exhausting
# mobile resources or Gemini quota. Set TTS_WORKERS=1 for troubleshooting.
TTS_WORKERS = max(1, int(os.getenv("TTS_WORKERS", "2")))

DEFAULT_LANGUAGE = "Vietnamese"

REQUEST_TIMEOUT = 300

MAX_RETRIES = 4


# ============================================================
# LOGGING
# ============================================================

def log(msg):
    print(f"[SMART-DUB] {msg}", flush=True)


def die(msg, code=1):
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(code)


# ============================================================
# COMMAND CHECK
# ============================================================

def check_command(name):
    if shutil.which(name) is None:
        die(
            f"Không tìm thấy '{name}'.\n"
            f"Hãy cài package tương ứng trong Termux."
        )


def check_environment():
    check_command("ffmpeg")
    check_command("ffprobe")

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        die(
            "Chưa có GEMINI_API_KEY.\n\n"
            "Trong Termux:\n"
            "export GEMINI_API_KEY='YOUR_KEY'\n"
        )

    return api_key


# ============================================================
# SHELL
# ============================================================

def run(cmd, check=True, capture=False):
    log("$ " + " ".join(map(str, cmd)))

    return subprocess.run(
        cmd,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None
    )


def ffprobe_duration(path):
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture=True
    )

    return float(result.stdout.strip())


# ============================================================
# STEP 1: EXTRACT AUDIO
# ============================================================

def extract_audio(video, output):
    log("STEP 1: Tách audio")

    run([
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output),
    ])


# ============================================================
# GEMINI UPLOAD
# ============================================================

def extract_json(text):
    """Parse Gemini JSON output, including an occasional Markdown fence."""
    text = str(text).strip()
    text = re.sub(r"^```(?:json)?\\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\\s*```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min(
            (index for index in (text.find("{"), text.find("[")) if index >= 0),
            default=-1,
        )
        if start < 0:
            raise RuntimeError("Gemini không trả JSON hợp lệ.")

        decoder = json.JSONDecoder()
        try:
            value, _ = decoder.raw_decode(text[start:])
            return value
        except json.JSONDecodeError as exc:
            raise RuntimeError("Gemini không trả JSON hợp lệ: " + str(exc)) from exc

def gemini_upload(api_key, path):
    """Upload a local audio file through the Gemini resumable Files API."""
    path = Path(path)
    mime_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
    headers = {
        "x-goog-api-key": api_key,
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(path.stat().st_size),
        "X-Goog-Upload-Header-Content-Type": mime_type,
        "Content-Type": "application/json",
    }

    log("STEP 2: Upload audio lên Gemini")
    response = requests.post(
        UPLOAD_URL,
        headers=headers,
        json={"file": {"display_name": path.name}},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    upload_url = response.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise RuntimeError("Gemini không trả URL upload: " + response.text)

    with path.open("rb") as audio_file:
        response = requests.post(
            upload_url,
            headers={
                "X-Goog-Upload-Command": "upload, finalize",
                "X-Goog-Upload-Offset": "0",
                "Content-Length": str(path.stat().st_size),
            },
            data=audio_file,
            timeout=REQUEST_TIMEOUT,
        )
    response.raise_for_status()
    file_data = response.json().get("file", {})
    uri = file_data.get("uri")
    if not uri:
        raise RuntimeError("Gemini không trả thông tin file: " + response.text)

    # Audio files normally become ACTIVE immediately; poll when processing is needed.
    file_name = file_data.get("name")
    state = file_data.get("state", "ACTIVE")
    for _ in range(60):
        if state == "ACTIVE":
            log("Upload thành công")
            return {"uri": uri, "mime_type": file_data.get("mime_type", mime_type)}
        if state == "FAILED":
            raise RuntimeError("Gemini không xử lý được file audio.")
        if not file_name:
            break
        time.sleep(2)
        response = requests.get(
            f"{GEMINI_API_BASE}/v1beta/{file_name}",
            headers={"x-goog-api-key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        file_data = response.json()
        state = file_data.get("state", "ACTIVE")
        uri = file_data.get("uri", uri)

    raise RuntimeError("Gemini xử lý file quá lâu hoặc không trả trạng thái ACTIVE.")

def gemini_generate(
    api_key,
    file_info,
    model,
    prompt
):
    # --------------------------------------------------------
    # Normalize Gemini model name
    # --------------------------------------------------------
    model = str(model).strip()

    if model.startswith("models/"):
        model = model[len("models/"):]

    # Tránh trường hợp người dùng truyền full URL
    if ":generateContent" in model:
        model = model.split(":generateContent")[0]

    model = model.rstrip("/")

    url = (
        f"{GEMINI_API_BASE}"
        f"/v1beta/models/{model}:generateContent"
    )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt
                    },
                    {
                        "file_data": {
                            "mime_type":
                                file_info["mime_type"],
                            "file_uri":
                                file_info["uri"]
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.15,
            "responseMimeType": "application/json"
        }
    }

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json"
    }

    # --------------------------------------------------------
    # Retry policy
    # --------------------------------------------------------

    retryable = {
        408,
        429,
        500,
        502,
        503,
        504
    }

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            log(
                f"Gemini request "
                f"{attempt}/{MAX_RETRIES} "
                f"model={model}"
            )

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )

            # ------------------------------------------------
            # SUCCESS
            # ------------------------------------------------

            if response.status_code == 200:

                data = response.json()

                candidates = data.get(
                    "candidates",
                    []
                )

                if not candidates:
                    raise RuntimeError(
                        "Gemini không trả candidate."
                    )

                parts = (
                    candidates[0]
                    .get("content", {})
                    .get("parts", [])
                )

                text = ""

                for part in parts:

                    if "text" in part:
                        text += part["text"]

                if not text.strip():
                    raise RuntimeError(
                        "Gemini trả kết quả rỗng."
                    )

                return extract_json(text)

            # ------------------------------------------------
            # BAD REQUEST
            # Không retry
            # ------------------------------------------------

            if response.status_code == 400:

                raise RuntimeError(
                    "Gemini API 400 INVALID_ARGUMENT:\n"
                    + response.text
                )

            # ------------------------------------------------
            # AUTH
            # ------------------------------------------------

            if response.status_code in (
                401,
                403
            ):

                raise RuntimeError(
                    "Gemini API authentication/"
                    "permission error:\n"
                    + response.text
                )

            # ------------------------------------------------
            # NOT FOUND
            # ------------------------------------------------

            if response.status_code == 404:

                raise RuntimeError(
                    "Gemini model hoặc file không tồn tại:\n"
                    + response.text
                )

            # ------------------------------------------------
            # RETRYABLE
            # ------------------------------------------------

            if response.status_code in retryable:

                wait = min(
                    60,
                    5 * (2 ** (attempt - 1))
                )

                log(
                    f"Gemini HTTP "
                    f"{response.status_code}. "
                    f"Chờ {wait}s..."
                )

                last_error = response.text

                if attempt < MAX_RETRIES:
                    time.sleep(wait)
                    continue

                break

            # ------------------------------------------------
            # OTHER
            # ------------------------------------------------

            raise RuntimeError(
                f"Gemini HTTP "
                f"{response.status_code}:\n"
                + response.text
            )

        except RuntimeError:
            raise

        except Exception as exc:

            last_error = exc

            if attempt >= MAX_RETRIES:
                break

            wait = min(
                60,
                5 * (2 ** (attempt - 1))
            )

            log(
                f"Lỗi mạng: {exc}"
            )

            log(
                f"Retry sau {wait}s..."
            )

            time.sleep(wait)

    raise RuntimeError(
        "Gemini request thất bại: "
        f"{last_error}"
    )


# ============================================================
# STEP 3: TRANSCRIBE + TRANSLATE
# ============================================================

def analyze_audio(
    api_key,
    file_info,
    model
):
    log(
        "STEP 3: Gemini nhận dạng + "
        "dịch tiếng Việt"
    )

    prompt = r"""
Bạn là hệ thống lồng tiếng video chuyên nghiệp.

Hãy nghe toàn bộ audio được cung cấp.

Nhiệm vụ:

1. Nhận dạng chính xác lời thoại.
2. Chia thành từng câu/đoạn nói tự nhiên.
3. Xác định timestamp bắt đầu và kết thúc.
4. Dịch sang tiếng Việt tự nhiên.
5. Giữ đúng ý nghĩa, cảm xúc và ngữ cảnh.
6. Không dịch tiếng động không phải lời thoại.
7. Không thêm giải thích.
8. Nếu có nhiều người nói, cố gắng nhận diện speaker.
9. Không gộp các câu quá dài.
10. Timestamp phải tính bằng giây.

Trả về JSON duy nhất:

{
  "segments": [
    {
      "id": 1,
      "start": 0.00,
      "end": 2.50,
      "speaker": "speaker_1",
      "source": "...",
      "translated": "..."
    }
  ]
}

QUY TẮC:

- start < end
- Các segment phải theo thứ tự thời gian.
- translated phải là tiếng Việt.
- Không dùng Markdown.
- Không dùng ```json.
"""

    data = gemini_generate(
        api_key,
        file_info,
        model,
        prompt
    )

    if isinstance(data, dict):
        segments = data.get(
            "segments",
            []
        )
    else:
        segments = data

    if not isinstance(segments, list):
        raise ValueError(
            "Gemini không trả danh sách segments."
        )

    cleaned = []

    for index, item in enumerate(segments):

        try:
            start = float(
                item["start"]
            )

            end = float(
                item["end"]
            )

            source = str(
                item.get("source", "")
            ).strip()

            translated = str(
                item.get("translated", "")
            ).strip()

            speaker = str(
                item.get(
                    "speaker",
                    "speaker_1"
                )
            ).strip()

            if end <= start:
                continue

            if not translated:
                continue

            cleaned.append({
                "id": index + 1,
                "start": start,
                "end": end,
                "speaker": speaker,
                "source": source,
                "translated": translated,
            })

        except (
            KeyError,
            TypeError,
            ValueError
        ):
            continue

    return cleaned


# ============================================================
# COMPATIBILITY WITH smart.py
# ============================================================

def translate_batch(texts, api_key=None, model=None):
    """
    Compatibility function.

    smart.py hiện tại của bạn có workflow:

        translated = translate_batch(texts)

    Hàm này cho phép tái sử dụng dữ liệu
    nếu sau này smart.py gọi smart_dub.py.
    """

    if not texts:
        return []

    api_key = (
        api_key
        or os.getenv("GEMINI_API_KEY")
    )

    model = (
        model
        or DEFAULT_MODEL
    )

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY chưa được thiết lập."
        )

    prompt_lines = []

    for i, text in enumerate(texts):
        prompt_lines.append(
            f"{i}: {text}"
        )

    prompt = """
Dịch các câu sau sang tiếng Việt.

Giữ nguyên thứ tự.
Không giải thích.
Trả JSON:

{
  "translations": [
    "...",
    "..."
  ]
}

TEXT:
""" + "\n".join(prompt_lines)

    # Không có audio ở đây.
    # Dùng text-only endpoint.
    url = GENERATE_URL.format(
        model=model
    )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.15,
            "responseMimeType": "application/json"
        }
    }

    response = requests.post(
        url,
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    text = ""

    for part in (
        data["candidates"][0]
        ["content"]["parts"]
    ):
        if "text" in part:
            text += part["text"]

    result = extract_json(text)

    return result["translations"]


# ============================================================
# SAVE SEGMENTS
# ============================================================

def save_segments(
    segments,
    path
):
    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            segments,
            f,
            ensure_ascii=False,
            indent=2
        )

    log(
        f"Đã lưu segments: {path}"
    )


# ============================================================
# TTS
# ============================================================

def make_tts(api_key, text, output, voice):
    if not text.strip():
        return False

    prompt = (
        "Synthesize only the Vietnamese transcript below. Speak like a real "
        "person in a close, natural conversation: warm, expressive, with "
        "emotion implied by the words and punctuation. Use natural Vietnamese "
        "pauses. Do not read these instructions aloud.\n\n"
        f"Transcript: {text}"
    )
    response = requests.post(
        GENERATE_URL.format(model=GEMINI_TTS_MODEL),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice}
                    }
                },
            },
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    parts = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
    audio_data = next((part.get("inlineData", {}).get("data") for part in parts if part.get("inlineData", {}).get("data")), None)
    if not audio_data:
        raise RuntimeError("Gemini TTS không trả audio: " + response.text)

    # Gemini TTS returns 24 kHz, mono, signed 16-bit PCM.
    with wave.open(str(output), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(base64.b64decode(audio_data))

    return True


# ============================================================
# AUDIO DURATION
# ============================================================

def audio_duration(path):
    try:
        with wave.open(str(path), "rb") as wav_file:
            return wav_file.getnframes() / wav_file.getframerate()
    except (wave.Error, EOFError):
        pass
    return ffprobe_duration(path)


# ============================================================
# FIT TTS TO TIMESTAMP
# ============================================================

def fit_audio(
    source,
    target,
    duration
):
    """
    Điều chỉnh TTS để vừa duration.

    Không ép tốc độ quá cao.
    """

    source_duration = audio_duration(
        source
    )

    if source_duration <= 0:
        return

    ratio = source_duration / duration

    # atempo chỉ nên thay đổi vừa phải.
    # Nếu lệch quá nhiều, dùng pad/trim.
    if 0.75 <= ratio <= 1.333:
        tempo = ratio

        run([
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-filter:a",
            f"atempo={tempo}",
            "-t",
            f"{duration:.3f}",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(target),
        ])

    else:
        # Không bóp giọng quá mạnh.
        run([
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-t",
            f"{duration:.3f}",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(target),
        ])


# ============================================================
# BUILD SILENCE + SEGMENTS
# ============================================================

def create_segment_audio(
    segments,
    workdir,
    voice,
    api_key
):
    log("STEP 4: Tạo TTS tiếng Việt")

    def create_one(pos, item):
        start = item["start"]
        end = item["end"]
        duration = end - start
        text = item["translated"]
        raw = workdir / (
            f"tts_raw_{pos:05d}.wav"
        )
        fitted = workdir / (
            f"tts_{pos:05d}.wav"
        )
        log(
            f"TTS {pos + 1}/{len(segments)} "
            f"[{start:.2f} -> {end:.2f}]"
        )

        make_tts(api_key, text, raw, voice)
        fit_audio(raw, fitted, duration)
        return pos, {
            "path": fitted,
            "start": start,
            "end": end,
        }

    files = []
    workers = min(TTS_WORKERS, len(segments))
    log(f"Tạo vocal song song: {workers} luồng")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(create_one, pos, item)
            for pos, item in enumerate(segments)
        ]
        for future in as_completed(futures):
            files.append(future.result())

    return [item for _, item in sorted(files)]


# ============================================================
# BUILD DUB AUDIO
# ============================================================

def build_dub_audio(
    segment_files,
    total_duration,
    output,
    workdir
):
    """
    Tạo một audio track hoàn chỉnh.

    Mỗi segment được delay đúng timestamp.
    """

    log("STEP 5: Ghép các đoạn TTS")

    if not segment_files:
        raise RuntimeError(
            "Không có TTS segment."
        )

    inputs = []

    for item in segment_files:
        inputs.extend([
            "-i",
            str(item["path"])
        ])

    filters = []

    for i, item in enumerate(segment_files):

        delay_ms = max(
            0,
            int(round(item["start"] * 1000))
        )

        filters.append(
            f"[{i}:a]"
            f"adelay={delay_ms}|{delay_ms},"
            f"asetpts=PTS-STARTPTS"
            f"[a{i}]"
        )

    labels = "".join(
        f"[a{i}]"
        for i in range(len(segment_files))
    )

    filters.append(
        f"{labels}"
        f"amix=inputs={len(segment_files)}:"
        f"duration=longest:"
        f"dropout_transition=0,"
        f"apad,"
        f"atrim=duration={total_duration:.3f}"
        f"[out]"
    )

    filter_complex = ";".join(filters)

    run([
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(output),
    ])


# ============================================================
# MIX ORIGINAL + DUB
# ============================================================

def mix_with_original(
    video,
    dub_audio,
    output,
    original_volume=0.0,
    dub_volume=1.0
):
    """
    original_volume=0.0:
        chỉ nghe tiếng Việt.

    original_volume=0.15:
        giữ tiếng gốc rất nhỏ làm ambience.

    dub_volume=1.0:
        tiếng Việt bình thường.
    """

    log("STEP 6: Ghép audio vào video")

    video_duration = ffprobe_duration(
        video
    )

    filter_complex = (
        f"[0:a]"
        f"volume={original_volume}"
        f"[orig];"
        f"[1:a]"
        f"volume={dub_volume}"
        f"[dub];"
        f"[orig][dub]"
        f"amix=inputs=2:"
        f"duration=longest:"
        f"dropout_transition=0,"
        f"atrim=duration={video_duration:.3f}"
        f"[aout]"
    )

    run([
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-i",
        str(dub_audio),
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(output),
    ])


# ============================================================
# OPTIONAL: KEEP ORIGINAL BACKGROUND
# ============================================================

def replace_audio(
    video,
    dub_audio,
    output
):
    log("STEP 6: Thay audio gốc bằng tiếng Việt")

    run([
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-i",
        str(dub_audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(output),
    ])


# ============================================================
# MAIN PIPELINE
# ============================================================

def process(
    video,
    output,
    model,
    voice,
    keep_original=False,
    original_volume=0.0
):
    video = Path(video).expanduser().resolve()
    output = Path(output).expanduser().resolve()

    if not video.exists():
        die(
            f"Không tìm thấy video:\n{video}"
        )

    api_key = check_environment()

    workdir = Path(
        tempfile.mkdtemp(
            prefix="smart_dub_"
        )
    )

    log(f"Workdir: {workdir}")

    try:

        # ----------------------------------------------------
        # 1. AUDIO
        # ----------------------------------------------------

        source_audio = (
            workdir / "source.wav"
        )

        extract_audio(
            video,
            source_audio
        )

        total_duration = (
            ffprobe_duration(video)
        )

        log(
            f"Video duration: "
            f"{total_duration:.2f}s"
        )

        # ----------------------------------------------------
        # 2. UPLOAD
        # ----------------------------------------------------

        file_info = gemini_upload(
            api_key,
            source_audio
        )

        # ----------------------------------------------------
        # 3. GEMINI
        # ----------------------------------------------------

        segments = analyze_audio(
            api_key,
            file_info,
            model
        )

        if not segments:
            raise RuntimeError(
                "Gemini không nhận được lời thoại."
            )

        # ----------------------------------------------------
        # 4. CLAMP TIMESTAMPS
        # ----------------------------------------------------

        for item in segments:

            item["start"] = max(
                0,
                min(
                    item["start"],
                    total_duration
                )
            )

            item["end"] = max(
                item["start"],
                min(
                    item["end"],
                    total_duration
                )
            )

        segments_path = (
            workdir / "segments.json"
        )

        save_segments(
            segments,
            segments_path
        )

        # ----------------------------------------------------
        # 5. TTS
        # ----------------------------------------------------

        tts_segments = (
            create_segment_audio(
                segments,
                workdir,
                voice,
                api_key
            )
        )

        # ----------------------------------------------------
        # 6. DUB TRACK
        # ----------------------------------------------------

        dub_audio = (
            workdir / "dub.wav"
        )

        build_dub_audio(
            tts_segments,
            total_duration,
            dub_audio,
            workdir
        )

        # ----------------------------------------------------
        # 7. FINAL VIDEO
        # ----------------------------------------------------

        if keep_original:
            mix_with_original(
                video,
                dub_audio,
                output,
                original_volume,
                1.0
            )
        else:
            replace_audio(
                video,
                dub_audio,
                output
            )

        # ----------------------------------------------------
        # COPY SEGMENTS BESIDE OUTPUT
        # ----------------------------------------------------

        final_segments = output.with_suffix(
            ".segments.json"
        )

        shutil.copy2(
            segments_path,
            final_segments
        )

        log("")
        log("=" * 60)
        log("HOÀN TẤT")
        log("=" * 60)
        log(f"Video : {output}")
        log(f"JSON  : {final_segments}")
        log(f"Đoạn  : {len(segments)}")
        log("=" * 60)

    finally:

        # Có thể giữ workdir để debug
        if os.getenv(
            "SMART_DUB_KEEP_TEMP"
        ) == "1":

            log(
                f"Giữ temporary files: "
                f"{workdir}"
            )

        else:

            shutil.rmtree(
                workdir,
                ignore_errors=True
            )


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Gemini Smart Dubbing "
            "for Termux"
        )
    )

    parser.add_argument(
        "input",
        help="Video input"
    )

    parser.add_argument(
        "-o",
        "--output",
        help="Video output"
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            "Gemini model "
            f"(default: {DEFAULT_MODEL})"
        )
    )

    parser.add_argument(
        "--voice",
        default=DEFAULT_VOICE,
        help=(
            "Gemini TTS voice "
            f"(default: {DEFAULT_VOICE})"
        )
    )

    parser.add_argument(
        "--keep-original",
        action="store_true",
        help=(
            "Giữ tiếng gốc nhỏ "
            "phía sau tiếng Việt"
        )
    )

    parser.add_argument(
        "--original-volume",
        type=float,
        default=0.08,
        help=(
            "Âm lượng tiếng gốc "
            "(0.0 - 1.0)"
        )
    )

    args = parser.parse_args()

    input_path = Path(
        args.input
    )

    if args.output:
        output_path = Path(
            args.output
        )
    else:
        output_path = (
            input_path.with_name(
                input_path.stem
                + "_vi"
                + input_path.suffix
            )
        )

    process(
        input_path,
        output_path,
        args.model,
        args.voice,
        args.keep_original,
        args.original_volume
    )


if __name__ == "__main__":
    main()
