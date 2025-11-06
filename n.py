#!/usr/bin/env python3
"""
neo_hotkeys.py

Global hotkey helper for NeoBrowser workflow:
- Alt+C : capture the left-side viewport, auto-scroll to capture longer questions, OCR and store the combined text
- Alt+M : type or paste the last-captured question at the current cursor position

Notes:
- Uses `pynput` for global hotkeys, `pyautogui` for screenshots and input simulation,
  `pytesseract` for OCR and `pyperclip` for clipboard operations.
- Defaults to typing-mode (simulate keystrokes) to work around webviews that block programmatic paste.

Run:
  python neo_hotkeys.py
"""

from __future__ import annotations

import threading
import time
import difflib
import os
import re
from typing import List
import json
import subprocess
import sys
import io
import base64
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver
from PIL import Image

# Load environment variables from .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, will use system env vars only

try:
    import pyautogui
except Exception:
    print("pyautogui is required. Install with: pip install pyautogui")
    raise

try:
    import pytesseract
except Exception:
    print("pytesseract is required. Install with: pip install pytesseract")
    raise

try:
    import pyperclip
except Exception:
    print("pyperclip is required. Install with: pip install pyperclip")
    raise

# Configuration
DEFAULT_MAX_SCROLLS = 3  # Reduced to 3 captures only
SCROLL_PAUSE = 2.5  # seconds - very slow scroll for complete capture
DEFAULT_OUTPUT_DIR = r"D:\\neo"
OUTPUT_DIR = os.environ.get("NEO_DIR", DEFAULT_OUTPUT_DIR)

# If NEO_TYPE_MODE is set to '0' or 'false', use clipboard+Ctrl+V; otherwise default to typing mode
# Typing/paste mode
TYPE_MODE = os.environ.get("NEO_TYPE_MODE", "1") not in ("0", "false", "False", "")
# If NEO_USE_AI is set to '0' disable AI pipeline and use local heuristics
USE_AI = os.environ.get("NEO_USE_AI", "1") not in ("0", "false", "False", "")
# If NEO_ALLOW_OCR is set to '1' allow fallback to Tesseract OCR when AI fails
ALLOW_OCR = os.environ.get("NEO_ALLOW_OCR", "0") in ("1", "true", "True")
# Enable scrolling capture (stitch multiple screenshots)
SCROLL_CAPTURE = os.environ.get("NEO_SCROLL_CAPTURE", "1") not in ("0", "false", "False", "")
# Enable small HTTP receiver to accept images from phone/browser
ENABLE_HTTP = os.environ.get("NEO_ENABLE_HTTP", "0") in ("1", "true", "True")
# Port for the optional HTTP receiver
HTTP_PORT = int(os.environ.get("NEO_HTTP_PORT", "8765"))
# Auto-type immediately after capture when using AI pipeline
AUTO_TYPE_ON_CAPTURE = os.environ.get("NEO_AUTO_TYPE_ON_CAPTURE", "0") in ("1", "true", "True")

# Internal store of last captured question
last_captured_text: str = ""
last_lock = threading.Lock()


def ensure_tesseract() -> bool:
    """Try to find a tesseract binary and configure pytesseract.tesseract_cmd.

    Checks TESSERACT_CMD env, common install paths, then a shallow search on C:\\.
    """
    env_cmd = os.environ.get("TESSERACT_CMD")
    if env_cmd and os.path.isfile(env_cmd):
        pytesseract.pytesseract.tesseract_cmd = env_cmd
        print(f"Using TESSERACT_CMD from env: {env_cmd}")
        return True

    common = [
        r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
        r"C:\\Program Files (x86)\\Tesseract-OCR\\tesseract.exe",
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Tesseract-OCR', 'tesseract.exe')
    ]
    for p in common:
        if p and os.path.isfile(p):
            pytesseract.pytesseract.tesseract_cmd = p
            print(f"Found tesseract at: {p}")
            return True

    # shallow search to avoid long delays
    try:
        for root in [r"C:\\"]:
            for dirpath, dirnames, filenames in os.walk(root):
                if 'tesseract.exe' in filenames:
                    candidate = os.path.join(dirpath, 'tesseract.exe')
                    pytesseract.pytesseract.tesseract_cmd = candidate
                    print(f"Located tesseract at: {candidate}")
                    return True
                if len(dirpath.split(os.sep)) > 5:
                    continue
    except Exception:
        pass

    print("Tesseract binary not found. Set TESSERACT_CMD or install Tesseract for OCR.")
    return False


def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def capture_and_stitch_left(region: tuple, max_scrolls: int = DEFAULT_MAX_SCROLLS) -> str | None:
    """Capture the left region multiple times (page down) and stitch vertically.

    Returns path to the saved stitched image or None on failure.
    Continues scrolling until content stops changing or max_scrolls reached.
    """
    imgs: List[Image.Image] = []
    
    # Click in the middle of the capture region to ensure focus before scrolling
    try:
        click_x = region[0] + region[2] // 2
        click_y = region[1] + region[3] // 2
        pyautogui.click(click_x, click_y)
        time.sleep(0.3)  # Give time for focus
    except Exception:
        pass

    consecutive_duplicates = 0
    max_duplicates = 2  # Stop after 2 identical captures in a row

    for i in range(max_scrolls):
        try:
            pil_img = pyautogui.screenshot(region=region)
        except Exception:
            break
        # convert to PIL Image if necessary
        if not isinstance(pil_img, Image.Image):
            pil_img = Image.fromarray(pil_img)
        
        # Check if this image is very similar to the last one
        is_duplicate = False
        if len(imgs) >= 1:
            try:
                # Compare a larger section of the images
                prev_img = imgs[-1]
                # Compare bottom half of previous with current full image
                h1 = prev_img.height
                h2 = pil_img.height
                w = min(prev_img.width, pil_img.width, 400)
                
                # Get bottom portion of previous image
                crop_h = min(300, h1 // 2)
                prev_bottom = prev_img.crop((0, h1 - crop_h, w, h1))
                
                # Get top portion of current image  
                curr_top = pil_img.crop((0, 0, w, min(crop_h, h2)))
                
                # Compare as bytes
                if prev_bottom.size == curr_top.size:
                    prev_bytes = prev_bottom.tobytes()
                    curr_bytes = curr_top.tobytes()
                    # If more than 95% similar, consider it duplicate
                    similarity = sum(a == b for a, b in zip(prev_bytes, curr_bytes)) / len(prev_bytes)
                    if similarity > 0.95:
                        is_duplicate = True
            except Exception:
                pass
        
        if is_duplicate:
            consecutive_duplicates += 1
            if consecutive_duplicates >= max_duplicates:
                print(f"Scroll capture stopped: reached end of content at scroll {i}")
                break
        else:
            consecutive_duplicates = 0
            imgs.append(pil_img)
        
        # Scroll down for next capture
        try:
            pyautogui.press('pagedown')
        except Exception:
            break
        time.sleep(SCROLL_PAUSE)

    if not imgs:
        return None

    print(f"Captured {len(imgs)} screen segments")

    # Stitch vertically
    widths = [im.width for im in imgs]
    heights = [im.height for im in imgs]
    total_h = sum(heights)
    max_w = max(widths)
    stitched = Image.new('RGB', (max_w, total_h), (255, 255, 255))
    y = 0
    for im in imgs:
        stitched.paste(im, (0, y))
        y += im.height

    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out_path = os.path.join(OUTPUT_DIR, f"capture_image_{int(time.time())}.png")
        stitched.save(out_path)
        print(f"Saved stitched image: {out_path} ({total_h}px tall)")
        return out_path
    except Exception as e:
        print(f"Failed to save stitched image: {e}")
        return None


def combine_chunks(chunks: List[str]) -> str:
    seen = set()
    lines_out: List[str] = []
    for chunk in chunks:
        for line in chunk.splitlines():
            l = line.strip()
            if not l:
                continue
            if l not in seen:
                seen.add(l)
                lines_out.append(l)
    return "\n".join(lines_out).strip()


def extract_from_first_numbered(text: str) -> str:
    """Return substring starting at first '1.' or '1)' if present, else original text."""
    if not text:
        return text
    m = re.search(r"(?m)^[ \t]*1[\.)]\s*", text)
    if m:
        start = m.start()
        return text[start:].lstrip('\n\r')
    m2 = re.search(r"\b1[\.)]\s+", text)
    if m2:
        start = m2.start()
        return text[start:].lstrip('\n\r')
    return text


def trim_to_question_end(text: str) -> str:
    if not text:
        return text

    end_markers = [
        r"(?mi)^[ \t]*Answer[:\s]", r"(?mi)^[ \t]*Solution[:\s]", r"(?mi)^[ \t]*Explanation[:\s]",
        r"(?mi)^[ \t]*Correct Answer[:\s]", r"(?m)^[ \t]*答案[:\s]", r"(?m)^[ \t]*解答[:\s]",
    ]
    next_question = r"(?m)^[ \t]*(?:[2-9]\d*|[1-9]\d{2,})[\.)]\s+"

    earliest = None
    for pat in end_markers:
        m = re.search(pat, text)
        if m:
            pos = m.start()
            if earliest is None or pos < earliest:
                earliest = pos
    m2 = re.search(next_question, text)
    if m2:
        pos = m2.start()
        if earliest is None or pos < earliest:
            earliest = pos
    if earliest is not None:
        return text[:earliest].rstrip('\n\r ')
    return text


def signal_success():
    """Move cursor to top-right corner to signal success."""
    try:
        screen_w, screen_h = pyautogui.size()
        pyautogui.moveTo(screen_w - 5, 5, duration=0.3)
        print("✓ Success - cursor moved to top-right corner")
    except Exception:
        pass


def signal_failure():
    """Move cursor to top-left corner to signal failure."""
    try:
        pyautogui.moveTo(5, 5, duration=0.3)
        print("✗ Failed - cursor moved to top-left corner")
    except Exception:
        pass


def do_capture_and_store():
    global last_captured_text
    print("Starting capture (Alt+C)...")
    # ensure output dir exists and cleanup old temp files we previously created
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        for fname in os.listdir(OUTPUT_DIR):
            if fname.startswith('capture_chunk_') or fname.startswith('capture_image_'):
                try:
                    os.remove(os.path.join(OUTPUT_DIR, fname))
                except Exception:
                    pass
    except Exception:
        pass

    screen_w, screen_h = pyautogui.size()
    left_w = int(screen_w * 0.45)
    region = (0, 0, left_w, screen_h)

    img_path = None
    if SCROLL_CAPTURE:
        img_path = capture_and_stitch_left(region)
    else:
        ts = int(time.time())
        img_path = os.path.join(OUTPUT_DIR, f"capture_image_{ts}.png")
        try:
            img = pyautogui.screenshot(region=region)
            img.save(img_path)
        except Exception as e:
            print("Failed to capture image:", e)
            return

    if not img_path or not os.path.isfile(img_path):
        print("No image captured.")
        return

    print(f"Image captured at: {img_path}")
    print(f"Image file exists: {os.path.isfile(img_path)}")
    print(f"Image file size: {os.path.getsize(img_path) if os.path.isfile(img_path) else 0} bytes")

    combined: str | None = None
    AUTO_ANSWER = os.environ.get("NEO_AUTO_ANSWER", "1") not in ("0", "false", "False", "")

    if USE_AI:
        try:
            ai_script = os.path.join(os.path.dirname(__file__), 'ai_pipeline.py')
            if os.path.isfile(ai_script):
                cmd = [sys.executable, ai_script, '--image', img_path]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
                
                # Print any errors from the AI pipeline
                if proc.stderr:
                    print(f"AI pipeline stderr: {proc.stderr}")
                
                if proc.returncode == 0 and proc.stdout:
                    try:
                        out = json.loads(proc.stdout)
                        if AUTO_ANSWER and out.get('answer'):
                            combined = out.get('answer')
                        elif out.get('question'):
                            combined = out.get('question')
                    except Exception as e:
                        print(f"Failed to parse AI output: {e}")
                else:
                    print(f"AI pipeline failed with return code: {proc.returncode}")
        except Exception as e:
            print(f"Exception calling AI pipeline: {e}")
            pass

    # fallback to OCR only if allowed (before deleting image!)
    if not combined and ALLOW_OCR:
        try:
            text = pytesseract.image_to_string(Image.open(img_path)).strip() if os.path.exists(img_path) else ''
            combined = text
        except Exception:
            combined = None

    # NOW remove temp image after all processing complete
    try:
        if img_path and os.path.isfile(img_path):
            os.remove(img_path)
    except Exception:
        pass

    if not combined:
        print("AI extraction failed and OCR disabled or failed; no text available.")
        signal_failure()
        return

    # lightweight heuristics after extraction
    extracted = extract_from_first_numbered(combined)
    if extracted and extracted != combined:
        combined = extracted
    trimmed = trim_to_question_end(combined)
    if trimmed and trimmed != combined:
        combined = trimmed

    if not combined:
        print("Captured text empty after heuristics.")
        signal_failure()
        return

    with last_lock:
        last_captured_text = combined
        try:
            pyperclip.copy(combined)
            print("Stored captured text and copied to clipboard (if available). Press Alt+M to paste/type.")
        except Exception:
            print("Stored captured text internally (clipboard copy failed).")

    # Signal success
    signal_success()

    if AUTO_TYPE_ON_CAPTURE:
        # Type immediately (run in background thread to avoid blocking)
        threading.Thread(target=do_paste_from_store, daemon=True).start()


def do_paste_from_store():
    global last_captured_text
    with last_lock:
        text = last_captured_text
    if not text:
        print("No captured text available. Press Alt+C first.")
        return
    try:
        time.sleep(0.1)
        # Use pynput which uses Windows SendInput API - most reliable
        try:
            from pynput.keyboard import Controller
            keyboard_controller = Controller()
            print(f"Starting to type {len(text)} characters...")
            keyboard_controller.type(text)
            print(f"Finished typing all {len(text)} characters.")
        except Exception as e:
            print(f"ERROR: pynput failed: {e}")
            # Absolute fallback
            pyperclip.copy(text)
            pyautogui.hotkey('ctrl', 'v')
    except Exception as e:
        print(f"Failed to type: {e}")


class SimpleImageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Serve a simple web UI for viewing captured text and sending edits from phone."""
        if self.path == '/':
            # Main page with captured text display and edit form
            with last_lock:
                text = last_captured_text or "No text captured yet. Use Alt+C on PC or POST an image."
            
            html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Neo Hotkeys Remote</title>
    <style>
        * {{
            box-sizing: border-box;
        }}
        body {{ 
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            max-width: 900px; 
            margin: 0 auto; 
            padding: 20px;
            background-color: #2e2e2e;
            color: #b8bb26;
            line-height: 1.6;
        }}
        h1 {{ 
            color: #fabd2f;
            border-bottom: none;
            padding-bottom: 10px;
            font-size: 1em;
            text-transform: none;
            letter-spacing: 0;
            font-weight: normal;
        }}
        h2 {{
            color: #83a598;
            font-size: 1em;
            margin-bottom: 15px;
            text-transform: none;
            letter-spacing: 0;
            font-weight: normal;
        }}
        .section {{ 
            margin: 20px 0; 
            padding: 15px; 
            border: none; 
            background-color: transparent;
        }}
        textarea {{ 
            width: 100%; 
            min-height: 200px; 
            padding: 10px; 
            font-size: 14px; 
            border: none; 
            background-color: #3c3836;
            color: #ebdbb2;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            resize: vertical;
        }}
        textarea::placeholder {{
            color: #665c54;
        }}
        button {{ 
            background: #504945; 
            color: #fabd2f; 
            border: none; 
            padding: 10px 20px; 
            font-size: 14px; 
            cursor: pointer; 
            margin: 5px 5px 5px 0;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            text-transform: none;
            letter-spacing: 0;
        }}
        button:hover {{ 
            background: #665c54;
            border-color: #fabd2f;
        }}
        button:active {{
            background: #7c6f64;
        }}
        .success {{ 
            color: #b8bb26; 
            font-weight: bold; 
        }}
        .error {{ 
            color: #fb4934; 
            font-weight: bold; 
        }}
        pre {{ 
            background: #3c3836; 
            padding: 15px; 
            overflow-x: auto;
            border: none;
            color: #ebdbb2;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            line-height: 1.4;
            white-space: pre-wrap;
            word-wrap: break-word;
        }}
        input[type="file"] {{
            background: #3c3836;
            color: #fabd2f;
            border: none;
            padding: 8px;
            margin: 10px 0;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
        }}
        p {{
            color: #00cc00;
            margin: 10px 0;
        }}
        form {{
            margin: 0;
        }}
    </style>
</head>
<body>
    <h1>remote_subnet 192.168.1.0/24</h1>
    
    <div class="section">
        <h2>> trigger capture on pc</h2>
        <button onclick="triggerCapture()">[ capture left screen ]</button>
        <p id="captureStatus"></p>
        <p style="color: #665c54;">clicks pc screen, scrolls slowly, captures 3 screens, extracts with ai</p>
    </div>
    
    <div class="section">
        <h2>> captured text</h2>
        <pre id="captured">{text}</pre>
        <button onclick="location.reload()">[ refresh ]</button>
    </div>
    
    <div class="section">
        <h2>> send answer to pc</h2>
        <form id="sendForm">
            <textarea id="answer" name="text" placeholder="enter or edit the answer here...">{text}</textarea>
            <br>
            <button type="button" onclick="document.getElementById('answer').value=''; document.getElementById('status').textContent='';">[ clear ]</button>
            <button type="submit">[ send & type on pc ]</button>
            <button type="button" onclick="copyToPC()">[ send & copy to pc ]</button>
        </form>
        <p id="status"></p>
    </div>
    
    <div class="section">
        <h2>> upload image</h2>
        <input type="file" id="imageFile" accept="image/*" capture="environment">
        <button onclick="uploadImage()">[ upload & extract ]</button>
        <p id="uploadStatus"></p>
    </div>
    
    <script>
        async function triggerCapture() {{
            const status = document.getElementById('captureStatus');
            status.textContent = '> capturing on pc... (this may take 20-30 seconds)';
            status.className = '';
            
            const resp = await fetch('/trigger_capture', {{
                method: 'POST'
            }});
            
            if (resp.ok) {{
                status.textContent = '> capture started! wait for completion, then refresh.';
                status.className = 'success';
                setTimeout(() => location.reload(), 3000);
            }} else {{
                status.textContent = '> error: failed to trigger capture.';
                status.className = 'error';
            }}
        }}
        
        document.getElementById('sendForm').onsubmit = async (e) => {{
            e.preventDefault();
            const text = document.getElementById('answer').value;
            const resp = await fetch('/send_text', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{text: text, mode: 'type'}})
            }});
            const status = document.getElementById('status');
            if (resp.ok) {{
                status.textContent = '> sent! text will be typed on pc.';
                status.className = 'success';
            }} else {{
                status.textContent = '> error: failed to send.';
                status.className = 'error';
            }}
        }};
        
        async function copyToPC() {{
            const text = document.getElementById('answer').value;
            const resp = await fetch('/send_text', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{text: text, mode: 'copy'}})
            }});
            const status = document.getElementById('status');
            if (resp.ok) {{
                status.textContent = '> sent! text copied to pc clipboard.';
                status.className = 'success';
            }} else {{
                status.textContent = '> error: failed to send.';
                status.className = 'error';
            }}
        }}
        
        async function uploadImage() {{
            const file = document.getElementById('imageFile').files[0];
            if (!file) {{
                alert('please select an image first');
                return;
            }}
            const status = document.getElementById('uploadStatus');
            status.textContent = '> uploading and extracting...';
            
            const formData = new FormData();
            formData.append('image', file);
            
            const resp = await fetch('/send_image', {{
                method: 'POST',
                body: await file.arrayBuffer()
            }});
            
            if (resp.ok) {{
                status.textContent = '> image processed! refresh to see extracted text.';
                status.className = 'success';
                setTimeout(() => location.reload(), 1500);
            }} else {{
                status.textContent = '> error: failed to process image.';
                status.className = 'error';
            }}
        }}
    </script>
</body>
</html>"""
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
            return
        
        elif self.path == '/capture':
            # Return current captured text as JSON
            with last_lock:
                text = last_captured_text or ""
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'text': text}).encode('utf-8'))
            return
        
        else:
            self.send_response(404)
            self.end_headers()
            return

    def do_POST(self):
        # Accept POST /trigger_capture to start capture from phone
        if self.path == '/trigger_capture':
            # Start capture in background thread
            threading.Thread(target=do_capture_and_store, daemon=True).start()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')
            return
        
        # Accept POST /send_text to receive edited text from phone
        if self.path == '/send_text':
            length = int(self.headers.get('Content-Length', 0))
            if length == 0:
                self.send_response(400)
                self.end_headers()
                return
            
            try:
                data = json.loads(self.rfile.read(length).decode('utf-8'))
                text = data.get('text', '')
                mode = data.get('mode', 'type')  # 'type' or 'copy'
                
                if not text:
                    self.send_response(400)
                    self.end_headers()
                    return
                
                # Store the text
                with last_lock:
                    global last_captured_text
                    last_captured_text = text
                
                # Execute based on mode
                if mode == 'type':
                    threading.Thread(target=do_paste_from_store, daemon=True).start()
                else:  # copy
                    try:
                        pyperclip.copy(text)
                    except Exception:
                        pass
                
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'ok')
                return
            except Exception as e:
                print(f"Error in /send_text: {e}")
                self.send_response(500)
                self.end_headers()
                return
        
        # Accept POST /send_image with multipart/form-data or raw image bytes
        elif self.path == '/send_image':
            length = int(self.headers.get('Content-Length', 0))
            if length == 0:
                self.send_response(400)
                self.end_headers()
                return
        content_type = self.headers.get('Content-Type', '')
        data = self.rfile.read(length)
        img_path = None
        try:
            if 'multipart/form-data' in content_type:
                # crude parse: find first file part by boundary
                boundary = content_type.split('boundary=')[-1]
                parts = data.split(b'--' + boundary.encode())
                for part in parts:
                    if b'Content-Disposition' in part and b'filename=' in part:
                        idx = part.find(b'\r\n\r\n')
                        if idx != -1:
                            img_bytes = part[idx+4: -2]
                            img_path = os.path.join(OUTPUT_DIR, f"capture_image_recv_{int(time.time())}.png")
                            with open(img_path, 'wb') as fh:
                                fh.write(img_bytes)
                            break
            else:
                # assume raw image bytes
                img_path = os.path.join(OUTPUT_DIR, f"capture_image_recv_{int(time.time())}.png")
                with open(img_path, 'wb') as fh:
                    fh.write(data)
        except Exception:
            img_path = None

        if not img_path or not os.path.isfile(img_path):
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'failed')
            return

        # process image: call ai_pipeline like hotkey capture
        try:
            ai_script = os.path.join(os.path.dirname(__file__), 'ai_pipeline.py')
            combined = None
            if USE_AI and os.path.isfile(ai_script):
                cmd = [sys.executable, ai_script, '--image', img_path]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
                if proc.returncode == 0 and proc.stdout:
                    try:
                        out = json.loads(proc.stdout)
                        if out.get('answer'):
                            combined = out.get('answer')
                        elif out.get('question'):
                            combined = out.get('question')
                    except Exception:
                        combined = None
            if not combined and ALLOW_OCR:
                try:
                    combined = pytesseract.image_to_string(Image.open(img_path)).strip()
                except Exception:
                    combined = None

            if combined:
                with last_lock:
                    last_captured_text = combined
                try:
                    pyperclip.copy(combined)
                except Exception:
                    pass
                # optionally auto-type
                if AUTO_TYPE_ON_CAPTURE:
                    threading.Thread(target=do_paste_from_store, daemon=True).start()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'ok')
            else:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'no_text')
        finally:
            try:
                if img_path and os.path.isfile(img_path):
                    os.remove(img_path)
            except Exception:
                pass
            return
        
        # Unknown endpoint
        self.send_response(404)
        self.end_headers()
        return


def start_http_server():
    try:
        import socket
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        
        server = HTTPServer(('0.0.0.0', HTTP_PORT), SimpleImageHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        print(f"\n{'='*60}")
        print(f"📱 Neo Hotkeys Web UI started!")
        print(f"{'='*60}")
        print(f"Local access:  http://localhost:{HTTP_PORT}")
        print(f"Phone access:  http://{local_ip}:{HTTP_PORT}")
        print(f"{'='*60}\n")
    except Exception as e:
        print("Failed to start HTTP receiver:", e)


def main():
    print("neo_hotkeys: Phone-controlled capture and typing via web UI.")
    print("No keyboard hotkeys active - use web interface to control.")
    pyautogui.FAILSAFE = True
    
    # Do not require Tesseract by default; only initialize if OCR fallback is enabled
    if ALLOW_OCR:
        ensure_tesseract()

    # Start HTTP receiver - required for phone control
    if ENABLE_HTTP:
        start_http_server()
        try:
            # Keep running indefinitely
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nExiting neo_hotkeys.")
    else:
        print("ERROR: NEO_ENABLE_HTTP must be set to 1 for phone control to work!")
        print("Set NEO_ENABLE_HTTP=1 in .env file")
        sys.exit(1)


if __name__ == '__main__':
    main()
