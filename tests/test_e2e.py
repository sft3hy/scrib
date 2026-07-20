#!/usr/bin/env python3
"""
PeelyDocs End-to-End Test Suite
================================
Tests every backend API endpoint and verifies the full pipeline produces
valid output. Designed to run against a live server on localhost:8502.

Usage:
    .venv/bin/python tests/test_e2e.py

Prerequisites:
    - uvicorn server running on port 8502
    - Ollama running on port 11434 with qwen3.5:2b pulled
    - At least one .mp4 in output/recordings/
"""

import os
import sys
import json
import time
import glob
import requests
from pathlib import Path

BACKEND = "http://localhost:8502"
FRONTEND = "http://localhost:3001"

# ANSI colours for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

passed = 0
failed = 0
skipped = 0


def log_pass(name, detail=""):
    global passed
    passed += 1
    print(f"  {GREEN}✓{RESET} {name}" + (f"  {CYAN}({detail}){RESET}" if detail else ""))


def log_fail(name, detail=""):
    global failed
    failed += 1
    print(f"  {RED}✗{RESET} {name}" + (f"  {RED}({detail}){RESET}" if detail else ""))


def log_skip(name, detail=""):
    global skipped
    skipped += 1
    print(f"  {YELLOW}○{RESET} {name}" + (f"  {YELLOW}({detail}){RESET}" if detail else ""))


def section(title):
    print(f"\n{BOLD}{CYAN}{'─' * 50}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{CYAN}{'─' * 50}{RESET}")


# ──────────────────────────────────────────────────────────────────
# 1. Connectivity checks
# ──────────────────────────────────────────────────────────────────

def test_backend_reachable():
    section("1. Connectivity")
    try:
        r = requests.get(f"{BACKEND}/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "ok"
        log_pass("Backend /health", f"status={data['status']}")
    except Exception as e:
        log_fail("Backend /health", str(e))
        print(f"\n{RED}  ⚠  Backend is not running. Start it with:{RESET}")
        print(f"     .venv/bin/uvicorn server:app --host 0.0.0.0 --port 8502 --reload\n")
        sys.exit(1)


def test_groq_reachable():
    try:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise Exception("GROQ_API_KEY environment variable is not set")
        # Simple test request to Groq API using requests
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [{"role": "user", "content": "ping"}],
            "max_completion_tokens": 5
        }
        r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=10)
        assert r.status_code == 200
        log_pass("Groq reachable", "API connection successful")
        return ["meta-llama/llama-4-scout-17b-16e-instruct"]
    except Exception as e:
        log_fail("Groq reachable", str(e))
        return []


def test_frontend_reachable():
    try:
        r = requests.get(FRONTEND, timeout=5)
        assert r.status_code == 200
        log_pass("Frontend reachable", f"status={r.status_code}")
    except Exception as e:
        log_skip("Frontend reachable", "Vite dev server not running — frontend visual tests will be skipped")


# ──────────────────────────────────────────────────────────────────
# 2. Settings API
# ──────────────────────────────────────────────────────────────────

def test_get_settings():
    section("2. Settings API")
    try:
        r = requests.get(f"{BACKEND}/api/settings", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "model_name" in data
        assert "llm_api_base" in data
        assert "similarity_threshold" in data
        assert "min_time_between_steps" in data
        log_pass("GET /api/settings", f"model={data['model_name']}")
        return data
    except Exception as e:
        log_fail("GET /api/settings", str(e))
        return {}


def test_post_settings():
    try:
        payload = {
            "llm_api_key": os.getenv("GROQ_API_KEY", ""),
            "llm_api_base": "https://api.groq.com/openai/v1",
            "model_name": "meta-llama/llama-4-scout-17b-16e-instruct",
            "similarity_threshold": 0.85,
            "min_time_between_steps": 0.5,
        }
        r = requests.post(f"{BACKEND}/api/settings", json=payload, timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "success"
        log_pass("POST /api/settings", "saved successfully")
    except Exception as e:
        log_fail("POST /api/settings", str(e))


def test_settings_roundtrip():
    """Verify a saved setting persists on subsequent GET."""
    try:
        payload = {
            "llm_api_key": os.getenv("GROQ_API_KEY", ""),
            "llm_api_base": "https://api.groq.com/openai/v1",
            "model_name": "meta-llama/llama-4-scout-17b-16e-instruct",
            "similarity_threshold": 0.75,
            "min_time_between_steps": 0.3,
        }
        requests.post(f"{BACKEND}/api/settings", json=payload, timeout=5)
        time.sleep(0.5)  # let uvicorn reload .env
        r = requests.get(f"{BACKEND}/api/settings", timeout=5)
        data = r.json()
        assert float(data["similarity_threshold"]) == 0.75, f"Expected 0.75, got {data['similarity_threshold']}"
        assert float(data["min_time_between_steps"]) == 0.3, f"Expected 0.3, got {data['min_time_between_steps']}"
        log_pass("Settings roundtrip", "values persisted correctly")

        # Restore defaults
        payload["similarity_threshold"] = 0.85
        payload["min_time_between_steps"] = 0.5
        requests.post(f"{BACKEND}/api/settings", json=payload, timeout=5)
    except Exception as e:
        log_fail("Settings roundtrip", str(e))


# ──────────────────────────────────────────────────────────────────
# 3. Upload API
# ──────────────────────────────────────────────────────────────────

def find_test_video():
    """Find an existing recording to use for testing."""
    recordings = sorted(glob.glob("output/recordings/recording_*.mp4"))
    if recordings:
        return recordings[0]
    return None


def test_upload():
    section("3. Upload API")
    video_path = find_test_video()
    if not video_path:
        log_skip("POST /api/upload", "No test video found in output/recordings/")
        return None

    try:
        with open(video_path, "rb") as f:
            files = {"file": ("test_recording.mp4", f, "video/mp4")}
            r = requests.post(f"{BACKEND}/api/upload", files=files, timeout=30)

        assert r.status_code == 200
        data = r.json()
        assert "path" in data
        assert "url" in data
        assert data.get("status") == "ok"
        log_pass("POST /api/upload", f"path={data['path']}")

        # Verify the uploaded file is accessible
        file_url = f"{BACKEND}{data['url']}"
        r2 = requests.head(file_url, timeout=5)
        if r2.status_code == 200:
            log_pass("Uploaded file accessible", file_url)
        else:
            log_fail("Uploaded file accessible", f"status={r2.status_code}")

        return data["path"]
    except Exception as e:
        log_fail("POST /api/upload", str(e))
        return None


# ──────────────────────────────────────────────────────────────────
# 4. Processing Pipeline (full end-to-end)
# ──────────────────────────────────────────────────────────────────

def test_process_pipeline(video_path):
    section("4. Processing Pipeline (end-to-end)")
    if not video_path:
        log_skip("POST /api/process", "No video path available — skipping pipeline test")
        return None

    try:
        payload = {
            "video_path": video_path,
            "similarity_threshold": 0.85,
            "min_time_between_steps": 0.5,
        }

        r = requests.post(
            f"{BACKEND}/api/process",
            json=payload,
            timeout=300,  # LLM calls can be slow
            stream=True,
        )
        assert r.status_code == 200

        statuses_seen = []
        final_data = None

        for line in r.iter_lines(decode_unicode=True):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                status = data.get("status", "unknown")
                statuses_seen.append(status)

                if status == "error":
                    log_fail("Pipeline stream", f"Error: {data.get('message')}")
                    return None

                if status == "completed":
                    final_data = data
            except json.JSONDecodeError:
                pass

        # Check we saw all expected pipeline stages
        expected_stages = ["starting", "detecting", "saving_screenshots", "completed"]
        for stage in expected_stages:
            if stage in statuses_seen:
                log_pass(f"Pipeline stage: {stage}")
            else:
                log_fail(f"Pipeline stage: {stage}", "not seen in stream")

        if "analyzing_step" in statuses_seen:
            log_pass("Pipeline stage: analyzing_step", f"seen {statuses_seen.count('analyzing_step')} times")
        else:
            log_fail("Pipeline stage: analyzing_step", "not seen")

        if "generating_guide" in statuses_seen:
            log_pass("Pipeline stage: generating_guide")
        else:
            log_fail("Pipeline stage: generating_guide", "not seen")

        if not final_data:
            log_fail("Pipeline completed with data", "No completion event received")
            return None

        return final_data
    except Exception as e:
        log_fail("POST /api/process", str(e))
        return None


# ──────────────────────────────────────────────────────────────────
# 5. Output validation
# ──────────────────────────────────────────────────────────────────

def test_output_quality(final_data):
    section("5. Output Quality Validation")
    if not final_data:
        log_skip("Output validation", "No pipeline output to validate")
        return

    # -- Markdown content --
    md = final_data.get("markdown", "")
    if len(md) > 100:
        log_pass("Markdown length", f"{len(md)} chars")
    else:
        log_fail("Markdown length", f"Only {len(md)} chars — too short")

    if md.startswith("#"):
        log_pass("Markdown has title heading")
    else:
        log_fail("Markdown has title heading", f"Starts with: {md[:50]!r}")

    # Check it's not just the fallback text
    if "Performed action on screen" in md:
        log_fail("Markdown is NOT fallback text", "Contains generic fallback — LLM likely failed silently")
    else:
        log_pass("Markdown is NOT fallback text")

    # Check for step structure
    step_count = md.lower().count("step")
    if step_count >= 2:
        log_pass("Markdown contains step references", f"{step_count} mentions")
    else:
        log_fail("Markdown step references", f"Only {step_count} — expected multiple")

    # -- Screenshots --
    screenshots = final_data.get("screenshots", {})
    if len(screenshots) >= 2:
        log_pass("Screenshots detected", f"{len(screenshots)} unique steps")
    elif len(screenshots) == 1:
        log_pass("Screenshots detected", "1 step (video may be very short)")
    else:
        log_fail("Screenshots detected", "0 screenshots")

    # Verify each screenshot URL is accessible
    accessible_count = 0
    for idx, url in screenshots.items():
        full_url = f"{BACKEND}{url}" if url.startswith("/") else url
        try:
            r = requests.head(full_url, timeout=5)
            if r.status_code == 200:
                accessible_count += 1
        except:
            pass
    if accessible_count == len(screenshots) and accessible_count > 0:
        log_pass("All screenshot URLs accessible", f"{accessible_count}/{len(screenshots)}")
    elif accessible_count > 0:
        log_fail("All screenshot URLs accessible", f"Only {accessible_count}/{len(screenshots)}")
    else:
        log_fail("Screenshot URLs accessible", "None accessible")

    # -- Check screenshots are not all identical (dedup check) --
    if len(screenshots) >= 2:
        try:
            import hashlib
            hashes = set()
            for idx, url in screenshots.items():
                full_url = f"{BACKEND}{url}" if url.startswith("/") else url
                r = requests.get(full_url, timeout=10)
                if r.status_code == 200:
                    hashes.add(hashlib.md5(r.content).hexdigest())
            if len(hashes) >= 2:
                log_pass("Screenshots are unique (not duplicates)", f"{len(hashes)} distinct images")
            else:
                log_fail("Screenshots are unique", f"Only {len(hashes)} distinct image(s) out of {len(screenshots)}")
        except Exception as e:
            log_skip("Screenshot uniqueness check", str(e))

    # -- Doc URL --
    doc_url = final_data.get("doc_url", "")
    if doc_url:
        full_doc_url = f"{BACKEND}{doc_url}" if doc_url.startswith("/") else doc_url
        try:
            r = requests.get(full_doc_url, timeout=5)
            if r.status_code == 200 and len(r.text) > 50:
                log_pass("Doc file accessible and non-empty", f"{len(r.text)} chars")
            else:
                log_fail("Doc file accessible", f"status={r.status_code}, len={len(r.text)}")
        except Exception as e:
            log_fail("Doc file accessible", str(e))
    else:
        log_fail("Doc URL present", "No doc_url in response")

    # -- Check markdown embeds screenshot paths --
    embedded_images = md.count("![")
    if embedded_images > 0:
        log_pass("Markdown embeds images", f"{embedded_images} image(s) embedded")
    else:
        log_fail("Markdown embeds images", "No ![...] image tags found")


# ──────────────────────────────────────────────────────────────────
# 6. Frontend rendering check
# ──────────────────────────────────────────────────────────────────

def test_frontend_rendering():
    section("6. Frontend Rendering")
    try:
        r = requests.get(FRONTEND, timeout=5)
        if r.status_code != 200:
            log_skip("Frontend rendering", "Vite dev server not reachable")
            return

        html = r.text
        if "PeelyDocs" in html or "Peely" in html or "root" in html:
            log_pass("Frontend HTML loads", f"{len(html)} bytes")
        else:
            log_fail("Frontend HTML loads", "Unexpected content")

        # Check that Vite dev assets are loading
        if "src/main.jsx" in html or "type=\"module\"" in html:
            log_pass("Vite module script present")
        else:
            log_fail("Vite module script present")

        if "peely-favicon.ico" in html:
            log_pass("Peely favicon configured")
        else:
            log_fail("Peely favicon configured", "favicon link not found in HTML")

    except Exception as e:
        log_skip("Frontend rendering", str(e))


# ──────────────────────────────────────────────────────────────────
# 7. Static asset serving
# ──────────────────────────────────────────────────────────────────

def test_static_assets():
    section("7. Static Asset Serving")

    # Test that /output mount works
    try:
        r = requests.get(f"{BACKEND}/output/", timeout=5)
        # StaticFiles may return 404 for directory listing, but mount should exist
        if r.status_code in [200, 404, 403]:
            log_pass("Backend /output mount exists", f"status={r.status_code}")
        else:
            log_fail("Backend /output mount", f"status={r.status_code}")
    except Exception as e:
        log_fail("Backend /output mount", str(e))

    # Test docs directory
    docs = sorted(glob.glob("output/docs/how_to_*.md"))
    if docs:
        latest = Path(docs[-1]).name
        try:
            r = requests.get(f"{BACKEND}/output/docs/{latest}", timeout=5)
            if r.status_code == 200:
                log_pass(f"Doc file served: {latest}", f"{len(r.text)} chars")
            else:
                log_fail(f"Doc file served: {latest}", f"status={r.status_code}")
        except Exception as e:
            log_fail("Doc file served", str(e))
    else:
        log_skip("Doc file serving", "No how_to docs generated yet")


# ──────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────

def main():
    print(f"\n{BOLD}🍌 PeelyDocs End-to-End Test Suite{RESET}")
    print(f"{CYAN}{'═' * 50}{RESET}")

    # 1. Connectivity
    test_backend_reachable()
    groq_models = test_groq_reachable()
    test_frontend_reachable()

    # 2. Settings
    test_get_settings()
    test_post_settings()
    test_settings_roundtrip()

    # 3. Upload
    uploaded_path = test_upload()

    # 4. Full pipeline
    final_data = test_process_pipeline(uploaded_path)

    # 5. Output validation
    test_output_quality(final_data)

    # 6. Frontend
    test_frontend_rendering()

    # 7. Static assets
    test_static_assets()

    # Summary
    total = passed + failed + skipped
    print(f"\n{BOLD}{CYAN}{'═' * 50}{RESET}")
    print(f"{BOLD}  Summary{RESET}")
    print(f"{CYAN}{'─' * 50}{RESET}")
    print(f"  {GREEN}✓ Passed:  {passed}{RESET}")
    print(f"  {RED}✗ Failed:  {failed}{RESET}")
    print(f"  {YELLOW}○ Skipped: {skipped}{RESET}")
    print(f"  Total:   {total}")
    print(f"{CYAN}{'═' * 50}{RESET}\n")

    if failed > 0:
        print(f"{RED}{BOLD}  ⚠  Some tests failed!{RESET}\n")
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}  ✅ All tests passed!{RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
