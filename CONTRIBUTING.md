# 贡献 / Contributing

Please open a focused issue before a large change. Include OS/WeChat/Tart versions, logical resolution, a minimal redacted reproduction and whether the problem is OCR, routing, memory or delivery. Never attach keys, runtime archives or real chat databases.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python scripts/check_release.py
```

Native UI tests require macOS; portable logic tests run in CI with platform-specific skips. Do not write tests that merely repeat a literal implementation. Verify a behavior and its failure boundary. Preserve upstream commits/licenses. Keep Chinese and English installation instructions consistent. Add actual validation evidence and disclose what was not run.

Submit changes in a branch and pull request. Small fixes, reviewed slang semantics, accessibility improvements and fresh-install reports are welcome. Copyrighted sticker packs should not be added without rights and provenance.
