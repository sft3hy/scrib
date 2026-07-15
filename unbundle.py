import os
import json
import base64
from pathlib import Path

def unbundle():
    workspace = Path(".")
    bundle_dir = workspace / "bundle"
    
    if not bundle_dir.exists() or not bundle_dir.is_dir():
        print("Error: 'bundle' directory not found!")
        return
        
    bundle_files = sorted(list(bundle_dir.glob("batch_*_file_*.txt")))
    
    if not bundle_files:
        print("Error: No bundle files found under 'bundle/' directory.")
        return
        
    print(f"Found {len(bundle_files)} bundle files to process.")
    
    for bf in bundle_files:
        print(f"Processing {bf.name}...")
        try:
            with open(bf, 'r', encoding='utf-8') as f:
                entries = json.load(f)
        except Exception as e:
            print(f"Error reading {bf.name}: {e}")
            continue
            
        for entry in entries:
            rel_path = entry["path"]
            encoding = entry["encoding"]
            content = entry["content"]
            
            target_path = workspace / rel_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            try:
                if encoding == "base64":
                    content_bytes = base64.b64decode(content)
                    with open(target_path, 'wb') as f:
                        f.write(content_bytes)
                else:
                    with open(target_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                print(f"  Recreated {rel_path}")
            except Exception as e:
                print(f"  Error writing {rel_path}: {e}")
                
    # Copy .env.example to .env if it does not exist
    env_file = workspace / ".env"
    env_example = workspace / ".env.example"
    if not env_file.exists() and env_example.exists():
        import shutil
        shutil.copy(env_example, env_file)
        print("Created default .env from .env.example")
        
    print("Unbundling completed successfully!")

if __name__ == "__main__":
    unbundle()
