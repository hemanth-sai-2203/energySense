import re

with open(r'C:\Users\heman\.gemini\antigravity-ide\brain\038d5223-2a2b-42c0-90c5-1ea2c8fb8823\.system_generated\steps\16\content.md', 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

# find zenodo file download links
links = re.findall(r'href="([^"]*files/[^"]*)"', text)
if not links:
    links = re.findall(r'https://zenodo.org/records/14983362/files/[^\s\)\"\']+', text)

for l in sorted(set(links)):
    print(l)
