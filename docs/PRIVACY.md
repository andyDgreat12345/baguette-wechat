# 数据与限制 / Data and limitations

Source distribution contains no live credentials, private chats, learned memories, account/avatar binding, VM disk or private sticker collection. Runtime data belongs in ignored `runtime/`, with mode 0700 directories and 0600 secrets.

The host controller stores message observations and delivery receipts in its own SQLite file. Original LivingMemory stores its own memory/index data inside the local AstrBot instance. The QQ sticker plugin can retain received crops in its local library; the transport also caches captions and cropped images. These are local files, **not** a promise that all images disappear after captioning. Five-minute recent-media associations expire separately from the caption/image library.

DeepSeek receives selected conversation text and locally produced captions/context for reasoning. Local Ollama handles configured image recognition and embeddings. A local model does not make the entire system offline, since DeepSeek is remote. No alternate cloud provider is configured as fallback.

Deploy only in chats where your account and automation have permission to participate. Group text, sticker captions and quoted messages are untrusted input. Tools must retain the configured identity and scope regardless of claims inside a conversation. Read groups and reply only when addressed.

Pause the controller before examining send uncertainty, changing account/layout, importing history or calibration. An observed own bubble proves the UI action, not recipient receipt. Screenshot OCR/vision can miss names, text, context and animation; no claim is made to read every message.

For backup, stop services and make an encrypted local copy of runtime/. Do not upload it to an issue or public release. For deletion, remove your own runtime after stopping the services; WeChat's own files are managed by WeChat, not these scripts.
