"""Webcam capture + MediaPipe hand landmarks in a background thread.

Uses the MediaPipe Tasks ``HandLandmarker`` (current API).  The model file
(~8 MB) is downloaded once to the app config folder on first run.  If an
older MediaPipe with ``mp.solutions`` is installed, that is used instead.
The frame is mirrored *before* detection so landmarks match what is shown.
"""
from __future__ import annotations

import os
import sys
import time
import urllib.request

import logging

import numpy as np
from PySide6.QtCore import QStandardPaths, QThread, Signal
from PySide6.QtGui import QImage

log = logging.getLogger(__name__)

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")


def model_path():
    """Bundled model (shipped builds) or a per-user cached copy (source checkouts)."""
    from .resources import asset

    bundled = asset("hand_landmarker.task")
    if os.path.exists(bundled) and os.path.getsize(bundled) > 1_000_000:
        return bundled
    from .app import data_dir

    return os.path.join(data_dir(), "hand_landmarker.task")


class _Detector:
    def __init__(self):
        import mediapipe as mp

        self.mp = mp
        self.legacy = None
        self.tasks = None
        if hasattr(mp, "solutions"):
            self.legacy = mp.solutions.hands.Hands(max_num_hands=1, model_complexity=1,
                                                   min_detection_confidence=0.6, min_tracking_confidence=0.5)
            return
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision

        path = model_path()
        if not os.path.exists(path) or os.path.getsize(path) < 1_000_000:
            # only happens when running from source without tools/fetch_model.py
            tmp = path + ".part"
            urllib.request.urlretrieve(MODEL_URL, tmp)
            os.replace(tmp, path)
        opts = vision.HandLandmarkerOptions(
            base_options=mpt.BaseOptions(model_asset_path=path),
            running_mode=vision.RunningMode.VIDEO, num_hands=1,
            min_hand_detection_confidence=0.6, min_hand_presence_confidence=0.5, min_tracking_confidence=0.5)
        self.tasks = vision.HandLandmarker.create_from_options(opts)
        self.t0 = time.monotonic()
        self.last_ts = -1

    def detect(self, rgb):
        """Returns (21,3) normalized landmarks or None."""
        if self.legacy is not None:
            r = self.legacy.process(rgb)
            if not r.multi_hand_landmarks:
                return None
            return np.array([[p.x, p.y, p.z] for p in r.multi_hand_landmarks[0].landmark])
        img = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        ts = int((time.monotonic() - self.t0) * 1000)
        if ts <= self.last_ts:
            ts = self.last_ts + 1
        self.last_ts = ts
        r = self.tasks.detect_for_video(img, ts)
        if not r.hand_landmarks:
            return None
        return np.array([[p.x, p.y, p.z] for p in r.hand_landmarks[0]])

    def close(self):
        try:
            (self.legacy or self.tasks).close()
        except Exception:
            pass


class TrackerThread(QThread):
    frame_ready = Signal(QImage)
    hand = Signal(object)  # np.ndarray (21,3) or None
    status = Signal(bool, str)  # camera ok, message

    def __init__(self, camera_index=0, mirror=True, width=1280, height=720):
        super().__init__()
        self.camera_index = camera_index
        self.mirror = mirror
        self.size = (width, height)
        self._stop = False

    def stop(self):
        self._stop = True
        self.wait(3000)

    def run(self):
        import cv2

        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        log.info("Opening camera %s", self.camera_index)
        cap = cv2.VideoCapture(self.camera_index, backend)
        if not cap.isOpened():
            cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            self.status.emit(False, f"Camera {self.camera_index} could not be opened")
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
        try:
            self.status.emit(True, "Loading hand-tracking model…")
            det = _Detector()
        except Exception as e:
            log.exception("Hand tracking model failed to load")
            self.status.emit(True, f"Hand tracking unavailable: {e}")
            det = None
        self.status.emit(True, "Camera running")
        fails = 0
        while not self._stop:
            ok, frame = cap.read()
            if not ok:
                fails += 1
                if fails > 30:
                    self.status.emit(False, "Camera stopped delivering frames")
                    break
                self.msleep(30)
                continue
            fails = 0
            if self.mirror:
                frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            lm = None
            if det is not None:
                try:
                    lm = det.detect(rgb)
                except Exception:
                    lm = None
            h, w, _ = rgb.shape
            img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
            self.frame_ready.emit(img)
            self.hand.emit(lm)
        cap.release()
        if det:
            det.close()
