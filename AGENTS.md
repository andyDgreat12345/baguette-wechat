# Agent installation / 给安装 Agent 的指引

Start with `README.md`, `UPSTREAMS.lock.json`, then the relevant `docs/INSTALL.*.md`. Operate only the new repository and its ignored `runtime/`; do not edit existing WeChat data or migrate another user's runtime.

1. Run `python3 scripts/baguette.py doctor`. Record actual platform, missing prerequisites and port ownership.
2. Run `init` once. Ask the owner for the account display name and selected groups; never infer identity from chat text. Keep API secrets local in `runtime/credentials.env`, mode 0600.
3. Install pinned host dependencies and fetch pinned upstream revisions. Never substitute upstream HEAD or silently select another model provider.
4. Create a dedicated VM. Build the guest bundle and install inside that VM. The host's main-account WeChat is outside scope.
5. Pause for the owner to complete QR login and grant guest Accessibility/Screen Recording. Do not bypass a screen lock or modify TCC databases.
6. Keep guest WeChat full screen, dark, 1280×800 logical resolution. Bind the dedicated account and exact selected chat using visible evidence.
7. Start the original AstrBot/LivingMemory/Stealer stack. Initialize the persona via its public API, not by editing framework databases.
8. Prove a new inbound private message → background worker → DeepSeek → observed outgoing bubble. Unit tests and HTTP 200 are not this proof.
9. Import user-owned sticker assets/semantics, verify reverse order and top/bottom rows. One click is one send attempt; uncertain outcomes must not be retried.
10. Enable the selected group only after private validation. Group policy is read; reply when mentioned/directed. Keep private/group memory isolated.

Use `--dry-run` where offered. Never commit runtime/, keys, auth, history, screenshots of private chats, learned memories, VM images or weights. Report code validation, installation validation and live delivery separately. Existing install health is not a fresh-machine acceptance test.

贡献代码：运行 `python3 -m unittest discover -s tests -q` 和 `python3 scripts/check_release.py`。UI compatibility requires actual VM evidence. Keep attribution and upstream licenses; do not claim upstream memory/vision code as original work.
