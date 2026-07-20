import unittest
from unittest.mock import patch
import numpy as np
import cv2
from pathlib import Path
from screendoc import DocumentationGenerator

class TestLLMActions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create a dummy image file
        cls.dummy_path = Path("tests/dummy_test_image.png")
        img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        cv2.imwrite(str(cls.dummy_path), img)

    @classmethod
    def tearDownClass(cls):
        if cls.dummy_path.exists():
            cls.dummy_path.unlink()

    @patch('screendoc.DocumentationGenerator._call_llm')
    def test_generate_step_action_parsing(self, mock_call_llm):
        generator = DocumentationGenerator()
        
        # Test case 1: Raw clean JSON
        mock_call_llm.return_value = '{"action": "Clicked the Button", "interaction_type": "click", "coordinates": [45.0, 50.0]}'
        res = generator.generate_step_action(str(self.dummy_path))
        self.assertEqual(res["action"], "Clicked the Button")
        self.assertEqual(res["interaction_type"], "click")
        self.assertEqual(res["coordinates"], [45.0, 50.0])
        
        # Test case 2: Markdown wrapped JSON
        mock_call_llm.return_value = '```json\n{"action": "Typed text", "interaction_type": "type", "coordinates": [10.0, 20.0, 30.0, 40.0]}\n```'
        res = generator.generate_step_action(str(self.dummy_path))
        self.assertEqual(res["action"], "Typed text")
        self.assertEqual(res["interaction_type"], "type")
        self.assertEqual(res["coordinates"], [10.0, 20.0, 30.0, 40.0])
        
        # Test case 3: Invalid JSON fallback
        mock_call_llm.return_value = 'Failed to extract JSON correctly. Just standard description.'
        res = generator.generate_step_action(str(self.dummy_path))
        self.assertEqual(res["action"], "Failed to extract JSON correctly. Just standard description.")
        self.assertEqual(res["interaction_type"], "none")
        self.assertEqual(res["coordinates"], [0, 0, 0, 0])

if __name__ == '__main__':
    unittest.main()
