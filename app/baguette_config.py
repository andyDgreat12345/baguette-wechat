"""Shared public-install identity settings; no personal account is compiled in."""
import json
import os
from pathlib import Path
BASE = Path(__file__).resolve().parents[1]
DEFAULTS = {'bot_id': 'baguette', 'owner_id': 'owner', 'owner_chat': 'Owner', 'group_chats': ['Example group'], 'vm_name': 'baguette', 'tart_binary': 'tart', 'proxy': 'direct', 'deepseek_model': 'deepseek-flash', 'vision_model': 'qwen3.5:9b', 'vision_base_url': 'http://127.0.0.1:11434/v1', 'embedding_base_url': 'http://127.0.0.1:11434', 'embedding_model': 'bge-m3'}
def load_config():
    path=Path(os.environ.get('BAGUETTE_CONFIG',str(BASE/'runtime/installation.json')))
    value=dict(DEFAULTS)
    if path.exists():value.update(json.loads(path.read_text()))
    return value
