import unittest
import re

class TestConfluenceTranslation(unittest.TestCase):
    def test_regex_image_replacement(self):
        # Simulated uploaded attachments mapping
        uploaded_files = {
            "/output/screenshots/step_000_123.png": "step_000_123.png",
            "/output/screenshots/step_001_456.png": "step_001_456.png"
        }
        
        # Mock compiled HTML representation
        html_input = (
            "<h1>Guide Title</h1>\n"
            "<p>Step 1 description</p>\n"
            '<p><img alt="Step 1" src="/output/screenshots/step_000_123.png" /></p>\n'
            "<p>Step 2 description</p>\n"
            '<p><img alt="Step 2" src="/output/screenshots/step_001_456.png" /></p>\n'
            '<p><img alt="External Image" src="https://example.com/logo.png" /></p>'
        )
        
        # Translation function logic
        def replacer(match):
            tag = match.group(0)
            src_match = re.search(r'src="([^"]+)"', tag)
            if src_match:
                src = src_match.group(1)
                for original_url, filename in uploaded_files.items():
                    if original_url in src or src in original_url:
                        return f'<ac:image><ri:attachment ri:filename="{filename}" /></ac:image>'
            return tag

        confluence_html = re.sub(r'<img[^>]+>', replacer, html_input)
        
        # Assertions
        self.assertIn('<ac:image><ri:attachment ri:filename="step_000_123.png" /></ac:image>', confluence_html)
        self.assertIn('<ac:image><ri:attachment ri:filename="step_001_456.png" /></ac:image>', confluence_html)
        self.assertIn('<img alt="External Image" src="https://example.com/logo.png" />', confluence_html)
        self.assertNotIn('src="/output/screenshots/step_000_123.png"', confluence_html)

if __name__ == '__main__':
    unittest.main()
