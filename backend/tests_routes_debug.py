import os, sys, tempfile
TMP = tempfile.mkdtemp(prefix="fu-rd-")
os.environ.update({
    "FLOWER_MOCK": "true",
    "FLOWER_RUNTIME_CONFIG_FILE": TMP + "/rt.env",
    "FLOWER_AUDIT_FILE": TMP + "/audit.jsonl",
    "FLOWER_RESTART_STATE_FILE": TMP + "/restart.json",
    "FLOWER_DB_PATH": TMP + "/flowerui.db",
    "FLOWER_DEBUG": "false",
})
sys.path.insert(0, ".")
from app.main import app
for rt in app.routes:
    print(type(rt).__name__, getattr(rt, "path", None), getattr(rt, "methods", None))
print("count:", len(app.routes))
