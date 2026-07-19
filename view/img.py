from __future__ import annotations

import pathlib

import cv2
import numpy as np

class Img:
    def __init__(self):
        self.img = None

    def read(self, path: str | pathlib.Path,
             size: tuple[int, int] | None = None,
             keep_aspect: bool = False,
             interpolation: int = cv2.INTER_AREA) -> "Img":
        """
        Load `path` into self.img and **optionally resize**.

        Parameters
        ----------
        path : str | Path
            Image file to load.
        size : (width, height) | None
            Target size in pixels.  If None, keep original.
        keep_aspect : bool
            • False  → resize exactly to `size`
            • True   → shrink so the *longer* side fits `size` while
                       preserving aspect ratio (no cropping).
        interpolation : OpenCV flag
            E.g.  `cv2.INTER_AREA` for shrink, `cv2.INTER_LINEAR` for enlarge.

        Returns
        -------
        Img
            `self`, so you can chain:  `sprite = Img().read("foo.png", (64,64))`
        """
        path = str(path)
        self.img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if self.img is None:
            raise FileNotFoundError(f"Cannot load image: {path}")

        if size is not None:
            target_w, target_h = size
            h, w = self.img.shape[:2]

            if keep_aspect:
                scale = min(target_w / w, target_h / h)
                new_w, new_h = int(w * scale), int(h * scale)
            else:
                new_w, new_h = target_w, target_h

            self.img = cv2.resize(self.img, (new_w, new_h), interpolation=interpolation)

        return self

    def draw_on(self, other_img, x, y):
        if self.img is None or other_img.img is None:
            raise ValueError("Both images must be loaded before drawing.")

        if self.img.shape[2] != other_img.img.shape[2]:
            if self.img.shape[2] == 3 and other_img.img.shape[2] == 4:
                self.img = cv2.cvtColor(self.img, cv2.COLOR_BGR2BGRA)
            elif self.img.shape[2] == 4 and other_img.img.shape[2] == 3:
                self.img = cv2.cvtColor(self.img, cv2.COLOR_BGRA2BGR)

        h, w = self.img.shape[:2]
        H, W = other_img.img.shape[:2]

        if y + h > H or x + w > W:
            raise ValueError("Logo does not fit at the specified position.")

        roi = other_img.img[y:y + h, x:x + w]

        if self.img.shape[2] == 4:
            b, g, r, a = cv2.split(self.img)
            mask = a / 255.0
            for c in range(3):
                roi[..., c] = (1 - mask) * roi[..., c] + mask * self.img[..., c]
        else:
            other_img.img[y:y + h, x:x + w] = self.img

    def put_text(self, txt, x, y, font_size, color=(255, 255, 255, 255), thickness=1):
        if self.img is None:
            raise ValueError("Image not loaded.")
        cv2.putText(self.img, txt, (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, font_size,
                    color, thickness, cv2.LINE_AA)

    def text_size(self, txt, font_size, thickness=1):
        """(width, height) `txt` would occupy at `font_size`/`thickness`,
        for callers that need to center or lay out text before drawing it."""
        (w, h), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, font_size, thickness)
        return w, h

    def rectangle(self, top_left, bottom_right, color, thickness):
        if self.img is None:
            raise ValueError("Image not loaded.")
        cv2.rectangle(self.img, top_left, bottom_right, color, thickness)

    def to_bgra(self):
        """Adds an opaque alpha channel in place if `self.img` is BGR."""
        if self.img is None:
            raise ValueError("Image not loaded.")
        if self.img.shape[2] == 3:
            self.img = cv2.cvtColor(self.img, cv2.COLOR_BGR2BGRA)

    def blend_rect(self, top, left, bottom, right, color, alpha):
        """Blends `color` into the BGR channels of the [top:bottom, left:right]
        region: `region * (1 - alpha) + color * alpha`, computed by hand so
        the compositing math is ours rather than a ready-made cv2 blend."""
        if self.img is None:
            raise ValueError("Image not loaded.")
        region = self.img[top:bottom, left:right, :3]
        overlay = np.array(color, dtype=np.float32)
        blended = region.astype(np.float32) * (1 - alpha) + overlay * alpha
        region[:] = blended.astype(region.dtype)

    def blend_circle(self, cx, cy, radius, color, alpha):
        """Like `blend_rect`, but only inside the circle of `radius` centered
        on (cx, cy) - the mask is our own squared-distance test, not
        `cv2.circle`, since the point is to compute the region ourselves."""
        if self.img is None:
            raise ValueError("Image not loaded.")
        top, left = cy - radius, cx - radius
        region = self.img[top:cy + radius, left:cx + radius, :3]
        yy, xx = np.mgrid[0:region.shape[0], 0:region.shape[1]]
        mask = (xx - radius) ** 2 + (yy - radius) ** 2 <= radius ** 2

        overlay = np.array(color, dtype=np.float32)
        blended = region[mask].astype(np.float32) * (1 - alpha) + overlay * alpha
        region[mask] = blended.astype(region.dtype)

    @staticmethod
    def create(width, height, color=(0, 0, 0, 255)):
        """A blank canvas of `width`x`height` filled with `color` - for
        building composite layouts (e.g. side panels) that don't start from
        a file on disk."""
        img = Img()
        img.img = np.full((height, width, len(color)), color, dtype=np.uint8)
        return img

    def show(self):
        if self.img is None:
            raise ValueError("Image not loaded.")
        cv2.imshow("Image", self.img)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    def show_frame(self, window_name):
        """Non-blocking `imshow` for a render loop - unlike `show()`, it
        doesn't wait for a keypress or tear the window down afterwards."""
        if self.img is None:
            raise ValueError("Image not loaded.")
        cv2.imshow(window_name, self.img)

    @staticmethod
    def open_window(window_name):
        cv2.namedWindow(window_name)

    @staticmethod
    def set_mouse_callback(window_name, on_click=None, on_double_click=None):
        """Registers `on_click(x, y)` / `on_double_click(x, y)`, translating
        cv2's raw mouse event codes so callers never need to import cv2 to
        wire up mouse handling."""
        def _handler(event, x, y, flags, userdata):
            if event == cv2.EVENT_LBUTTONDOWN and on_click is not None:
                on_click(x, y)
            elif event == cv2.EVENT_LBUTTONDBLCLK and on_double_click is not None:
                on_double_click(x, y)
        cv2.setMouseCallback(window_name, _handler)

    @staticmethod
    def wait_key(delay_ms):
        return cv2.waitKey(delay_ms) & 0xFF

    @staticmethod
    def is_window_visible(window_name):
        return cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) >= 1

    @staticmethod
    def close_all_windows():
        cv2.destroyAllWindows()
