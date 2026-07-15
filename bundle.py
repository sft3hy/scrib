import os
import json
import base64
from pathlib import Path

def is_binary(file_path):
    # Try reading as UTF-8
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            f.read(1024)
        return False
    except UnicodeDecodeError:
        return True

def bundle():
    workspace = Path(".")
    output_dir = workspace / "bundle"
    output_dir.mkdir(exist_ok=True)
    
    ignore_dirs = {'.git', '.venv', 'venv', 'env', '__pycache__', 'output', 'bundle', 'node_modules', 'dist'}
    ignore_files = {'bundle.py', 'unbundle.py', '.DS_Store', '.env'}
    
    all_files = []
    
    for root, dirs, files in os.walk(workspace):
        # Exclude ignored directories in-place
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        for f in files:
            if f in ignore_files:
                continue
            
            file_path = Path(root) / f
            all_files.append(file_path)
            
    print(f"Found {len(all_files)} files to bundle.")
    
    # 50 MB limits (which ensures a batch of 10 files is at most 500MB, safely under the 512MB limit)
    MAX_TEXT_FILE_SIZE = 50 * 1024 * 1024
    
    current_batch_num = 1
    current_file_num = 1
    current_list = []
    current_size = 2 # empty json array '[]' is 2 bytes
    
    for file_path in all_files:
        rel_path = str(file_path.relative_to(workspace))
        binary = is_binary(file_path)
        
        try:
            if binary:
                with open(file_path, 'rb') as f:
                    content_bytes = f.read()
                content_str = base64.b64encode(content_bytes).decode('utf-8')
                encoding = "base64"
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content_str = f.read()
                encoding = "text"
        except Exception as e:
            print(f"Skipping {rel_path} due to read error: {e}")
            continue
            
        file_entry = {
            "path": rel_path,
            "encoding": encoding,
            "content": content_str
        }
        
        entry_size = len(json.dumps(file_entry)) + 2 # plus comma and formatting
        
        # If adding this entry exceeds 50MB, start a new file
        if current_size + entry_size > MAX_TEXT_FILE_SIZE and len(current_list) > 0:
            out_file = output_dir / f"batch_{current_batch_num}_file_{current_file_num}.txt"
            with open(out_file, 'w', encoding='utf-8') as f:
                json.dump(current_list, f, indent=2)
            print(f"Wrote {out_file} (Size: {out_file.stat().st_size / 1024 / 1024:.2f} MB)")
            
            # Reset and increment file numbers
            current_list = []
            current_size = 2
            current_file_num += 1
            if current_file_num > 10:
                current_file_num = 1
                current_batch_num += 1
                
        current_list.append(file_entry)
        current_size += entry_size
        
    # Write any remaining entries
    if current_list:
        out_file = output_dir / f"batch_{current_batch_num}_file_{current_file_num}.txt"
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(current_list, f, indent=2)
        print(f"Wrote {out_file} (Size: {out_file.stat().st_size / 1024 / 1024:.2f} MB)")
        
    print("Bundling completed successfully!")

if __name__ == "__main__":
    bundle()
