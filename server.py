import os
import shutil
import subprocess
import time
import json
from pathlib import Path
from typing import List, Dict, Generator
from pydantic import BaseModel
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# Import our processing modules
import cv2
from screendoc import StepDetector, DocumentationGenerator

load_dotenv()

app = FastAPI(title="Peely AI backend")

# CORS middleware for dev server access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from starlette.responses import Response

class CORSStaticFiles(StaticFiles):
    async def simple_response(self, *args, **kwargs) -> Response:
        response = await super().simple_response(*args, **kwargs)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

# Core directories
OUTPUT_DIR = Path("output")
RECORDINGS_DIR = OUTPUT_DIR / "recordings"
SCREENSHOTS_DIR = OUTPUT_DIR / "screenshots"
DOCS_DIR = OUTPUT_DIR / "docs"

for dir_path in [OUTPUT_DIR, RECORDINGS_DIR, SCREENSHOTS_DIR, DOCS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Mount output directory to serve screenshots/videos with CORS support
app.mount("/output", CORSStaticFiles(directory="output"), name="output")


class ProcessConfig(BaseModel):
    video_path: str
    similarity_threshold: float = 0.85
    min_time_between_steps: float = 1.0


class SettingsPayload(BaseModel):
    llm_api_key: str
    llm_api_base: str
    model_name: str
    similarity_threshold: float
    min_time_between_steps: float


@app.get("/health")
def health():
    return {"status": "ok", "backend": "fastapi"}


@app.get("/api/settings")
def get_settings():
    load_dotenv()
    return {
        "llm_api_key": os.getenv("LLM_API_KEY", ""),
        "llm_api_base": os.getenv("LLM_API_BASE", "http://localhost:11434"),
        "model_name": os.getenv("MODEL_NAME", "meta-llama/llama-4-scout-17b-16e-instruct"),
        "similarity_threshold": float(os.getenv("SIMILARITY_THRESHOLD", "0.85")),
        "min_time_between_steps": float(os.getenv("MIN_TIME_BETWEEN_STEPS", "0.5")),
    }


@app.post("/api/settings")
def save_settings(payload: SettingsPayload):
    try:
        # Save settings to .env file
        with open(".env", "w") as f:
            f.write(f"LLM_API_KEY={payload.llm_api_key}\n")
            f.write(f"LLM_API_BASE={payload.llm_api_base}\n")
            f.write(f"MODEL_NAME={payload.model_name}\n")
            f.write(f"SIMILARITY_THRESHOLD={payload.similarity_threshold}\n")
            f.write(f"MIN_TIME_BETWEEN_STEPS={payload.min_time_between_steps}\n")

        # Reload environment variables in current process
        os.environ["LLM_API_KEY"] = payload.llm_api_key
        os.environ["LLM_API_BASE"] = payload.llm_api_base
        os.environ["MODEL_NAME"] = payload.model_name
        os.environ["SIMILARITY_THRESHOLD"] = str(payload.similarity_threshold)
        os.environ["MIN_TIME_BETWEEN_STEPS"] = str(payload.min_time_between_steps)

        return {"status": "success", "message": "Settings saved successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload")
async def upload_recording(file: UploadFile = File(...)):
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    # Clean file extension
    ext = Path(file.filename).suffix or ".webm"
    raw_path = RECORDINGS_DIR / f"raw_{timestamp}{ext}"
    mp4_path = RECORDINGS_DIR / f"recording_{timestamp}.mp4"

    # Save uploaded file
    with open(raw_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Convert to MP4 using ffmpeg if it's WebM (or any format other than mp4 for better browser compatibility)
    if ext != ".mp4":
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(raw_path),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "23",
                    "-movflags",
                    "+faststart",
                    str(mp4_path),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
            raw_path.unlink(missing_ok=True)
            final = str(mp4_path)
        except Exception as e:
            print(f"ffmpeg conversion failed: {e}, using raw {ext} directly")
            final = str(raw_path)
    else:
        # Move raw to correct mp4 path
        shutil.move(str(raw_path), str(mp4_path))
        final = str(mp4_path)

    # Write path to shared state file for backward compatibility
    state_file = Path("output/last_recording.txt")
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(final)

    return {
        "path": final,
        "status": "ok",
        "url": f"/output/recordings/{Path(final).name}",
    }


@app.post("/api/process")
async def process_video_endpoint(config: ProcessConfig):
    if not Path(config.video_path).exists():
        raise HTTPException(
            status_code=400, detail=f"Video file not found at path: {config.video_path}"
        )

    def progress_stream() -> Generator[str, None, None]:
        try:
            # Yield initial status
            yield json.dumps(
                {"status": "starting", "message": "Reading video metadata..."}
            ) + "\n"

            # Step 1: Detect frame rate and timestamps
            cap = cv2.VideoCapture(config.video_path)
            if not cap.isOpened():
                yield json.dumps(
                    {"status": "error", "message": "Failed to read video file."}
                ) + "\n"
                return

            fps = cap.get(cv2.CAP_PROP_FPS) or 15
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()

            # Use stable frame-index based timestamps (seconds from start of video)
            timestamps = [i / fps for i in range(frame_count)]

            yield json.dumps(
                {
                    "status": "detecting",
                    "message": f"Analyzing {frame_count} frames for transition steps...",
                }
            ) + "\n"

            # Step 2: Run Step Detection
            detector = StepDetector(
                similarity_threshold=config.similarity_threshold,
                min_time_between_steps=config.min_time_between_steps,
            )
            steps = detector.detect_steps(config.video_path, timestamps)

            yield json.dumps(
                {
                    "status": "saving_screenshots",
                    "message": f"Detected {len(steps)} steps. Generating screenshots...",
                }
            ) + "\n"

            # Step 3: Save Screenshots
            screenshot_paths = detector.save_screenshots(steps, str(SCREENSHOTS_DIR))

            # Form clean URLs for screenshots
            screenshots_data = {}
            for idx, path in screenshot_paths.items():
                screenshots_data[idx] = f"/output/screenshots/{Path(path).name}"

            # Step 4: Extract action for each step
            # Instantiate with current env settings
            generator = DocumentationGenerator()
            raw_step_actions = []

            for i in range(len(steps)):
                yield json.dumps(
                    {
                        "status": "analyzing_step",
                        "message": f"Analyzing step {i+1} of {len(steps)} with LLM...",
                        "current": i + 1,
                        "total": len(steps),
                    }
                ) + "\n"

                path = screenshot_paths.get(i)
                prev_path = screenshot_paths.get(i - 1) if i > 0 else None

                action = generator.generate_step_action(path, prev_path)
                raw_step_actions.append(action)

            # Filter out PeelyDocs setup/stop noise steps (start/end of recording)
            filtered_indices = []
            for i, action in enumerate(raw_step_actions):
                act_lower = action.lower()
                # Skip first step if it's about opening/starting PeelyDocs
                if i == 0 and ("peely" in act_lower or "start recording" in act_lower or "configure settings" in act_lower):
                    continue
                # Skip last step if it's about stopping/building in PeelyDocs
                if i == len(raw_step_actions) - 1 and ("peely" in act_lower or "stop & build" in act_lower or "stop recording" in act_lower or "build guide" in act_lower):
                    continue
                filtered_indices.append(i)

            # If filtering left nothing, keep all to avoid an empty guide
            if not filtered_indices:
                filtered_indices = list(range(len(steps)))

            final_step_actions = [raw_step_actions[i] for i in filtered_indices]
            final_screenshot_paths = {new_idx: screenshot_paths[old_idx] for new_idx, old_idx in enumerate(filtered_indices)}

            # Form clean URLs for screenshots based on the filtered list
            screenshots_data = {}
            for idx, path in final_screenshot_paths.items():
                screenshots_data[idx] = f"/output/screenshots/{Path(path).name}"

            # Step 5: Synthesize into how-to guide using filtered steps
            yield json.dumps(
                {
                    "status": "generating_guide",
                    "message": "Compiling final How-To guide...",
                }
            ) + "\n"

            markdown_content = generator.generate_howto_guide(
                final_step_actions, final_screenshot_paths
            )

            # Save the guide in docs folder
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            doc_path = DOCS_DIR / f"how_to_{timestamp}.md"
            with open(doc_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)

            yield json.dumps(
                {
                    "status": "completed",
                    "message": "Guide generated successfully!",
                    "markdown": markdown_content,
                    "screenshots": screenshots_data,
                    "doc_url": f"/output/docs/{doc_path.name}",
                }
            ) + "\n"

        except Exception as e:
            print(f"Error in processing pipeline: {e}")
            yield json.dumps(
                {
                    "status": "error",
                    "message": f"Internal error during processing: {str(e)}",
                }
            ) + "\n"

    return StreamingResponse(progress_stream(), media_type="text/event-stream")


# Serve React static assets in production if available
dist_dir = Path("frontend/dist")
if dist_dir.exists():
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")
else:

    @app.get("/")
    def root():
        return {
            "message": "ScreenDoc FastAPI backend. Run Vite dev server on port 8501 for UI."
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8502, reload=True)
