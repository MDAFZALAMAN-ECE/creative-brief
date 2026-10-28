import os
import tempfile
from pathlib import Path

# Isolated config for tests; must run before `app` is imported.
_tmp = tempfile.mkdtemp(prefix="cb-test-")
os.environ["DB_PATH"] = str(Path(_tmp) / "test.db")
os.environ["SECRET_KEY"] = "test-secret-key-0123456789abcdef"
os.environ["EXTERNAL_AI_ENABLED"] = "false"
os.environ["SEMANTIC_SEARCH"] = "false"
