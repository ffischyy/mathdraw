"""Download the MediaPipe hand-landmark model into mathdraw/assets so it ships inside the build.

The model is published by Google under the Apache 2.0 licence.
"""
import os
import urllib.request

URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "mathdraw", "assets", "hand_landmarker.task")
os.makedirs(os.path.dirname(DST), exist_ok=True)
if os.path.exists(DST) and os.path.getsize(DST) > 1_000_000:
    print("Model already present:", DST)
else:
    print("Downloading", URL)
    urllib.request.urlretrieve(URL, DST + ".part")
    os.replace(DST + ".part", DST)
    print("Saved", DST, os.path.getsize(DST), "bytes")
