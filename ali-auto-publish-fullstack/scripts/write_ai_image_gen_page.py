# -*- coding: utf-8 -*-
"""Generate AiImageGen.tsx with UTF-8."""
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "frontend" / "client" / "src" / "pages" / "AiImageGen.tsx"

# Read template from sibling file content built in Python
CONTENT = open(Path(__file__).with_name("_AiImageGen.tsx.template"), "r", encoding="utf-8").read()
TARGET.write_text(CONTENT, encoding="utf-8")
assert "图片管理" in TARGET.read_text(encoding="utf-8")
print("ok", TARGET)
