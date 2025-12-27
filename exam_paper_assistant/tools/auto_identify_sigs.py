
import asyncio
import difflib
import json
import os
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv(ROOT_DIR / ".env")

from utils.svg_to_latex import load_signatures, svg_content_to_latex

FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY")
FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"
MODEL_NAME = "accounts/fireworks/models/qwen3-vl-235b-a22b-instruct"

# Helper to normalize latex for comparison
def normalize_latex(s):
    if not s: return ""
    # Remove spaces, braces, formatting
    s = s.replace(" ", "")
    s = s.replace("{ ", "").replace("}", "")
    s = s.replace("\mathrm", "")
    s = s.replace("\text", "")
    s = s.replace("\left", "").replace("\right", "")
    return s

async def recognize_formula(client, image_url):
    headers = {
        "Authorization": f"Bearer {FIREWORKS_API_KEY}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Transcribe this mathematical formula into LaTeX. Output ONLY the LaTeX code. e.g. x^2+y^2=1"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url
                        }
                    }
                ]
            }
        ],
        "max_tokens": 256,
        "temperature": 0.0,
    }
    
    try:
        resp = await client.post(
            f"{FIREWORKS_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30.0
        )
        if resp.status_code != 200:
            print(f"API Error: {resp.status_code}")
            return None
        
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        
        if "```" in content:
            match = re.search(r'```(?:latex)?\s*(.*?)\s*```', content, re.DOTALL)
            if match:
                content = match.group(1).strip()
                
        content = content.strip('$').strip()
        return content
    except Exception as e:
        print(f"Exception: {e}")
        return None

async def main():
    if not FIREWORKS_API_KEY:
        print("Error: FIREWORKS_API_KEY not found.")
        return

    # Load unknown signatures
    unknown_path = ROOT_DIR / "utils" / "unknown_signatures.json"
    if not unknown_path.exists():
        print(f"unknown_signatures.json not found at {unknown_path}")
        return
        
    with open(unknown_path, 'r') as f:
        data = json.load(f)
        signatures = data.get('signatures', {})
        
    # Reload known signatures
    known = load_signatures()
    
    # Filter target signatures (unknown ones)
    target_sigs = []
    for sig, info in signatures.items():
        if sig not in known:
            target_sigs.append((sig, info))
            
    # Sort by count
    target_sigs.sort(key=lambda x: x[1]['count'], reverse=True)
    
    # Process Top N
    TOP_N = 30
    batch = target_sigs[:TOP_N]
    
    print(f"Analyzing top {len(batch)} unknown signatures...")
    
    inferred_mappings = {}
    
    async with httpx.AsyncClient() as client:
        for sig, info in batch:
            print(f"\n[{info['count']}] Analyzing {sig}...")
            
            # Try a few sources until we get a good read
            sources = info['sources'][:3]
            if not sources: continue
            
            # We prefer shorter formulas usually, but we don't know length yet.
            # Just take the first valid one.
            
            url = sources[0]
            png_url = url.replace(".svg", ".png")
            
            # 1. Get SVG and Placeholder
            try:
                resp = await client.get(url)
                if resp.status_code != 200: continue
                svg_content = resp.text
            except:
                continue
                
            placeholder_latex, _ = svg_content_to_latex(svg_content)
            
            # 2. Get Vision Result
            vision_latex = await recognize_formula(client, png_url)
            if not vision_latex: continue
            
            print(f"  Placeholder: {placeholder_latex}")
            print(f"  Vision:      {vision_latex}")
            
            # 3. Inference Logic
            # Normalize strings
            norm_ph = normalize_latex(placeholder_latex)
            norm_vis = normalize_latex(vision_latex)
            
            # The placeholder contains `[?sig]`.
            # We want to find what substring in `vision` corresponds to `[?sig]`.
            
            # Simple case: Only one unknown signature in the whole formula
            # Count occurrences of `[?`
            unknown_count = placeholder_latex.count("[?")
            
            if unknown_count == 1:
                # We can try to align the strings
                # Split placeholder by the unknown tag
                parts = placeholder_latex.split(f"[?{sig}]")
                if len(parts) == 2:
                    prefix = normalize_latex(parts[0])
                    suffix = normalize_latex(parts[1])
                    
                    # Check if vision starts with prefix and ends with suffix (roughly)
                    # This is tricky because normalization removes chars.
                    # Let's try to match characters.
                    
                    # Remove prefix from start of norm_vis
                    # Allow some fuzziness?
                    
                    # Heuristic: Remove the common prefix and suffix
                    # This is naive but might work for simple cases
                    
                    # Using difflib to find the difference
                    s = difflib.SequenceMatcher(None, norm_ph.replace(f"[?{sig}]", ""), norm_vis)
                    # This doesn't quite work because the placeholder has a gap.
                    
                    # Alternative: Regex replacement
                    # Construct a regex from placeholder: escape it, replace `\`[`?sig`]` with `(.+)`
                    # Need to handle the normalization though.
                    
                    # Let's try manual visual inspection for now via output, 
                    # OR simple single-char guess.
                    
                    # If vision length is close to placeholder length (minus tag plus 1 char)
                    # And difflib ratio is high when we replace tag with 'x'
                    
                    candidates = []
                    # Try common single chars
                    test_chars = ["a", "b", "c", "x", "y", "z", "0", "1", "2", "3", "+", "-", "=", "(", ")", "\\pi", "\\theta", "\\alpha", "\\beta"]
                    
                    best_char = None
                    best_ratio = 0
                    
                    for char in test_chars:
                        guess = placeholder_latex.replace(f"[?{sig}]", char)
                        guess_norm = normalize_latex(guess)
                        ratio = difflib.SequenceMatcher(None, guess_norm, norm_vis).ratio()
                        if ratio > best_ratio:
                            best_ratio = ratio
                            best_char = char
                    
                    if best_ratio > 0.9:
                        print(f"  >>> MATCH: {sig} -> {best_char} (Confidence: {best_ratio:.2f})")
                        inferred_mappings[sig] = best_char
                    else:
                        print(f"  >>> No confident match. Best guess: {best_char} ({best_ratio:.2f})")
            else:
                print("  [Skipping auto-match: multiple unknowns]")

            # Rate limit
            await asyncio.sleep(1.0)

    # Output results
    if inferred_mappings:
        print("\n" + "="*40)
        print("Inferred Mappings to Add:")
        for sig, char in inferred_mappings.items():
            print(f'"{sig}": "{char}",')
            
        # Save to file?
        # We can append to a log or directly update if confident.
        # Let's just print for now.

if __name__ == "__main__":
    asyncio.run(main())
