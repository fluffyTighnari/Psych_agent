# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# llm.py
p = r"C:\Users\lilex\Desktop\Code\phy\psych_agent\core\llm.py"
s = open(p, encoding="utf-8").read()
s2 = s.replace("import ollama\nfrom openai import OpenAI", "import os\nimport ollama\nfrom openai import OpenAI", 1)
assert s2 != s, "llm import os patch failed"
s = s2
old = "            self._client = ollama.Client(timeout=timeout)"
new = "            # 地址可配置（Docker 内指向 ollama 服务名），默认本机 Ollama，行为不变\n            host = os.environ.get(\"OLLAMA_HOST\", \"http://127.0.0.1:11434\")\n            self._client = ollama.Client(host=host, timeout=timeout)"
assert old in s, "llm client patch anchor missing"
s = s.replace(old, new, 1)
open(p, "w", encoding="utf-8", newline="").write(s)
print("llm.py patched")

# ollama_client.py
p2 = r"C:\Users\lilex\Desktop\Code\phy\psych_agent\core\ollama_client.py"
s = open(p2, encoding="utf-8").read()
s2 = s.replace("import requests\nfrom typing import List, Dict, Optional\nfrom config.model_config import OLLAMA_GLOBAL",
               "import os\nimport requests\nfrom typing import List, Dict, Optional\nfrom config.model_config import OLLAMA_GLOBAL", 1)
assert s2 != s, "ollama_client import os patch failed"
s = s2
old = "        self.base_url = OLLAMA_GLOBAL.rstrip(\"/\")"
new = "        # 地址可配置（Docker 内指向 ollama 服务名），默认本机 Ollama，行为不变\n        self.base_url = os.environ.get(\"OLLAMA_HOST\", OLLAMA_GLOBAL).rstrip(\"/\")"
assert old in s, "ollama_client base_url patch anchor missing"
s = s.replace(old, new, 1)
open(p2, "w", encoding="utf-8", newline="").write(s)
print("ollama_client.py patched")