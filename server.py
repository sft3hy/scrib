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
import base64
from screendoc import StepDetector, DocumentationGenerator, db

load_dotenv()

app = FastAPI(title="Peely AI backend")

@app.on_event("startup")
def on_startup():
    db.init_db()

import numpy as np

def choose_contrast_color(roi: np.ndarray) -> tuple:
    """
    Selects a high-contrast, color-blind friendly color (BGR) based on the background ROI.
    Uses Okabe-Ito palette colors and evaluates luminance contrast and color difference.
    """
    if roi is None or roi.size == 0:
        return (0, 159, 230) # Default Orange (BGR)
    
    avg_bgr = np.mean(roi, axis=(0, 1))
    b, g, r = avg_bgr[0], avg_bgr[1], avg_bgr[2]
    bg_luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    
    # Palette format: (Name, BGR)
    palette = [
        ("Sky Blue", (233, 180, 86)),      # Hex #56B4E9
        ("Orange", (0, 159, 230)),        # Hex #E69F00
        ("Yellow", (66, 228, 240)),       # Hex #F0E442
        ("Blue", (178, 114, 0)),         # Hex #0072B2
        ("Vermillion", (0, 94, 213)),    # Hex #D55E00
        ("Reddish Purple", (167, 121, 204)), # Hex #CC79A7
        ("Bluish Green", (115, 158, 0))  # Hex #009E73
    ]
    
    best_color = (0, 159, 230) # Default Orange
    max_score = -1.0
    
    for name, bgr in palette:
        cb, cg, cr = bgr[0], bgr[1], bgr[2]
        c_luminance = 0.2126 * cr + 0.7152 * cg + 0.0722 * cb
        
        # Absolute luminance difference
        lum_diff = abs(c_luminance - bg_luminance)
        
        # Color distance in BGR space
        color_dist = np.sqrt((cb - b)**2 + (cg - g)**2 + (cr - r)**2)
        
        # Weighted score (70% luminance difference, 30% color distance)
        score = 0.7 * (lum_diff / 255.0) + 0.3 * (color_dist / 441.67)
        
        if score > max_score:
            max_score = score
            best_color = bgr
            
    return best_color

def find_action_centroid_by_diff(prev_path: Path, curr_path: Path) -> tuple:
    """
    Uses Gaussian-smoothed pixel diff + weighted centroid (image moments) to precisely
    locate where the visual change is most concentrated between two screenshots.

    Returns:
        (cx_percent, cy_percent, region_w_percent, region_h_percent)
        cx/cy is the center-of-mass of the densest change region.
        Returns None if no significant localized change is found.
    """
    try:
        img_prev = cv2.imread(str(prev_path))
        img_curr = cv2.imread(str(curr_path))

        if img_prev is None or img_curr is None:
            return None

        h, w = img_curr.shape[:2]

        if img_prev.shape != img_curr.shape:
            img_prev = cv2.resize(img_prev, (w, h))

        gray_prev = cv2.cvtColor(img_prev, cv2.COLOR_BGR2GRAY)
        gray_curr = cv2.cvtColor(img_curr, cv2.COLOR_BGR2GRAY)

        # Step 1: Compute raw absolute pixel difference
        diff = cv2.absdiff(gray_prev, gray_curr).astype(np.float32)

        # Step 2: Zero out browser chrome zones to suppress false positives.
        # Top 12%: tab bar, bookmark bar, URL bar (clocks, spinners)
        # Bottom 5%: taskbar / dock
        ignore_top_px = int(0.12 * h)
        ignore_bottom_px = int(0.05 * h)
        diff[:ignore_top_px, :] = 0
        if ignore_bottom_px > 0:
            diff[h - ignore_bottom_px:, :] = 0

        # Step 3: Apply Gaussian blur to create a smooth "heat map" of change density.
        # This merges closely spaced small changes (like a button hover glow)
        # into a single coherent blob and dramatically reduces isolated noise.
        blurred = cv2.GaussianBlur(diff, (51, 51), 0)

        # Step 4: Threshold the blurred heatmap to produce a binary activity mask.
        # Using OTSU to auto-select threshold based on the image histogram.
        uint8_blur = cv2.normalize(blurred, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        otsu_thresh, thresh = cv2.threshold(uint8_blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Step 5: Find contours of the active change regions.
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None

        # Step 6: Score contours by their TOTAL DIFF INTENSITY inside each blob.
        # This picks the contour that corresponds to the highest-energy change,
        # not merely the largest area (which could be a scrolled page).
        best_contour = None
        best_score = -1.0
        best_bbox = None

        for c in contours:
            area = cv2.contourArea(c)
            if area < 100:  # Skip noise blobs
                continue

            # Build mask of this contour only
            mask = np.zeros((h, w), dtype=np.uint8)
            cv2.drawContours(mask, [c], -1, 255, cv2.FILLED)

            # Total intensity of diff pixels inside this contour
            intensity_sum = float(np.sum(diff * (mask / 255.0)))
            # Favor compact focused regions by penalizing large diffuse areas
            compactness_penalty = area / float(h * w)
            score = intensity_sum * (1.0 - compactness_penalty)

            if score > best_score:
                best_score = score
                best_contour = c
                best_bbox = cv2.boundingRect(c)

        if best_contour is None or best_bbox is None:
            return None

        bx, by, bw, bh = best_bbox
        bbox_area_frac = (bw * bh) / float(w * h)

        # Step 7: Reject if the winning region is too large (full page transition/scroll).
        # Anything covering >40% of the screen is a full navigation, not a click target.
        if bbox_area_frac > 0.40:
            return None

        # Step 8: Compute the WEIGHTED CENTROID using image moments on the blurred
        # heatmap masked to our winning contour.
        # The centroid is a precision estimate of the center of mass of the visual change,
        # which corresponds to where the cursor was/click effect originated.
        contour_mask = np.zeros((h, w), dtype=np.float32)
        cv2.drawContours(contour_mask, [best_contour], -1, 1.0, cv2.FILLED)
        weighted_region = blurred * contour_mask

        M = cv2.moments(weighted_region, binaryImage=False)
        if M["m00"] > 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
        else:
            # Fallback: use geometric center of the bounding box
            cx = bx + bw // 2
            cy = by + bh // 2

        cx_pct = (cx / float(w)) * 100.0
        cy_pct = (cy / float(h)) * 100.0
        bw_pct = (bw / float(w)) * 100.0
        bh_pct = (bh / float(h)) * 100.0

        return cx_pct, cy_pct, bw_pct, bh_pct

    except Exception as e:
        print(f"Error in find_action_centroid_by_diff: {e}")

    return None

def annotate_screenshot_file(
    filepath: Path,
    click_x_percent: float,
    click_y_percent: float,
    click_width_percent: float = 0.0,
    click_height_percent: float = 0.0,
    is_typing: bool = False
) -> bool:
    """
    Draws high-contrast action annotations directly on an image file on disk.
    Returns True if drawing was performed successfully, False otherwise.
    """
    try:
        # Avoid accidental drawing at (0, 0)
        if click_x_percent <= 0.01 and click_y_percent <= 0.01:
            return False
            
        img = cv2.imread(str(filepath))
        if img is None:
            return False
            
        h, w = img.shape[:2]
        cx = int((click_x_percent / 100.0) * w)
        cy = int((click_y_percent / 100.0) * h)
        
        is_annotated = False
        
        if is_typing:
            cw = int((click_width_percent / 100.0) * w)
            ch = int((click_height_percent / 100.0) * h)

            # For typing: cx/cy is the centroid, so build rect centered on it
            half_w = max(cw // 2, 60)
            half_h = max(ch // 2, 20)
            x1 = max(0, cx - half_w)
            y1 = max(0, cy - half_h)
            x2 = min(w - 1, cx + half_w)
            y2 = min(h - 1, cy + half_h)

            if x2 > x1 and y2 > y1:
                roi = img[y1:y2, x1:x2]
                color = choose_contrast_color(roi)
                # Draw rounded attention rectangle: thick outer shadow + bright inner
                cv2.rectangle(img, (x1 - 2, y1 - 2), (x2 + 2, y2 + 2), (0, 0, 0), 6)
                cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
                is_annotated = True
        else:
            # Click: draw a large, highly visible target circle.
            # Scale radius as 2.5% of the shorter image dimension so it's proportional.
            radius = max(28, int(min(w, h) * 0.025))
            rx1 = max(0, cx - radius)
            ry1 = max(0, cy - radius)
            rx2 = min(w, cx + radius)
            ry2 = min(h, cy + radius)

            roi = img[ry1:ry2, rx1:rx2]
            color = choose_contrast_color(roi)

            # Outer black shadow ring
            cv2.circle(img, (cx, cy), radius + 4, (0, 0, 0), 6)
            # Colored ring
            cv2.circle(img, (cx, cy), radius, color, 4)
            # Inner smaller ring for depth
            cv2.circle(img, (cx, cy), max(4, radius // 2), color, 2)
            # Solid center dot
            cv2.circle(img, (cx, cy), 5, (0, 0, 0), -1)
            cv2.circle(img, (cx, cy), 4, color, -1)
            is_annotated = True
            
        if is_annotated:
            cv2.imwrite(str(filepath), img)
            return True
            
    except Exception as e:
        print(f"Error drawing annotations on {filepath}: {e}")
        
    return False

def save_base64_screenshot(
    b64_data: str,
    click_x_percent: float = 0.0,
    click_y_percent: float = 0.0,
    click_width_percent: float = 0.0,
    click_height_percent: float = 0.0,
    is_typing: bool = False
) -> tuple:
    if "," in b64_data:
        b64_data = b64_data.split(",", 1)[1]
    img_bytes = base64.b64decode(b64_data)
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    import uuid
    filename = f"step_{timestamp}_{uuid.uuid4().hex[:6]}.png"
    filepath = SCREENSHOTS_DIR / filename
    
    # Save base image file
    with open(filepath, "wb") as f:
        f.write(img_bytes)
        
    # Annotate the screenshot file on disk
    is_annotated = annotate_screenshot_file(
        filepath=filepath,
        click_x_percent=click_x_percent,
        click_y_percent=click_y_percent,
        click_width_percent=click_width_percent,
        click_height_percent=click_height_percent,
        is_typing=is_typing
    )
    
    return f"/output/screenshots/{filename}", is_annotated

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
    confluence_email: str = ""
    confluence_api_token: str = ""


class OnboardingPayload(BaseModel):
    completed: bool
    reason: str


class StepCreate(BaseModel):
    order_index: int
    caption: str
    screenshot_base64: str
    click_x_percent: float
    click_y_percent: float
    click_width_percent: float = 0.0
    click_height_percent: float = 0.0
    is_typing: bool = False


class GuideCreatePayload(BaseModel):
    title: str
    description: str = ""
    steps: List[StepCreate] = []


class GuideUpdatePayload(BaseModel):
    title: str
    description: str = ""


class StepUpdatePayload(BaseModel):
    caption: str
    order_index: int


@app.get("/api/users/me")
def get_user_me():
    user = db.get_user_by_id(1)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.patch("/api/users/me")
def patch_user_me(payload: OnboardingPayload):
    success = db.update_user_onboarding(1, payload.completed, payload.reason)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "success", "message": "Onboarding status updated"}


@app.post("/api/guides")
def create_guide_endpoint(payload: GuideCreatePayload):
    try:
        guide_id = db.create_guide(1, payload.title, payload.description)
        for step in payload.steps:
            screenshot_url, is_annotated = save_base64_screenshot(
                step.screenshot_base64,
                click_x_percent=step.click_x_percent,
                click_y_percent=step.click_y_percent,
                click_width_percent=step.click_width_percent,
                click_height_percent=step.click_height_percent,
                is_typing=step.is_typing
            )
            db.create_step(
                guide_id=guide_id,
                order_index=step.order_index,
                caption=step.caption,
                screenshot_url=screenshot_url,
                click_x_percent=step.click_x_percent,
                click_y_percent=step.click_y_percent,
                click_width_percent=step.click_width_percent,
                click_height_percent=step.click_height_percent,
                is_typing=step.is_typing,
                is_annotated=is_annotated
            )
        return {"status": "success", "guide_id": guide_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/guides")
def get_guides_endpoint():
    return db.get_guides(1)


@app.get("/api/guides/{guide_id}")
def get_guide_endpoint(guide_id: str):
    guide = db.get_guide_by_id(guide_id)
    if not guide:
        raise HTTPException(status_code=404, detail="Guide not found")
    return guide


@app.post("/api/guides/{guide_id}/export-confluence")
def export_guide_to_confluence(guide_id: str):
    import requests
    from requests.auth import HTTPBasicAuth
    import re
    import markdown

    # Load Confluence credentials from environment variables directly
    email = os.getenv("CONFLUENCE_EMAIL") or os.getenv("ATLASSIAN_EMAIL") or "sft3hy@virginia.edu"
    api_token = os.getenv("ATLASSIAN_API_KEY") or os.getenv("ATLASSIAN_API_TOKEN") or os.getenv("CONFLUENCE_API_TOKEN")
    if not api_token:
        raise HTTPException(
            status_code=400,
            detail="Confluence API Key/Token (ATLASSIAN_API_KEY) not found in environment."
        )

    # Get the guide from database
    guide = db.get_guide_by_id(guide_id)
    if not guide:
        raise HTTPException(status_code=404, detail="Guide not found")

    auth = HTTPBasicAuth(email, api_token)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    # Generate title with unique timestamp to avoid duplicates in the same space
    timestamped_title = f"{guide['title']} ({time.strftime('%Y-%m-%d %H:%M')})"

    # 1. Create page with placeholder body
    create_payload = {
        "type": "page",
        "title": timestamped_title,
        "space": {
            "key": "FH"
        },
        "ancestors": [
            {
                "id": "327835"
            }
        ],
        "body": {
            "storage": {
                "value": "<p>Publishing guide content and uploading attachments...</p>",
                "representation": "storage"
            }
        }
    }

    create_url = "https://samuel-townsend.atlassian.net/wiki/rest/api/content"
    try:
        r = requests.post(create_url, json=create_payload, auth=auth, headers=headers, timeout=15)
        if r.status_code != 200:
            raise HTTPException(
                status_code=r.status_code,
                detail=f"Confluence API returned {r.status_code}: {r.text}"
            )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to connect to Confluence: {str(e)}")

    page_data = r.json()
    page_id = page_data["id"]
    page_web_url = "https://samuel-townsend.atlassian.net/wiki" + page_data["_links"]["webui"]

    # 2. Upload screenshot attachments
    upload_url = f"https://samuel-townsend.atlassian.net/wiki/rest/api/content/{page_id}/child/attachment"
    attachment_headers = {
        "X-Atlassian-Token": "no-check"
    }

    uploaded_files = {} # Maps original screenshot URL -> Confluence attachment filename

    for step in guide["steps"]:
        screenshot_url = step.get("screenshot_url")
        if not screenshot_url:
            continue

        # Parse screenshot_url: "/output/screenshots/filename.png" -> "output/screenshots/filename.png"
        rel_path = screenshot_url.lstrip("/")
        local_path = Path(rel_path)

        if local_path.exists():
            filename = local_path.name
            try:
                with open(local_path, "rb") as file_data:
                    files = {
                        "file": (filename, file_data, "image/png")
                    }
                    att_r = requests.post(
                        upload_url,
                        auth=auth,
                        headers=attachment_headers,
                        files=files,
                        timeout=15
                    )
                    if att_r.status_code == 200:
                        uploaded_files[screenshot_url] = filename
                    else:
                        print(f"Failed to upload attachment {filename}: {att_r.text}")
            except Exception as ex:
                print(f"Error uploading attachment {filename}: {ex}")

    # 3. Compile Markdown and convert to HTML
    md_content = f"# {guide['title']}\n\n{guide.get('description') or ''}\n\n"
    md_content += "## Prerequisites\n- None\n\n## Steps\n"
    
    sorted_steps = sorted(guide["steps"], key=lambda s: s["order_index"])
    for idx, step in enumerate(sorted_steps):
        md_content += f"\n### Step {idx + 1}\n{step['caption']}\n\n"
        if step.get("screenshot_url"):
            md_content += f"![Step {idx + 1}]({step['screenshot_url']})\n\n"
        md_content += "---\n"

    html_content = markdown.markdown(md_content)

    # 4. Translate local image URLs in HTML to Confluence storage attachment markup
    def replacer(match):
        tag = match.group(0)
        src_match = re.search(r'src="([^"]+)"', tag)
        if src_match:
            src = src_match.group(1)
            for original_url, filename in uploaded_files.items():
                if original_url in src or src in original_url:
                    return f'<ac:image><ri:attachment ri:filename="{filename}" /></ac:image>'
        return tag

    confluence_html = re.sub(r'<img[^>]+>', replacer, html_content)

    # 5. Update the page with final content
    update_payload = {
        "id": page_id,
        "type": "page",
        "title": timestamped_title,
        "space": {
            "key": "FH"
        },
        "ancestors": [
            {
                "id": "327835"
            }
        ],
        "version": {
            "number": 2
        },
        "body": {
            "storage": {
                "value": confluence_html,
                "representation": "storage"
            }
        }
    }

    update_url = f"https://samuel-townsend.atlassian.net/wiki/rest/api/content/{page_id}"
    try:
        update_r = requests.put(update_url, json=update_payload, auth=auth, headers=headers, timeout=15)
        if update_r.status_code != 200:
            raise HTTPException(
                status_code=update_r.status_code,
                detail=f"Failed to update Confluence content: {update_r.text}"
            )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to update Confluence content: {str(e)}")

    return {
        "status": "success",
        "message": "Guide successfully exported to Confluence!",
        "url": page_web_url,
        "title": timestamped_title
    }


@app.patch("/api/guides/{guide_id}")
def patch_guide_endpoint(guide_id: str, payload: GuideUpdatePayload):
    success = db.update_guide(guide_id, payload.title, payload.description)
    if not success:
        raise HTTPException(status_code=404, detail="Guide not found")
    return {"status": "success", "message": "Guide updated"}


@app.patch("/api/guides/{guide_id}/steps/{step_id}")
def patch_step_endpoint(guide_id: str, step_id: str, payload: StepUpdatePayload):
    success = db.update_step(step_id, payload.caption, payload.order_index)
    if not success:
        raise HTTPException(status_code=404, detail="Step not found")
    return {"status": "success", "message": "Step updated"}


@app.delete("/api/guides/{guide_id}")
def delete_guide_endpoint(guide_id: str):
    success = db.delete_guide(guide_id)
    if not success:
        raise HTTPException(status_code=404, detail="Guide not found")
    return {"status": "success", "message": "Guide deleted"}


@app.delete("/api/guides/{guide_id}/steps/{step_id}")
def delete_step_endpoint(guide_id: str, step_id: str):
    success = db.delete_step(step_id)
    if not success:
        raise HTTPException(status_code=404, detail="Step not found")
    return {"status": "success", "message": "Step deleted"}


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
        "confluence_email": os.getenv("CONFLUENCE_EMAIL", ""),
        "confluence_api_token": os.getenv("CONFLUENCE_API_TOKEN", ""),
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
            f.write(f"CONFLUENCE_EMAIL={payload.confluence_email}\n")
            f.write(f"CONFLUENCE_API_TOKEN={payload.confluence_api_token}\n")

        # Reload environment variables in current process
        os.environ["LLM_API_KEY"] = payload.llm_api_key
        os.environ["LLM_API_BASE"] = payload.llm_api_base
        os.environ["MODEL_NAME"] = payload.model_name
        os.environ["SIMILARITY_THRESHOLD"] = str(payload.similarity_threshold)
        os.environ["MIN_TIME_BETWEEN_STEPS"] = str(payload.min_time_between_steps)
        os.environ["CONFLUENCE_EMAIL"] = payload.confluence_email
        os.environ["CONFLUENCE_API_TOKEN"] = payload.confluence_api_token

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

                action_data = generator.generate_step_action(path, prev_path)
                
                # Annotate the screenshot file on disk.
                # Strategy: weighted-centroid frame diff (precise) → LLM coords (fallback)
                try:
                    interaction_type = action_data.get("interaction_type", "none")
                    is_typing = (interaction_type == "type")

                    annotated = False

                    # --- Primary: Gaussian-smoothed weighted centroid diff ---
                    if prev_path:
                        cv_result = find_action_centroid_by_diff(Path(prev_path), Path(path))
                        if cv_result:
                            cx_pct, cy_pct, bw_pct, bh_pct = cv_result
                            annotated = annotate_screenshot_file(
                                filepath=Path(path),
                                click_x_percent=cx_pct,
                                click_y_percent=cy_pct,
                                click_width_percent=bw_pct,
                                click_height_percent=bh_pct,
                                is_typing=is_typing
                            )
                            if annotated:
                                print(f"Step {i}: CV centroid annotation at ({cx_pct:.1f}%, {cy_pct:.1f}%)")

                    # --- Fallback: LLM-estimated coordinates ---
                    if not annotated and interaction_type in ["click", "type"]:
                        llm_coords = action_data.get("coordinates", [0, 0, 0, 0])
                        if len(llm_coords) >= 2 and (llm_coords[0] > 1.0 or llm_coords[1] > 1.0):
                            click_w = llm_coords[2] if len(llm_coords) >= 4 else 0.0
                            click_h = llm_coords[3] if len(llm_coords) >= 4 else 0.0
                            annotate_screenshot_file(
                                filepath=Path(path),
                                click_x_percent=llm_coords[0],
                                click_y_percent=llm_coords[1],
                                click_width_percent=click_w,
                                click_height_percent=click_h,
                                is_typing=is_typing
                            )
                            print(f"Step {i}: LLM fallback annotation at ({llm_coords[0]:.1f}%, {llm_coords[1]:.1f}%)")

                except Exception as draw_ex:
                    print(f"Failed to draw visual overlay on step screenshot: {draw_ex}")
                    
                raw_step_actions.append(action_data.get("action", "Action on screen"))

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
        finally:
            try:
                video_file = Path(config.video_path)
                if video_file.exists():
                    video_file.unlink()
                    print(f"Deleted processed video file: {config.video_path}")
            except Exception as clean_ex:
                print(f"Failed to clean up video file: {clean_ex}")

    return StreamingResponse(progress_stream(), media_type="text/event-stream")


# Serve React static assets in production if available
dist_dir = Path("frontend/dist")
if dist_dir.exists():
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")
else:

    @app.get("/")
    def root():
        return {
            "message": "ScreenDoc FastAPI backend. Run Vite dev server on port 3001 for UI."
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8502, reload=True)
