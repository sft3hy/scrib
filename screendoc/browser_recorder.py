"""
Browser-based screen recorder using the Web Screen Capture API.
Injects a JavaScript component that calls getDisplayMedia() in the user's browser,
records via MediaRecorder, and POSTs the WebM blob back to a FastAPI upload endpoint.
"""
import os
import subprocess
import time
import threading
from pathlib import Path


def get_recorder_html(upload_url: str, width: int = 700, height: int = 420) -> str:
    """
    Returns HTML+JS for a browser-based screen recorder.
    Uses getDisplayMedia() to capture the real host screen,
    records as WebM and POSTs it to upload_url when stopped.
    """
    return f"""
<style>
  body {{ margin: 0; font-family: 'Segoe UI', sans-serif; background: transparent; }}
  .rec-panel {{
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border: 1px solid rgba(255,75,75,0.3);
    border-radius: 12px;
    padding: 20px 24px;
    color: #fff;
    max-width: 680px;
  }}
  .rec-title {{
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 4px;
    color: #fff;
  }}
  .rec-subtitle {{
    font-size: 0.8rem;
    color: rgba(255,255,255,0.5);
    margin-bottom: 16px;
  }}
  .rec-preview {{
    width: 100%;
    height: 180px;
    background: #000;
    border-radius: 8px;
    margin-bottom: 14px;
    object-fit: contain;
    display: block;
  }}
  .rec-btn {{
    padding: 10px 22px;
    border: none;
    border-radius: 8px;
    font-size: 0.95rem;
    font-weight: 600;
    cursor: pointer;
    margin-right: 10px;
    transition: all 0.2s;
  }}
  .btn-start {{ background: #FF4B4B; color: #fff; }}
  .btn-start:hover {{ background: #ff6b6b; }}
  .btn-stop {{ background: #e0e0e0; color: #333; display: none; }}
  .btn-stop:hover {{ background: #bdbdbd; }}
  .rec-status {{
    display: inline-block;
    margin-left: 10px;
    font-size: 0.85rem;
    color: rgba(255,255,255,0.6);
    vertical-align: middle;
  }}
  .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #FF4B4B; margin-right: 6px; animation: pulse 1s infinite; }}
  @keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.3; }} }}
  .rec-progress {{ margin-top: 14px; font-size: 0.82rem; color: rgba(255,255,255,0.55); min-height: 20px; }}
  .rec-success {{ color: #4caf50; font-weight: 600; }}
  .rec-error   {{ color: #FF4B4B; font-weight: 600; }}
</style>

<div class="rec-panel">
  <div class="rec-title">🖥️ Browser Screen Capture</div>
  <div class="rec-subtitle">Records your real screen — works on any OS, Docker, or cloud</div>

  <video id="preview" class="rec-preview" muted autoplay playsinline></video>

  <div>
    <button id="btnStart" class="rec-btn btn-start" onclick="startRecording()">▶ Start Recording</button>
    <button id="btnStop"  class="rec-btn btn-stop"  onclick="stopRecording()">⏹ Stop &amp; Upload</button>
    <span id="statusText" class="rec-status"></span>
  </div>
  <div id="progress" class="rec-progress"></div>
</div>

<script>
(function() {{
  const UPLOAD_URL = "{upload_url}";
  let stream = null;
  let mediaRecorder = null;
  let chunks = [];
  let timerInterval = null;
  let startTime = null;

  function setStatus(msg, cls) {{
    const el = document.getElementById('statusText');
    el.innerHTML = msg;
    el.className = 'rec-status ' + (cls || '');
  }}
  function setProgress(msg, cls) {{
    const el = document.getElementById('progress');
    el.innerHTML = msg;
    el.className = 'rec-progress ' + (cls || '');
  }}

  window.startRecording = async function() {{
    try {{
      // Request screen capture — browser shows system picker
      stream = await navigator.mediaDevices.getDisplayMedia({{
        video: {{ frameRate: 15, cursor: 'always' }},
        audio: false
      }});

      // Show live preview
      document.getElementById('preview').srcObject = stream;

      // Pick supported codec
      let mimeType = 'video/webm;codecs=vp9';
      if (!MediaRecorder.isTypeSupported(mimeType)) {{
        mimeType = 'video/webm;codecs=vp8';
      }}
      if (!MediaRecorder.isTypeSupported(mimeType)) {{
        mimeType = 'video/webm';
      }}

      mediaRecorder = new MediaRecorder(stream, {{ mimeType, videoBitsPerSecond: 2500000 }});
      chunks = [];

      mediaRecorder.ondataavailable = e => {{ if (e.data.size > 0) chunks.push(e.data); }};

      mediaRecorder.onstop = async () => {{
        clearInterval(timerInterval);
        document.getElementById('preview').srcObject = null;
        setStatus('');
        setProgress('⏳ Uploading recording to server...', '');

        const blob = new Blob(chunks, {{ type: mimeType }});
        const formData = new FormData();
        formData.append('file', blob, 'recording.webm');

        try {{
          const resp = await fetch(UPLOAD_URL, {{ method: 'POST', body: formData }});
          if (resp.ok) {{
            const data = await resp.json();
            setProgress('✅ Recording uploaded! Refresh the Review tab to continue.', 'rec-success');
            // Signal Streamlit
            if (window.parent && window.parent.postMessage) {{
              window.parent.postMessage({{ type: 'SCREENDOC_RECORDING_DONE', path: data.path }}, '*');
            }}
          }} else {{
            const txt = await resp.text();
            setProgress('❌ Upload failed: ' + txt, 'rec-error');
          }}
        }} catch(err) {{
          setProgress('❌ Upload error: ' + err.message, 'rec-error');
        }}
      }};

      // If user clicks browser "Stop sharing" button
      stream.getVideoTracks()[0].addEventListener('ended', () => {{
        if (mediaRecorder && mediaRecorder.state === 'recording') {{
          mediaRecorder.stop();
        }}
        stream.getTracks().forEach(t => t.stop());
        document.getElementById('btnStart').style.display = 'inline-block';
        document.getElementById('btnStop').style.display = 'none';
      }});

      mediaRecorder.start(500); // collect every 500ms
      startTime = Date.now();
      timerInterval = setInterval(() => {{
        const secs = Math.floor((Date.now() - startTime) / 1000);
        const mm = String(Math.floor(secs / 60)).padStart(2, '0');
        const ss = String(secs % 60).padStart(2, '0');
        setStatus('<span class="dot"></span> Recording ' + mm + ':' + ss, '');
      }}, 1000);

      document.getElementById('btnStart').style.display = 'none';
      document.getElementById('btnStop').style.display = 'inline-block';
      setProgress('');

    }} catch(err) {{
      if (err.name === 'NotAllowedError') {{
        setProgress('❌ Permission denied. Please allow screen capture when prompted.', 'rec-error');
      }} else {{
        setProgress('❌ Error: ' + err.message, 'rec-error');
      }}
    }}
  }};

  window.stopRecording = function() {{
    if (mediaRecorder && mediaRecorder.state === 'recording') {{
      mediaRecorder.stop();
    }}
    if (stream) {{
      stream.getTracks().forEach(t => t.stop());
    }}
    document.getElementById('btnStart').style.display = 'inline-block';
    document.getElementById('btnStop').style.display = 'none';
  }};
}})();
</script>
"""


def convert_to_mp4(input_path: str, output_path: str) -> bool:
    """Convert WebM to MP4 using ffmpeg. Returns True on success."""
    try:
        subprocess.run([
            "ffmpeg", "-y",
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-movflags", "+faststart",
            output_path
        ], check=True, capture_output=True, timeout=120)
        return True
    except Exception as e:
        print(f"ffmpeg conversion failed: {e}")
        return False
