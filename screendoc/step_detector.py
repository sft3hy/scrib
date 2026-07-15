import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass
from datetime import datetime
import time


@dataclass
class Step:
    timestamp: float
    screenshot: np.ndarray
    description: str = ""
    similarity_score: float = 0.0


class StepDetector:
    def __init__(
        self,
        similarity_threshold: float = 0.85,
        min_time_between_steps: float = 0.5,
    ):
        """Initialize the step detector.

        Args:
            similarity_threshold: How different frames must be to count as a new step.
                Lower = fewer steps captured (ignore minor UI changes).
                Higher = more steps captured (detect subtle changes).
            min_time_between_steps: Minimum seconds between captured steps.
        """
        self.similarity_threshold = similarity_threshold
        self.min_time_between_steps = min_time_between_steps

    # ------------------------------------------------------------------
    # Core similarity helpers
    # ------------------------------------------------------------------

    def _resize(self, frame: np.ndarray, width: int = 640) -> np.ndarray:
        """Downscale frame to a fixed width to normalise comparisons."""
        h, w = frame.shape[:2]
        if w <= width:
            return frame
        ratio = width / w
        return cv2.resize(frame, (width, int(h * ratio)), interpolation=cv2.INTER_AREA)

    def _histogram_similarity(self, f1: np.ndarray, f2: np.ndarray) -> float:
        """Compare colour histograms — fast, rotation/scale robust."""
        f1r = self._resize(f1)
        f2r = self._resize(f2)
        hist1 = cv2.calcHist([f1r], [0, 1, 2], None, [32, 32, 32], [0, 256, 0, 256, 0, 256])
        hist2 = cv2.calcHist([f2r], [0, 1, 2], None, [32, 32, 32], [0, 256, 0, 256, 0, 256])
        cv2.normalize(hist1, hist1)
        cv2.normalize(hist2, hist2)
        score = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
        return max(0.0, min(1.0, float(score)))

    def _pixel_similarity(self, f1: np.ndarray, f2: np.ndarray) -> float:
        """Mean-Squared-Error based similarity between down-sampled greyscale frames."""
        f1r = self._resize(cv2.cvtColor(f1, cv2.COLOR_BGR2GRAY))
        f2r = self._resize(cv2.cvtColor(f2, cv2.COLOR_BGR2GRAY))
        # Resize to same shape in case aspect ratios differ (should not, but safety)
        if f1r.shape != f2r.shape:
            f2r = cv2.resize(f2r, (f1r.shape[1], f1r.shape[0]))
        diff = cv2.absdiff(f1r.astype(np.float32), f2r.astype(np.float32))
        mse = np.mean(diff ** 2)
        # MSE 0 → identical (sim=1), MSE ~65025 (max) → totally different (sim=0)
        return max(0.0, 1.0 - mse / 65025.0)

    def calculate_similarity(self, frame1: np.ndarray, frame2: np.ndarray) -> float:
        """Weighted ensemble: histogram (60%) + pixel MSE (40%)."""
        hist = self._histogram_similarity(frame1, frame2)
        pix = self._pixel_similarity(frame1, frame2)
        return 0.6 * hist + 0.4 * pix

    # ------------------------------------------------------------------
    # Step detection
    # ------------------------------------------------------------------

    def detect_steps(self, video_path: str, timestamps: List[float]) -> List[Step]:
        """Detect significant scene changes in a recorded video.

        Strategy:
        1. Compare each frame to the *last accepted keyframe* (not just the
           previous frame) using an ensemble similarity metric.
        2. Enforce a minimum time gap between accepted steps.
        3. Post-filter: remove near-duplicate steps that slipped through.

        Args:
            video_path: Path to the video file.
            timestamps: Per-frame timestamps (same length as frame count).

        Returns:
            List of Step objects representing distinct UI states.
        """
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 15
        steps: List[Step] = []
        keyframe: np.ndarray | None = None   # last accepted step frame
        last_step_time: float = -999.0
        frame_idx = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            # Guard against timestamp list shorter than actual frame count
            if frame_idx >= len(timestamps):
                break

            current_ts = timestamps[frame_idx]
            frame_idx += 1

            # Always accept the first frame
            if keyframe is None:
                steps.append(Step(
                    timestamp=current_ts,
                    screenshot=frame.copy(),
                    similarity_score=1.0,
                ))
                keyframe = frame.copy()
                last_step_time = current_ts
                continue

            # Enforce minimum time gap
            if current_ts - last_step_time < self.min_time_between_steps:
                continue

            # Compare current frame vs. last accepted keyframe
            similarity = self.calculate_similarity(keyframe, frame)

            if similarity < self.similarity_threshold:
                steps.append(Step(
                    timestamp=current_ts,
                    screenshot=frame.copy(),
                    similarity_score=similarity,
                ))
                keyframe = frame.copy()
                last_step_time = current_ts

        cap.release()

        if not steps:
            return steps

        # ------------------------------------------------------------------
        # Post-filter: remove steps that are too similar to their neighbours
        # (catches any duplicates that squeaked through)
        # ------------------------------------------------------------------
        deduped: List[Step] = [steps[0]]
        for i in range(1, len(steps)):
            sim_to_prev = self.calculate_similarity(deduped[-1].screenshot, steps[i].screenshot)
            if sim_to_prev < self.similarity_threshold:
                deduped.append(steps[i])

        return deduped

    # ------------------------------------------------------------------
    # Screenshot persistence
    # ------------------------------------------------------------------

    def save_screenshots(self, steps: List[Step], output_dir: str) -> Dict[int, str]:
        """Save screenshots for each detected step.

        Args:
            steps: List of detected steps.
            output_dir: Directory to save screenshots.

        Returns:
            Dict mapping step index → file path.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        screenshot_paths: Dict[int, str] = {}
        for idx, step in enumerate(steps):
            ts_str = datetime.fromtimestamp(step.timestamp).strftime("%Y%m%d_%H%M%S_%f")
            out_file = str(output_path / f"step_{idx:03d}_{ts_str}.png")
            cv2.imwrite(out_file, step.screenshot)
            screenshot_paths[idx] = out_file

        return screenshot_paths
