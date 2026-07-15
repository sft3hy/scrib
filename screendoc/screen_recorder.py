import cv2
import time
import numpy as np
import os
import threading
from pathlib import Path
from typing import Tuple

class ScreenRecorder:
    def __init__(self, output_dir: str = "recordings"):
        """Initialize the screen recorder.
        
        Args:
            output_dir (str): Directory to save recordings
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.recording = False
        self._lock = threading.Lock()
        self.frames = []
        self.timestamps = []
        self.actual_output_file = str(self.output_dir / "temp.avi")
        self.error = None

    def start_recording(self, monitor: int = 1) -> None:
        """Start screen recording continuously until stopped.
        
        Args:
            monitor (int): Monitor number to record (default: 1, primary monitor)
        """
        self.recording = True
        self.timestamps = []
        self.error = None
        sct = None
        out = None
        
        try:
            import mss
            try:
                sct = mss.mss()
            except Exception as e:
                raise RuntimeError(
                    f"Failed to initialize screen capture library (mss). "
                    f"If running inside Docker or headlessly, screen recording is not supported. "
                    f"Details: {e}"
                )
                
            num_monitors = len(sct.monitors)
            if num_monitors <= 1:
                monitor_idx = 0
            else:
                monitor_idx = monitor if 0 <= monitor < num_monitors else 1
                
            mon = sct.monitors[monitor_idx]
            screen_width = mon["width"]
            screen_height = mon["height"]
            
            # Test grab to verify permissions
            try:
                sct.grab(mon)
            except Exception as e:
                raise PermissionError(
                    f"Screen recording permission denied. "
                    f"Please ensure your OS/terminal/IDE has screen recording permissions granted. "
                    f"Details: {e}"
                )
                
            # Try to initialize the VideoWriter with fallback codecs
            codecs = [
                ('MJPG', 'temp.avi'),
                ('mp4v', 'temp.mp4'),
                ('XVID', 'temp.avi')
            ]
            
            output_file = None
            
            for codec_name, filename in codecs:
                try:
                    fourcc = cv2.VideoWriter_fourcc(*codec_name)
                    temp_path = str(self.output_dir / filename)
                    out = cv2.VideoWriter(temp_path, fourcc, 10.0, (screen_width, screen_height))
                    if out.isOpened():
                        output_file = temp_path
                        break
                except Exception as e:
                    print(f"Failed to initialize codec {codec_name}: {e}")
            
            if not out or not out.isOpened():
                raise RuntimeError("Could not open OpenCV VideoWriter with any codec.")

            self.actual_output_file = output_file
            
            # Start recording loop
            while self.recording:
                timestamp = time.time()
                frame = np.array(sct.grab(mon))
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                self.timestamps.append(timestamp)
                out.write(frame)
                time.sleep(0.1)  # ~10 FPS

        except Exception as e:
            self.error = str(e)
            self.recording = False
            print(f"Recording error: {e}")
            raise e
        finally:
            if out:
                out.release()
            if sct:
                try:
                    sct.close()
                except:
                    pass
            print("Recording resources released.")

    def stop_recording(self) -> Tuple[str, list]:
        """Stop recording and save the video.
        
        Returns:
            Tuple[str, list]: Path to saved video and list of timestamps
        """
        self.recording = False
        time.sleep(0.2)  # Give recording thread time to stop
        
        if self.error:
            raise RuntimeError(f"Recording failed: {self.error}")
            
        if not self.actual_output_file or not os.path.exists(self.actual_output_file):
            raise FileNotFoundError(f"Recording file was not found or was not created.")

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        timestamps = self.timestamps.copy()
        
        orig_ext = Path(self.actual_output_file).suffix
        temp_output = self.actual_output_file
        final_output = str(self.output_dir / f"recording_{timestamp}.mp4")
        
        self.timestamps = []
        self.actual_output_file = str(self.output_dir / "temp.avi") # Reset to default
        
        # Convert to web-compatible MP4 using ffmpeg
        import subprocess
        try:
            # Ensure the conversion is done with web-compatible settings
            subprocess.run([
                'ffmpeg', '-i', temp_output,
                '-c:v', 'libx264',  # Use H.264 codec
                '-preset', 'medium',
                '-crf', '23',
                '-movflags', '+faststart',
                '-y',
                final_output
            ], check=True, capture_output=True)
            
            # Remove temporary file
            if os.path.exists(temp_output):
                os.remove(temp_output)
            
            return final_output, timestamps
        except Exception as e:
            print(f"FFmpeg conversion failed or ffmpeg not found ({e}). Falling back to raw file.")
            fallback_output = str(self.output_dir / f"recording_{timestamp}{orig_ext}")
            import shutil
            shutil.move(temp_output, fallback_output)
            return fallback_output, timestamps

    def capture_screenshot(self, monitor: int = 1) -> np.ndarray:
        """Capture a single screenshot.
        
        Args:
            monitor (int): Monitor number to capture
            
        Returns:
            np.ndarray: Screenshot as numpy array
        """
        import mss
        with mss.mss() as sct:
            screenshot = np.array(sct.grab(sct.monitors[monitor]))
            return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)
