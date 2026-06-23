#!/usr/bin/env python3
"""Fix missing closing quotes in curl commands in api-v1.md"""

doc_path = r'F:\workstation\projects\agent-seal\docs\api-v1.md'

with open(doc_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

fixes = {
    # Line 259: -H "Authorization: Bearer *** \  → add closing "
    258: ('Bearer *** \\', 'Bearer ***" \\'),
    # Line 837: same pattern
    836: ('Bearer *** \\', 'Bearer ***" \\'),
    # Line 907: same pattern
    906: ('Bearer *** \\', 'Bearer ***" \\'),
}

for idx, (old, new) in fixes.items():
    lines[idx] = lines[idx].replace(old, new)

with open(doc_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

# Verify
print("Verification:")
for ln in [85, 259, 837, 907, 264]:
    print(f"  Line {ln}: {lines[ln-1].rstrip()}")
