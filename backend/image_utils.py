import base64
import io
import os
from PIL import Image, ImageDraw, ImageFont

def draw_grounding_marks(base64_str, elements_meta, debug_save=True):
    """
    Draws bounding boxes and IDs on the screenshot based on elements_meta.
    Returns: Base64 string of the marked image.
    """
    if not base64_str or not elements_meta:
        return None

    try:
        # 1. Decode Base64
        # Remove header if present (e.g., "data:image/jpeg;base64,")
        if ',' in base64_str:
            base64_str = base64_str.split(',')[1]
        
        image_data = base64.b64decode(base64_str)
        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        draw = ImageDraw.Draw(image)

        # 2. Setup Font (Fallback to default if arial not found)
        try:
            # Try to load a readable font (Size 20 for visibility)
            font = ImageFont.truetype("arial.ttf", 20)
        except IOError:
            # Fallback for Linux/Docker environments without fonts
            font = ImageFont.load_default()

        # 3. Draw Marks (SoM - Set of Marks)
        for meta in elements_meta:
            agent_id = str(meta.get('id', '?'))
            x = meta.get('x', 0)
            y = meta.get('y', 0)
            w = meta.get('w', 0)
            h = meta.get('h', 0)

            # A. Draw Bounding Box (Red, 2px width)
            draw.rectangle([x, y, x + w, y + h], outline="red", width=2)

            # B. Draw Label Background (Red tag at top-left)
            # Calculate text size to fit the red background tag
            bbox = draw.textbbox((x, y), agent_id, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            
            # Draw tag background
            draw.rectangle([x, y - text_h - 4, x + text_w + 8, y], fill="red")
            
            # C. Draw Text (White)
            draw.text((x + 4, y - text_h - 4), agent_id, fill="white", font=font)

        # 4. (Debug) Save locally to verify alignment
        if debug_save:
            if not os.path.exists("debug_screenshots"):
                os.makedirs("debug_screenshots")
            image.save("debug_screenshots/latest_grounding.jpg", "JPEG")
            print(f"📸 Debug: Saved marked screenshot to 'debug_screenshots/latest_grounding.jpg'")

        # 5. Encode back to Base64 (for VLM input)
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG")
        return base64.b64encode(buffered.getvalue()).decode('utf-8')

    except Exception as e:
        print(f"❌ Image Processing Error: {e}")
        return None