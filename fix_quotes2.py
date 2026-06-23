#!/usr/bin/env python3
"""Fix missing closing quotes - use whole-file string replacement"""
import pathlib

doc_path = pathlib.Path(r'F:\workstation\projects\agent-seal\docs\api-v1.md')
content = doc_path.read_text(encoding='utf-8')

# Check exactly what we're dealing with
idx85 = content.find('Bearer *** http')
idx259 = content.find('Bearer *** \\\n')
print(f"Line 85 pattern at offset {idx85}: {content[idx85:idx85+25]!r}")
print(f"Line 259 pattern at offset {idx259}: {content[idx259:idx259+25]!r}")

# Apply replacements
count = 0
# Line 85: curl -H "Authorization: Bearer *** http → ***" http
new = content.replace('Bearer *** http', 'Bearer ***" http', 1)
if new != content:
    count += 1
    content = new
    print("Fixed line 85")

# Line 259: first Bearer *** \ before -d
new = content.replace('Bearer *** \\\n  -d', 'Bearer ***" \\\n  -d', 1)
if new != content:
    count += 1
    content = new
    print("Fixed line 259")

# Line 837 (compliance): second Bearer *** \ before -d  
new = content.replace('Bearer *** \\\n  -d', 'Bearer ***" \\\n  -d', 1)
if new != content:
    count += 1
    content = new
    print("Fixed line 837")

# Line 907 (evidence): third Bearer *** \ before -d
new = content.replace('Bearer *** \\\n  -d', 'Bearer ***" \\\n  -d', 1)
if new != content:
    count += 1
    content = new
    print("Fixed line 907")

print(f"\nTotal fixes applied: {count}")
doc_path.write_text(content, encoding='utf-8')
