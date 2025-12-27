
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SIG_PATH = ROOT_DIR / "utils" / "glyph_signatures.json"

def main():
    with SIG_PATH.open("r", encoding="utf-8") as f:
        sigs = json.load(f)
    
    new_mappings = {
        "2216d29f": "\\beta",
        "8562dff4": "N",
        "21215970": "C",
        "01233559": "H",
        "df773aee": "O",
        "3a1cba35": "R",
        "2e1af619": "B",
        "b529f241": "L",
        "67d5f730": "m",
    }
    
    count = 0
    for sig, char in new_mappings.items():
        if sig not in sigs:
            sigs[sig] = char
            print(f"Added: {sig} -> {char}")
            count += 1
        elif sigs[sig] != char:
            print(f"Updating: {sig} -> {char} (was {sigs[sig]})")
            sigs[sig] = char
            count += 1
            
    if count > 0:
        with SIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(sigs, f, ensure_ascii=False, indent=2)
        print(f"Saved {count} signatures.")

if __name__ == "__main__":
    main()
