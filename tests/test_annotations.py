import unittest
import numpy as np
import cv2
import base64
import os
from pathlib import Path
from server import choose_contrast_color, save_base64_screenshot, SCREENSHOTS_DIR, find_action_centroid_by_diff

class TestAnnotations(unittest.TestCase):
    def test_choose_contrast_color_dark_background(self):
        # Create a dark (black) image ROI
        roi = np.zeros((10, 10, 3), dtype=np.uint8)
        color = choose_contrast_color(roi)
        # For dark background, a light/bright color should be selected (e.g. Yellow, Orange, Sky Blue)
        self.assertIsNotNone(color)
        
    def test_choose_contrast_color_light_background(self):
        # Create a light (white) image ROI
        roi = np.ones((10, 10, 3), dtype=np.uint8) * 255
        color = choose_contrast_color(roi)
        # For light background, a darker contrast color should be selected
        self.assertIsNotNone(color)

    def test_save_base64_screenshot_click(self):
        # Generate a solid color base64 image (gray 100x100 png)
        img = np.ones((100, 100, 3), dtype=np.uint8) * 128
        _, buffer = cv2.imencode('.png', img)
        b64_data = base64.b64encode(buffer).decode('utf-8')
        
        # Click annotation at (50%, 50%)
        url, is_annotated = save_base64_screenshot(
            b64_data,
            click_x_percent=50.0,
            click_y_percent=50.0,
            is_typing=False
        )
        
        self.assertTrue(is_annotated)
        self.assertTrue(url.startswith("/output/screenshots/"))
        
        # Verify file exists
        filename = url.replace("/output/screenshots/", "")
        filepath = SCREENSHOTS_DIR / filename
        self.assertTrue(filepath.exists())
        
        # Clean up
        if filepath.exists():
            filepath.unlink()

    def test_save_base64_screenshot_typing(self):
        # Generate a solid color base64 image (gray 100x100 png)
        img = np.ones((100, 100, 3), dtype=np.uint8) * 128
        _, buffer = cv2.imencode('.png', img)
        b64_data = base64.b64encode(buffer).decode('utf-8')
        
        # Typing annotation at (20%, 30%) with size (40%, 15%)
        url, is_annotated = save_base64_screenshot(
            b64_data,
            click_x_percent=20.0,
            click_y_percent=30.0,
            click_width_percent=40.0,
            click_height_percent=15.0,
            is_typing=True
        )
        
        self.assertTrue(is_annotated)
        self.assertTrue(url.startswith("/output/screenshots/"))
        
        # Verify file exists
        filename = url.replace("/output/screenshots/", "")
        filepath = SCREENSHOTS_DIR / filename
        self.assertTrue(filepath.exists())
        
        # Clean up
        if filepath.exists():
            filepath.unlink()

    def test_find_action_centroid_by_diff(self):
        # Create a base white image (200x200)
        img_prev = np.ones((200, 200, 3), dtype=np.uint8) * 255

        # Create a current image with a 20x20 black square at (90,90) to (110,110)
        img_curr = np.ones((200, 200, 3), dtype=np.uint8) * 255
        img_curr[90:110, 90:110] = 0

        # Save temp images
        path_prev = Path("tests/temp_prev.png")
        path_curr = Path("tests/temp_curr.png")
        cv2.imwrite(str(path_prev), img_prev)
        cv2.imwrite(str(path_curr), img_curr)

        try:
            result = find_action_centroid_by_diff(path_prev, path_curr)
            self.assertIsNotNone(result, "Expected centroid result but got None")
            cx_pct, cy_pct, bw_pct, bh_pct = result

            # The centroid should be near the center of the 200x200 image (50%, 50%)
            # allowing ~15% tolerance for Gaussian spreading
            self.assertAlmostEqual(cx_pct, 50.0, delta=15.0,
                msg=f"cx_pct={cx_pct:.1f} should be near 50%")
            self.assertAlmostEqual(cy_pct, 50.0, delta=15.0,
                msg=f"cy_pct={cy_pct:.1f} should be near 50%")
        finally:
            if path_prev.exists():
                path_prev.unlink()
            if path_curr.exists():
                path_curr.unlink()

if __name__ == '__main__':
    unittest.main()
