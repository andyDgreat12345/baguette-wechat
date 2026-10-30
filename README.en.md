# Baguette 🥖 — Big Fat Fish for WeChat

[简体中文](README.md) · [Installation](docs/INSTALL.en.md) · [Agent guide](AGENTS.md)

A visual companion for an ordinary WeChat account inside an isolated macOS VM. It reads visible chat screenshots, replies through DeepSeek, and operates WeChat's actual UI, including scrolling Favorites to send a calibrated sticker.

**Developer alpha.** This is a visual/UI bridge, not a peer-to-peer model or an official WeChat API. Content comes from screenshots; native Accessibility APIs locate windows and operate controls. WeChat databases and process injection are not used.

The reasoning and memory runtime is the original [AstrBot](https://github.com/AstrBotDevs/AstrBot) with [LivingMemory](https://github.com/lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory). The original [Stealer](https://github.com/nagatoquin33/astrbot_plugin_stealer) classifies incoming sticker crops; [Dafeiyu](https://github.com/whyever77/dafeiyu-astrbot) supplies the persona reference. See [attribution and pinned revisions](docs/ATTRIBUTION.md).

## Start here

Apple Silicon Mac, a dedicated macOS VM and WeChat account, DeepSeek credentials, and local Ollama are required. Plan around 32 GB RAM and 100 GB free disk for a 9B local vision model plus VM; this is a planning estimate, not a benchmarked minimum.

```bash
git clone https://github.com/andyDgreat12345/baguette-wechat.git
cd baguette-wechat
python3 scripts/baguette.py init
python3 scripts/baguette.py doctor
```

Follow the [full installation guide](docs/INSTALL.en.md). QR login, permission grants, account binding and a real private-chat send test remain local steps. New-machine installation is not yet independently validated.

## Capabilities and boundaries

- Scoped persona, long-term memory, retrieval and group-language learning through the QQ framework.
- Incoming visible images get local descriptions, emotion and usage labels; recent captions survive into a following “interpret this sticker” request.
- Favorites navigation, reverse ordering, scrolling, thumbnail matching and one-click sending after calibration.
- Groups are read; replies require addressing/mentions or a bounded conversational follow-up.
- A visible outgoing bubble is checked; this does not prove recipient delivery.
- Visible windows/current animation frames only. Full history, every group, complete GIFs, voice/video and restart-after-host-reboot coverage remain incomplete.
- Optional same-login-session controller supervision preserves run/pause intent. Ambiguous sends remain blocked.

No credentials, private conversations, learned memories, VM disks, model weights, or personal sticker collections are shipped. API usage may cost money. The public release includes configuration examples and import/calibration instructions rather than someone else's live account.

## Contribute

Read [CONTRIBUTING](CONTRIBUTING.md), [security](SECURITY.md), [privacy](docs/PRIVACY.md) and [roadmap](docs/ROADMAP.md). Reproducible, redacted compatibility reports and installation receipts are especially useful. If the project helps, a star makes it easier for others to find.

AGPL-3.0; upstream licenses are preserved. Not affiliated with Tencent/WeChat.
