import os
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from PIL import Image
import requests
import base64
from fpdf import FPDF
from io import BytesIO
import markdown
import pdfkit
import time
import re
from .step_detector import Step


class PDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)
        self.add_page()
        self.set_font("Arial", "B", 24)

    def header(self):
        # Add logo if exists
        logo_path = Path("assets/logo.png")
        if logo_path.exists():
            self.image(str(logo_path), 10, 8, 33)
        self.set_font("Arial", "B", 12)
        self.cell(0, 10, "Peely Documentation", 0, 1, "R")
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", 0, 0, "C")

    def chapter_title(self, title):
        self.set_font("Arial", "B", 20)
        self.set_fill_color(240, 240, 240)
        self.cell(0, 15, title, 0, 1, "L", True)
        self.ln(10)

    def chapter_body(self, body):
        self.set_font("Arial", "", 12)
        self.multi_cell(0, 10, body)
        self.ln()

    def add_step(self, number: int, description: str, image_path: str = None):
        # Step header
        self.set_font("Arial", "B", 14)
        self.set_fill_color(230, 230, 230)
        self.cell(0, 10, f"Step {number}", 0, 1, "L", True)
        self.ln(5)

        # Step description
        self.set_font("Arial", "", 12)
        self.multi_cell(0, 8, description)
        self.ln(5)

        # Step image
        if image_path and Path(image_path).exists():
            # Calculate image dimensions to fit page width while maintaining aspect ratio
            page_width = self.w - 40  # 20mm margins on each side
            img = Image.open(image_path)
            width, height = img.size
            aspect = height / width

            img_width = page_width
            img_height = page_width * aspect

            # Add a new page if the image won't fit
            if self.get_y() + img_height + 20 > self.h:
                self.add_page()

            # Center the image
            x = (self.w - img_width) / 2
            self.image(image_path, x, self.get_y(), img_width)
            self.ln(img_height + 10)


class DocumentationGenerator:
    def __init__(self):
        """Initialize the documentation generator."""
        load_dotenv()

        # Configure LLM API (Ollama native)
        base_url = os.getenv("LLM_API_BASE", "http://localhost:11434")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        if base_url.endswith("/"):
            base_url = base_url[:-1]
        self.ollama_base = base_url
        self.model_name = os.getenv("MODEL_NAME", "meta-llama/llama-4-scout-17b-16e-instruct")

        # Rate limiting parameters
        self.request_delay = 1.0  # Delay between requests in seconds
        self.max_retries = 3

    def _image_to_base64(self, img: Image.Image) -> str:
        """Resize and compress PIL Image to JPEG base64 string for efficient API transmission."""
        # Convert to RGB mode (required for JPEG)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        # Downscale image if width > 1024px to reduce token/payload size
        max_width = 1024
        w, h = img.size
        if w > max_width:
            ratio = max_width / w
            img = img.resize((max_width, int(h * ratio)), Image.Resampling.LANCZOS)

        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=70)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def _call_llm(self, messages: List[Dict]) -> str:
        """Call the configured LLM API (Ollama or Groq)."""
        delay = 1.0

        if self.model_name == "meta-llama/llama-4-scout-17b-16e-instruct":
            from groq import Groq
            import groq
            api_key = os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY")
            if not api_key:
                raise Exception("GROQ_API_KEY is not set. Please configure GROQ_API_KEY in your settings or environment.")
            
            client = Groq(api_key=api_key)
            
            # Preemptive sleep between requests to avoid hitting the 30 RPM limit
            time.sleep(1.5)
            
            # Increase retries to handle rate limit backoff (up to 5 attempts)
            for attempt in range(5):
                try:
                    completion = client.chat.completions.create(
                        model=self.model_name,
                        messages=messages,
                        temperature=0.2,
                        max_completion_tokens=1024,
                    )
                    return completion.choices[0].message.content.strip()
                except groq.RateLimitError as e:
                    retry_after = 5.0
                    try:
                        headers = getattr(e, "response", None) and e.response.headers
                        if headers and "retry-after" in headers:
                            retry_after = float(headers["retry-after"]) + 0.5
                    except Exception:
                        pass
                    
                    print(f"Groq Rate Limit hit (429). Retrying after {retry_after}s...")
                    time.sleep(retry_after)
                except Exception as e:
                    if attempt == 4:
                        raise e
                    time.sleep(delay)
                    delay *= 2
            return ""

        # Default Ollama native /api/chat endpoint
        url = f"{self.ollama_base}/api/chat"
        headers = {"Content-Type": "application/json"}

        # Convert messages from OpenAI format -> Ollama native format
        ollama_messages = []
        for msg in messages:
            content = msg.get("content", "")
            images = []

            if isinstance(content, list):
                # Extract text and images from OpenAI-style content blocks
                text_parts = []
                for block in content:
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif block.get("type") == "image_url":
                        # Strip the data URI prefix, keep only raw base64
                        url_str = block["image_url"]["url"]
                        if "," in url_str:
                            url_str = url_str.split(",", 1)[1]
                        images.append(url_str)
                content = "\n".join(text_parts)

            ollama_msg = {"role": msg["role"], "content": content}
            if images:
                ollama_msg["images"] = images
            ollama_messages.append(ollama_msg)

        payload = {
            "model": self.model_name,
            "messages": ollama_messages,
            "stream": False,
            "options": {"temperature": 0.2},
        }

        for attempt in range(self.max_retries):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                result = response.json()
                return result["message"]["content"].strip()
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise e
                time.sleep(delay)
                delay *= 2


    def generate_step_description(
        self, screenshot_path: str, prev_screenshot: str = None
    ) -> str:
        """Generate a description for a step using the LLM Vision API.

        Args:
            screenshot_path (str): Path to the screenshot
            prev_screenshot (str): Path to previous screenshot for context

        Returns:
            str: Generated description
        """
        try:
            # Load current screenshot
            with open(screenshot_path, "rb") as img_file:
                try:
                    current_image_data = Image.open(BytesIO(img_file.read()))
                except Exception as e:
                    print(f"Error opening image: {e}")
                    return f"Error opening image: {e}"
            # Load previous screenshot if available
            prev_image_data = None
            if prev_screenshot and Path(prev_screenshot).exists():
                with open(prev_screenshot, "rb") as img_file:
                    try:
                        prev_image_data = Image.open(BytesIO(img_file.read()))
                    except Exception as e:
                        print(f"Error opening image: {e}")

            # Create prompt based on context
            if prev_image_data:
                prompt = """Analyze these two consecutive screenshots from a process documentation and:
1. Describe what changed between the previous and current screen
2. Explain the user's action that likely caused this change
3. Identify any important UI elements or data that were modified
4. Note any system responses or feedback shown
5. Highlight any potential dependencies or prerequisites for this step

CRITICAL: Do NOT mention or reference 'Scrib', 'Scribe', or 'Peely' tools/applications in any way. These are only the recording tools. Focus solely on documenting the target application workflow shown on the screen.
Focus on being specific and actionable. Use clear, professional language.
Previous screenshot shows the starting state, current screenshot shows the result."""
            else:
                prompt = """Analyze this screenshot from a process documentation and:
1. Describe the current state of the application/screen
2. Identify key UI elements and their purpose
3. Note any important data or settings shown
4. Highlight any system status or feedback messages
5. Suggest what actions might be available or required

CRITICAL: Do NOT mention or reference 'Scrib', 'Scribe', or 'Peely' tools/applications in any way. These are only the recording tools. Focus solely on documenting the target application workflow shown on the screen.
Focus on being specific and actionable. Use clear, professional language."""

            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]

            # Add images in base64
            if prev_image_data:
                prev_base64 = self._image_to_base64(prev_image_data)
                messages[0]["content"].append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{prev_base64}"},
                    }
                )

            current_base64 = self._image_to_base64(current_image_data)
            messages[0]["content"].append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{current_base64}"},
                }
            )

            # Call Sanctuary LLM
            description = self._call_llm(messages)

            # Post-process the description
            description = self._enhance_description(description)

            time.sleep(self.request_delay)  # Rate limiting
            return description

        except Exception as e:
            print(f"Error processing screenshots: {str(e)}")
            raise Exception(f"LLM API Error: Failed to process screenshots. {str(e)}")

    def _enhance_description(self, description: str) -> str:
        """Enhance the generated description with additional context and formatting.

        Args:
            description (str): Raw generated description

        Returns:
            str: Enhanced description
        """
        # Split description into paragraphs
        paragraphs = description.split("\n\n")

        # Process each paragraph
        enhanced_paragraphs = []
        for para in paragraphs:
            # Clean up formatting
            para = para.strip()

            # Convert bullet points to proper markdown
            if para.startswith("•"):
                para = "- " + para[1:].strip()
            elif para.startswith("* "):
                para = "- " + para[2:].strip()

            # Highlight important terms
            para = re.sub(
                r"(button|menu|dialog|window|panel|screen|field|input|output)",
                r"**\1**",
                para,
                flags=re.IGNORECASE,
            )

            # Add paragraph to list
            if para:
                enhanced_paragraphs.append(para)

        # Join paragraphs with proper spacing
        enhanced_description = "\n\n".join(enhanced_paragraphs)

        # Add context markers if they don't exist
        if not any(
            marker in enhanced_description.lower()
            for marker in ["result:", "outcome:", "effect:", "change:"]
        ):
            enhanced_description += "\n\n**Result:** " + self._generate_result_summary(
                enhanced_description
            )

        return enhanced_description

    def _generate_result_summary(self, description: str) -> str:
        """Generate a summary of the step's result based on the description.

        Args:
            description (str): Step description

        Returns:
            str: Result summary
        """
        try:
            prompt = f"""Based on this step description, provide a one-sentence summary of the result or outcome:

{description}

Focus on the concrete change or achievement, not the process."""

            messages = [{"role": "user", "content": prompt}]
            return self._call_llm(messages)
        except Exception as e:
            print(f"Error generating result summary: {str(e)}")
            return "Step completed successfully."

    def _link_steps(self, steps: List[Step]) -> List[Step]:
        """Add contextual links between steps.

        Args:
            steps (List[Step]): List of steps to process

        Returns:
            List[Step]: Steps with added context links
        """
        for i, step in enumerate(steps):
            if not hasattr(step, "description") or not step.description:
                continue

            # Add context from previous step if available
            if (
                i > 0
                and hasattr(steps[i - 1], "description")
                and steps[i - 1].description
            ):
                context = self._generate_step_context(
                    steps[i - 1].description, step.description
                )
                if context:
                    step.description = f"{context}\n\n{step.description}"

        return steps

    def _generate_step_context(self, prev_desc: str, curr_desc: str) -> str:
        """Generate contextual link between steps.

        Args:
            prev_desc (str): Previous step description
            curr_desc (str): Current step description

        Returns:
            str: Contextual link text
        """
        try:
            prompt = f"""Given these two consecutive steps in a process, create a one-sentence transition that shows how they are related:

Previous Step:
{prev_desc}

Current Step:
{curr_desc}

Focus on cause-and-effect or sequential relationship. Be concise and professional."""

            messages = [{"role": "user", "content": prompt}]
            return f"*Context: {self._call_llm(messages)}*"
        except Exception as e:
            print(f"Error generating step context: {str(e)}")
            return ""

    def generate_documentation(
        self,
        steps: List[Step],
        screenshot_paths: Dict[int, str],
        output_format: str = "pdf",
        template: str = "default",
    ) -> str:
        """Generate documentation from detected steps."""
        # Generate descriptions for steps
        for i, step in enumerate(steps):
            if i in screenshot_paths:
                prev_screenshot = screenshot_paths.get(i - 1) if i > 0 else None
                step.description = self.generate_step_description(
                    screenshot_paths[i], prev_screenshot
                )

        # Add contextual links between steps
        steps = self._link_steps(steps)

        # Generate documentation in requested format
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if output_format.lower() == "pdf":
            return self._generate_pdf(steps, screenshot_paths, template, timestamp)
        elif output_format.lower() == "html":
            return self._generate_html(steps, screenshot_paths, template, timestamp)
        else:  # markdown
            return self._generate_markdown(steps, screenshot_paths, template, timestamp)

    def _generate_pdf(
        self,
        steps: List[Step],
        screenshot_paths: Dict[int, str],
        template: str,
        timestamp: str,
    ) -> str:
        """Generate PDF documentation."""
        output_path = f"documentation_{timestamp}.pdf"

        # Initialize PDF with custom class
        pdf = PDF()

        # Add title page
        pdf.set_font("Arial", "B", 24)
        pdf.cell(0, 60, "Process Documentation", 0, 1, "C")
        pdf.set_font("Arial", "", 14)
        pdf.cell(
            0,
            10,
            f'Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
            0,
            1,
            "C",
        )
        pdf.add_page()

        # Add table of contents
        pdf.chapter_title("Table of Contents")
        for i, _ in enumerate(steps, 1):
            pdf.cell(0, 10, f"Step {i}", 0, 1)
        pdf.add_page()

        # Add steps
        pdf.chapter_title("Process Steps")
        for i, step in enumerate(steps, 1):
            image_path = screenshot_paths.get(i - 1)
            description = (
                step.description
                if hasattr(step, "description") and step.description
                else f"Step {i}"
            )
            # description = f"Step {i}"
            pdf.add_step(i, description, image_path)

        # Save the PDF
        pdf.output(output_path)
        return output_path

    def _generate_html(
        self,
        steps: List[Step],
        screenshot_paths: Dict[int, str],
        template: str,
        timestamp: str,
    ) -> str:
        """Generate HTML documentation."""
        output_path = f"documentation_{timestamp}.html"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Process Documentation</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f5f5f5;
                }}
                .header {{
                    text-align: center;
                    padding: 20px;
                    background-color: #fff;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    margin-bottom: 30px;
                }}
                .step {{
                    background-color: #fff;
                    border-radius: 8px;
                    padding: 20px;
                    margin-bottom: 30px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .step-number {{
                    font-size: 24px;
                    color: #333;
                    margin-bottom: 15px;
                }}
                .step-description {{
                    color: #666;
                    margin-bottom: 20px;
                }}
                .step-image {{
                    max-width: 100%;
                    height: auto;
                    border-radius: 4px;
                    margin-top: 15px;
                }}
                .toc {{
                    background-color: #fff;
                    border-radius: 8px;
                    padding: 20px;
                    margin-bottom: 30px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .toc-title {{
                    font-size: 20px;
                    margin-bottom: 15px;
                }}
                .toc-item {{
                    margin: 8px 0;
                }}
                @media print {{
                    body {{
                        background-color: #fff;
                    }}
                    .step {{
                        break-inside: avoid;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Process Documentation</h1>
                <p>Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
            </div>
            
            <div class="toc">
                <div class="toc-title">Table of Contents</div>
                {"".join(f'<div class="toc-item"><a href="#step-{i}">Step {i}</a></div>' for i in range(1, len(steps) + 1))}
            </div>
        """

        for i, step in enumerate(steps, 1):
            description = (
                step.description
                if hasattr(step, "description") and step.description
                else f"Step {i}"
            )
            image_path = screenshot_paths.get(i - 1, "")

            html_content += f"""
            <div class="step" id="step-{i}">
                <div class="step-number">Step {i}</div>
                <div class="step-description">{description}</div>
                {"<img class='step-image' src='" + image_path + "' alt='Step " + str(i) + "'>" if image_path else ""}
            </div>
            """

        html_content += """
        </body>
        </html>
        """

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return output_path

    def _generate_markdown(
        self,
        steps: List[Step],
        screenshot_paths: Dict[int, str],
        template: str,
        timestamp: str,
    ) -> str:
        """Generate markdown documentation."""
        output_path = f"documentation_{timestamp}.md"

        toc_items = [f"- [Step {i}](#step-{i})" for i in range(1, len(steps) + 1)]
        toc = "\n".join(toc_items)

        content = f"""# Process Documentation
Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Table of Contents
{toc}

## Steps
"""

        for i, step in enumerate(steps, 1):
            description = (
                step.description
                if hasattr(step, "description") and step.description
                else f"Step {i}"
            )
            image_path = screenshot_paths.get(i - 1, "")

            content += f"""
### Step {i}
{description}

{"![Step " + str(i) + "](" + image_path + ")" if image_path else ""}

---
"""

        return output_path

    def generate_step_action(
        self, screenshot_path: str, prev_screenshot: str = None
    ) -> str:
        """Generate a concise description of the user action using the LLM Vision API.

        Args:
            screenshot_path (str): Path to the screenshot
            prev_screenshot (str): Path to previous screenshot for context

        Returns:
            str: Single sentence describing the user's action
        """
        try:
            # Load current screenshot
            with open(screenshot_path, "rb") as img_file:
                try:
                    current_image_data = Image.open(BytesIO(img_file.read()))
                except Exception as e:
                    print(f"Error opening image: {e}")
                    return f"Action on screen"

            # Load previous screenshot if available
            prev_image_data = None
            if prev_screenshot and Path(prev_screenshot).exists():
                with open(prev_screenshot, "rb") as img_file:
                    try:
                        prev_image_data = Image.open(BytesIO(img_file.read()))
                    except Exception as e:
                        print(f"Error opening image: {e}")

            # Create prompt for action
            if prev_image_data:
                prompt = """Analyze these two consecutive screenshots from a process recording.
Identify the user action that caused the transition from the previous screen (start state) to the current screen (end state).
What button did they click, what did they type, or what menu did they open?
Respond with a single, clear, action-oriented sentence describing this action (e.g. 'Clicked the **Submit** button' or 'Typed "my_password" into the password field and pressed **Enter**').

CRITICAL: Do NOT mention or reference 'Scrib', 'Scribe', or 'Peely' tools/applications in any way. These are only the recording tools. Document only the actions taken inside the target application.
Only return the sentence, nothing else."""
            else:
                prompt = """Analyze this screenshot from a process recording.
Identify what action the user is performing or has just completed on this screen.
Respond with a single, clear, action-oriented sentence describing the state/action (e.g. 'Opened the dashboard page' or 'Navigated to the settings configuration tab').

CRITICAL: Do NOT mention or reference 'Scrib', 'Scribe', or 'Peely' tools/applications in any way. These are only the recording tools. Document only the actions taken inside the target application.
Only return the sentence, nothing else."""

            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]

            # Add images in base64
            if prev_image_data:
                prev_base64 = self._image_to_base64(prev_image_data)
                messages[0]["content"].append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{prev_base64}"},
                    }
                )

            current_base64 = self._image_to_base64(current_image_data)
            messages[0]["content"].append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{current_base64}"},
                }
            )

            description = self._call_llm(messages)

            # Clean up the output to be a clean single sentence
            description = description.replace("\n", " ").strip()

            time.sleep(self.request_delay)  # Rate limiting
            return description

        except Exception as e:
            print(f"Error extracting step action: {str(e)}")
            raise Exception(f"LLM API Error: Failed to extract step action. {str(e)}")

    def generate_howto_guide(
        self, step_actions: List[str], screenshot_paths: Dict[int, str]
    ) -> str:
        """Generate a cohesive 'How-To' guide based on the list of actions and screenshots.

        Args:
            step_actions (List[str]): List of action descriptions for each step
            screenshot_paths (Dict[int, str]): Dict mapping step index to screenshot path

        Returns:
            str: Generated markdown documentation
        """
        steps_text = ""
        for i, action in enumerate(step_actions, 1):
            img_path = screenshot_paths.get(i - 1, "")
            # Return relative path for frontend rendering
            img_url = f"/output/screenshots/{Path(img_path).name}" if img_path else ""
            steps_text += f"Step {i}: {action}\nImage: {img_url}\n\n"

        prompt = f"""You are an expert technical writer and developer documentation designer.
Write a clear, concise, and professional "How-To" guide in markdown format explaining how to accomplish the task demonstrated in the user's video recording.

Based on the following sequence of actions and screenshots detected from the recording:

{steps_text}

Generate a single cohesive markdown document.
The document must contain:
1. A clear Title starting with "# How to [Goal]" that describes the overarching objective.
2. A brief Introduction (1-2 sentences) explaining the goal.
3. A "Prerequisites" section (e.g. required software, access, or starting state).
4. A numbered, action-oriented list of steps. Each step must be clear and direct (e.g. "Click **Save** in the top right").
5. Emphasize UI elements (buttons, inputs, pages) in **bold**.
6. Embed the screenshots in-line within the steps using markdown syntax: `![Step X Description](IMAGE_URL)`. Use the exact Image URL provided for each step. Do not invent other paths.
7. A final "Tips" or "Key Takeaways" section.

CRITICAL: Do NOT mention or reference 'Scrib', 'Scribe', or 'Peely' tools/applications in any way. These are only the recording tools. Focus solely on documenting the target application workflow shown in the step descriptions.
Ensure the markdown document is compact, elegant, and action-oriented. Do not include meta-text or preambles (like "Here is your guide:"). Start directly with the title."""

        messages = [{"role": "user", "content": prompt}]

        try:
            guide = self._call_llm(messages)
            return guide
        except Exception as e:
            print(f"Error generating how-to guide: {e}")
            raise Exception(f"LLM API Error: Failed to generate how-to guide. {str(e)}")
