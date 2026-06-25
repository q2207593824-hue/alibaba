# -*- coding: utf-8 -*-
from pathlib import Path

src = Path(r"D:\桌面\工厂图片调用API\main-批量生成.py")
dst = Path(__file__).resolve().parent.parent / "backend" / "app" / "services" / "ai_image_batch_engine.py"

text = src.read_text(encoding="utf-8")
text = text.replace(
    '"API_KEY": "sk-pQYeiHLptXRPFiEh1qdGSQ4ACHVaJnzFhhDOnvHhA9SQhQ9R"',
    '"API_KEY": ""',
)
text = text.replace(
    '"API_KEY": "ark-d496170d-b35a-467f-b273-7c6f03be8cbe-40598"',
    '"API_KEY": ""',
)
text = text.replace(
    "parent, name = os.path.split(parent), os.path.basename(output_path)",
    "parent, name = os.path.split(output_path)",
)

hook = """
_external_log_fn = None

def set_external_log_fn(fn):
    global _external_log_fn
    _external_log_fn = fn

"""
text = text.replace("_log_lock = threading.Lock()\n", "_log_lock = threading.Lock()\n" + hook)
text = text.replace(
    "def log(msg):\n    with _log_lock:\n        print(msg, flush=True)\n",
    "def log(msg):\n    with _log_lock:\n        if _external_log_fn:\n            _external_log_fn(str(msg))\n        else:\n            print(msg, flush=True)\n",
)

old_ep = '''def _load_ep_from_file():
    """从项目目录 doubao_ep.txt 读取 ep- 接入点（一行，推荐）"""
    ep_file = CONFIG.get("DOUBAO", {}).get("EP_FILE", "doubao_ep.txt")
    for base in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):'''

new_ep = '''def _load_ep_from_file():
    """从项目目录 doubao_ep.txt 读取 ep- 接入点（一行，推荐）"""
    ep_abs = CONFIG.get("DOUBAO", {}).get("_EP_FILE_ABSPATH")
    if ep_abs and os.path.isfile(ep_abs):
        with open(ep_abs, "r", encoding="utf-8") as f:
            line = f.read().strip().splitlines()[0].strip()
            if line.startswith("ep-"):
                return line
    ep_file = CONFIG.get("DOUBAO", {}).get("EP_FILE", "doubao_ep.txt")
    for base in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):'''

text = text.replace(old_ep, new_ep)

header = (
    '# -*- coding: utf-8 -*-\n'
    '"""AI 批量生图引擎 — 由原 main-批量生成.py 完整内嵌，勿删减业务逻辑。"""\n'
)
if not text.startswith("# -*- coding"):
    text = header + text

dst.write_text(text, encoding="utf-8")
print("written", dst, "lines", len(text.splitlines()))
