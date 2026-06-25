# -*- coding: utf-8 -*-
from pathlib import Path
content = open(r"scripts\_interaction_probe_body.txt", encoding="utf-8").read()
Path(r"app\services\page_scanner\interaction_probe.py").write_text(content, encoding="utf-8", newline="\n")
print("written", len(content))
