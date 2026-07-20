import unittest
import numpy as np
import cv2
import base64
from server import choose_contrast_color, save_base64_screenshot

class TestDrawVerification(unittest.TestCase):
    def test_drawing_changes_pixels(self):
        # Create a plain white image (100x100, 3 channels)
        img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        _, buffer = cv2.imencode('.png', img)
        b64_data = base64.b64encode(buffer).decode('utf-8')
        
        # Draw a click annotation at (50%, 50%) -> center is (50, 50)
        url, is_annotated = save_base64_screenshot(
            b64_data,
            click_x_percent=50.0,
            click_y_percent=50.0,
            is_typing=False
        )
        
        self.assertTrue(is_annotated)
        
        # Load the saved image from output/screenshots
        filename = url.replace("/output/screenshots/", "")
        from server import SCREENSHOTS_DIR
        filepath = SCREENSHOTS_DIR / filename
        
        saved_img = cv2.imread(str(filepath))
        self.assertIsNotNone(saved_img)
        
        # The center at (50, 50) should be drawn on (not pure white anymore)
        center_pixel = saved_img[50, 50]
        # Pure white is [255, 255, 255]
        # The center dot is black [0, 0, 0] or colored, so it should not be white!
        self.assertTrue(any(val < 255 for val in center_pixel), f"Pixel at center is unchanged: {center_pixel}")
        
        # Clean up
        if filepath.exists():
            filepath.unlink()

if __name__ == '__main__':
    unittest.main()
