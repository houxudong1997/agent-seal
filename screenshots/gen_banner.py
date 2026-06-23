import requests, json, time, base64, io, os
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

COMFY = 'http://127.0.0.1:8188'
OUTPUT = 'F:/workstation/projects/agent-audit/screenshots/banner.png'

# ── Step 1: Generate background with ComfyUI SD1.5 + hires fix ──
# Using majicmixRealistic_v7 which is lighter (SD1.5 ~2GB) and faster

# Base generation at 704x352 (2:1 ratio for banner crop)
# Then hires fix upscale to ~1408x704, then resize to 1200x630

workflow = {
    # Base model
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {
            "ckpt_name": "majicmixRealistic_v7.safetensors"
        }
    },
    # Empty latent - 704x384 (close to 1.9:1 banner ratio)
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": 704,
            "height": 384,
            "batch_size": 1
        }
    },
    # Positive prompt
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": """sleek dark technology dashboard background, deep charcoal black backdrop,
abstract glowing amber data lines, futuristic interface elements,
holographic grid, subtle fiber optic light trails, minimal tech aesthetic,
premium corporate style, volumetric fog, dark moody atmosphere,
cinematic lighting, 8k sharp details""",
            "clip": ["4", 1]
        }
    },
    # Negative prompt
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": """light background, white background, bright, colorful, cartoon, anime,
people, text, letters, words, watermark, signature, face, person,
blurry, low quality, ugly, distorted, low resolution, grainy,
oversaturated, chaotic, busy, messy, photograph""",
            "clip": ["4", 1]
        }
    },
    # Base KSampler (euler to avoid tqdm issues)
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 420108,
            "steps": 30,
            "cfg": 7.5,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0]
        }
    },
    # VAE Decode
    "8": {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": ["3", 0],
            "vae": ["4", 2]
        }
    },
    # Save Image
    "9": {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": "banner_bg",
            "images": ["8", 0]
        }
    }
}

print("🎨 Step 1: Generating banner background with ComfyUI SD1.5...")
resp = requests.post(f'{COMFY}/prompt', json={"prompt": workflow})
data = resp.json()
print(f"  Prompt submitted: {data}")

prompt_id = data['prompt_id']

# Poll for completion
attempts = 0
while attempts < 60:
    status = requests.get(f'{COMFY}/history/{prompt_id}').json()
    if prompt_id in status:
        result = status[prompt_id]
        if 'status' in result:
            print(f"  Status: {result['status']}")
        break
    attempts += 1
    time.sleep(3)
    print(f"  Waiting... ({attempts*3}s)", end='\r')

print(f"\n  Result: {json.dumps(result.get('outputs', {}), indent=2)[:500]}")

# Fetch generated image
outputs = result.get('outputs', {})
images_data = []
for node_id, node_out in outputs.items():
    if isinstance(node_out, dict) and 'images' in node_out:
        images_data.extend(node_out['images'])

if not images_data:
    # Check for errors
    print(f"  Full result: {json.dumps(result, indent=2)[:1000]}")
    if 'error' in result.get('status', {}):
        print(f"  ❌ Generation error: {result['status']['error']}")
    print("  ❌ No images generated!")
    exit(1)

img_info = images_data[0]
print(f"  Found image: {img_info}")

# Fetch via /view API
img_resp = requests.get(f'{COMFY}/view', params={
    'filename': img_info['filename'],
    'subfolder': img_info.get('subfolder', ''),
    'type': img_info.get('type', 'output')
})
img_resp.raise_for_status()

bg_img = Image.open(io.BytesIO(img_resp.content)).convert('RGBA')
print(f"  Loaded generated image: {bg_img.size}")

# ── Step 2: Resize and compose ──
print("\n🎨 Step 2: Composing final banner with text overlay...")

# Resize to 1200x630 (cover/crop to fit)
bg_img = bg_img.resize((1200, 630), Image.LANCZOS)

# Darken slightly for better text readability
bg_img = ImageEnhance.Brightness(bg_img).enhance(0.6)

draw = ImageDraw.Draw(bg_img)

# Try to find a good font
font_paths = [
    'C:/Windows/Fonts/arialbd.ttf',      # Arial Bold
    'C:/Windows/Fonts/arial.ttf',         # Arial
    'C:/Windows/Fonts/segoeui.ttf',       # Segoe UI
    'C:/Windows/Fonts/consola.ttf',       # Consolas
    'C:/Windows/Fonts/cour.ttf',          # Courier New
]

title_font = None
subtitle_font = None
tag_font = None

for path in font_paths:
    if os.path.exists(path):
        try:
            title_font = ImageFont.truetype(path, 64)
            subtitle_font = ImageFont.truetype(path, 26)
            tag_font = ImageFont.truetype(path, 16)
            print(f"  Using font: {path}")
            break
        except:
            continue

if not title_font:
    print("  No TrueType font found, using default")
    title_font = ImageFont.load_default()
    subtitle_font = subtitle_font or title_font
    tag_font = tag_font or title_font

# Draw accent line at top
accent_color = (245, 158, 11, 230)  # #F59E0B amber
draw.rectangle([(80, 0), (350, 4)], fill=accent_color)

# Draw title - centered
title_text = "agent-audit"
bbox = draw.textbbox((0, 0), title_text, font=title_font)
tw = bbox[2] - bbox[0]
th = bbox[3] - bbox[1]
tx = (1200 - tw) // 2
ty = 160
draw.text((tx, ty), title_text, font=title_font, fill=(255, 255, 255, 250))

# Draw subtitle
sub_text = "Zero-Code Audit Trail for AI Agents"
bbox2 = draw.textbbox((0, 0), sub_text, font=subtitle_font)
sw = bbox2[2] - bbox2[0]
sh = bbox2[3] - bbox2[1]
sx = (1200 - sw) // 2
sy = ty + th + 18
draw.text((sx, sy), sub_text, font=subtitle_font, fill=(200, 200, 200, 220))

# Draw subtle separator line below subtitle
sep_y = sy + sh + 20
draw.rectangle([(450, sep_y), (750, sep_y + 2)], fill=(245, 158, 11, 160))

# Draw tag label at bottom
tag_text = "LLM Agent Monitoring · Session Replay · Chain Verification"
bbox3 = draw.textbbox((0, 0), tag_text, font=tag_font)
tag_w = bbox3[2] - bbox3[0]
tag_x = (1200 - tag_w) // 2
tag_y = 630 - 55
draw.text((tag_x, tag_y), tag_text, font=tag_font, fill=(160, 160, 160, 180))

# Convert to RGB for final save
final = bg_img.convert('RGB')
final.save(OUTPUT, 'PNG')
print(f"\n✅ Banner saved to: {OUTPUT}")
print(f"   Dimensions: {final.size}")
