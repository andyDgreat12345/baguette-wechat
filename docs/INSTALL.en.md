# Installation — developer alpha

[简体中文完整版](INSTALL.zh-CN.md) · [README](../README.en.md) · [Troubleshooting](TROUBLESHOOTING.md)

Use a dedicated macOS VM for the spare account. The host runs the controller, original QQ framework and models; a second Linux VM is unnecessary. This source release does not include a preconfigured account, a VM image, credentials, a private sticker pack or learned memories. A clean second-machine installation has not yet been accepted as complete.

## 1. Prerequisites

Apple Silicon Mac; Tart requires host macOS 13+. The development setup used Tart 2.41.1, guest macOS 26.6.2 and WeChat 4.1.15. Budget around 32 GB RAM and 100 GB free disk for a VM and 9B local vision model; this is a planning recommendation, not a measured minimum. You need a spare WeChat account, a phone for QR approval, a test contact and your own DeepSeek API key. API calls may cost money.

Install Command Line Tools (`xcode-select --install`), [Homebrew](https://brew.sh/), `brew install uv`, and `brew install cirruslabs/cli/tart`. Install/open [Ollama](https://ollama.com/download) from its official source. Keep default service ports private: Ollama 11434, AstrBot 6186, controller 8766 and credential relay 18764. Do not kill another application's listener.

## 2. Clone and initialize on the host

```bash
git clone https://github.com/andyDgreat12345/baguette-wechat.git
cd baguette-wechat
python3 scripts/baguette.py init
python3 scripts/baguette.py doctor
```

Edit ignored `runtime/installation.json`: set `bot_id` to the name used for mentions, `owner_chat` to the owner's exact display name, `owner_id` to the local admin identity, `group_chats` to an explicit allowlist and `vm_name`/`tart_binary` to your installation. The sample names are placeholders. If needed set proxy to `system` or an explicit HTTP CONNECT URL; default is `direct`. No provider fallback is configured.

Put your key only in `runtime/credentials.env` as `DEEPSEEK_API_KEY=...`, then `chmod 600 runtime/credentials.env`. Create it in your own [DeepSeek console](https://platform.deepseek.com/api_keys). Never put a real key in the guest bundle, command line, screenshot or public issue.

Set `runtime/settings.json` to `scope: selected_chats`, initially selecting only the owner private chat. Keep the generated persona. Host identity verification flags remain false until you actually inspect/bind the guest.

## 3. Install pinned host components

```bash
python3 scripts/baguette.py --dry-run fetch-upstreams
python3 scripts/baguette.py fetch-upstreams
python3 scripts/baguette.py host-setup
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python scripts/check_release.py
```

The fetcher checks out exact commits in `UPSTREAMS.lock.json` and refuses dirty upstream checkouts. uv creates a Python 3.13 venv and installs the pinned framework source plus plugin dependencies. It does not modify system Python. If a pinned package is unavailable, record the platform/version failure rather than silently replacing it with an unrelated latest revision.

Download local models with Ollama running:

```bash
ollama pull bge-m3
ollama pull qwen3.5:9b
ollama list
curl --noproxy '*' http://127.0.0.1:11434/api/tags
```

The default configuration uses local embeddings and vision on Ollama; DeepSeek handles conversational reasoning remotely. These are separate data paths. Custom local ports are configurable. The installer does not restart an unrelated Ollama server. First-time image analysis can be slow and captions can be wrong. See [Ollama compatibility](https://docs.ollama.com/api/openai-compatibility) for its API boundaries.

## 4. Create one macOS VM

```bash
python3 scripts/baguette.py --dry-run vm-create
python3 scripts/baguette.py vm-create
tart run baguette --no-clipboard --no-audio --no-usb-accessories
```

Adjust the name if changed. The script sets 4 CPUs, 8 GB RAM, 1280×800 logical display and disables display refitting. The default image follows [Tart's quick start](https://tart.run/quick-start/). Images are downloaded separately and follow their own licenses/default credentials; choose appropriate local credentials yourself. Alternatively create from IPSW with `tart create --from-ipsw=latest baguette` and finish macOS setup manually. A personal Apple ID and passwordless sudo are not required.

## 5. Install the guest helper

On the host:

```bash
python3 scripts/baguette.py guest-bundle
```

Transfer only `runtime/guest-bundle.tar.gz` to the guest. It contains source and nonsecret identity settings. One option is a dedicated read-only shared directory: copy the bundle to `runtime/share`, exit the current graphical Tart run cleanly, then run `tart run baguette --dir=baguette-share:./runtime/share:ro --no-clipboard --no-audio --no-usb-accessories`. Find the share in guest Finder; do not share the entire host Home.

Inside the guest, copy the bundle to Home and extract it. Install guest Command Line Tools and uv from their official sources, then:

```bash
cd ~
tar -xzf guest-bundle.tar.gz
cd ~/baguette
zsh setup-guest.zsh
```

The script refuses a physical Mac, root user or wrong destination. It creates guest Python, downloads a pinned v0.15.0 [Tart guest agent](https://github.com/openai/tart-guest-agent), checks archive/binary hashes, compiles and locally signs `~/Applications/Baguette.app`. A hash mismatch stops installation. No model secret is placed in the guest.

## 6. Permissions, account and layout

Install macOS WeChat from its official source inside the guest. QR-login to the dedicated spare account and verify it with your phone. Keep WeChat full screen, dark appearance, 1280×800 logical resolution.

Open guest Baguette.app and grant it Accessibility and Screen Recording in guest System Settings → Privacy & Security. A changed signing identity may require granting again. Use the application's permission check, then verify the actual RPC process from the host:

```bash
tart exec -i baguette /bin/zsh -c '"$HOME/baguette/.venv/bin/python" "$HOME/baguette/app/permission_probe.py"'
```

Both permissions must be true. The native wrapper's status alone does not prove its child can capture or click. Never edit TCC databases to bypass permission prompts.

Inside the guest, open the owner's exact private chat, verify the spare avatar/contact/empty composer, and bind:

```bash
cd ~/baguette
.venv/bin/python scripts/bind_guest.py --chat 'Exact owner display name' --owner-confirmed-spare
```

The confirmation flag means you actually checked the account. To add a selected group, open it and run the same command with `--group` and its exact current name. Binding records avatar fingerprints, PID and geometry locally. Changing account, restarting WeChat, changing avatars or layout requires review/rebinding. Renaming a confirmed group can retain scope via its selected sidebar avatar; this is not a server-side stable group ID.

## 7. Start the original QQ runtime

On the host:

```bash
.venv/bin/python scripts/setup_brain.py
.venv/bin/python scripts/brain.py start
.venv/bin/python scripts/brain.py install-persona
```

The fresh-instance configurator refuses to overwrite existing framework data. It derives settings from original plugin schemas, uses session-scoped LivingMemory/five-round reflection, disables alternate LLM providers and leaves original QQ automatic sticker sending off. The bridge performs actual WeChat actions. Persona initialization uses the AstrBot API rather than writing framework databases.

AstrBot listens at `http://127.0.0.1:6186`; randomly generated local dashboard credentials are in ignored `runtime/brain/auth.json`, never printed. Upstream persona and the actual WeChat capability overlay are separate; unavailable QQ browser/device/voice tools are not enabled.

## 8. Prove a new private reply

After actual guest inspection/binding, set `guest_adapter_verified` and `spare_account_verified` to true in host `runtime/controller-profile.json`. Keep visual adapter and AstrBot backend selected. These are owner attestations, not something a successful pip install establishes.

```bash
.venv/bin/python scripts/baguette.py start
```

The controller stays foreground and initially paused. In a second host terminal:

```bash
.venv/bin/python scripts/baguette.py check-model
.venv/bin/python scripts/baguette.py enable
.venv/bin/python scripts/baguette.py status
```

Open `http://127.0.0.1:8766`. Send a **new** plain-text message from the owner account. Verify: inbound appears → background reads it → DeepSeek generates final content → a new own bubble appears → no pending/uncertain delivery. Recipient receipt is a separate observation. A model connectivity test does not send WeChat messages and is not an automatic-reply acceptance test.

## 9. Import your own stickers

Text can work before stickers. No private guide or meme pack is included. The alpha sender currently expects exactly 36 IDs S01–S36, five columns, WeChat Favorites in reverse guide order (`position = 37 - guide_number`). Other sizes/layouts need sender changes and tests.

Prepare local `originals/S01.jpg` through `S36.jpg` plus `catalog.json` with `entries`, each containing id, name, meaning, use_when and avoid_when. Meanings must come from you or a source you may use, not guessed coordinates. See [sticker resources](../resources/stickers/README.md).

Pause the host controller. In guest Favorites, manually capture top, middle and bottom screenshots, including the final row, with `screencapture -x ~/baguette/runtime/favorites-top.png` and corresponding middle/bottom names. Keep screenshots private. Then in the guest:

```bash
.venv/bin/python scripts/calibrate_stickers.py --source /path/to/your-stickers \
  --top runtime/favorites-top.png --middle runtime/favorites-middle.png \
  --bottom runtime/favorites-bottom.png --confirm-reverse-order
.venv/bin/python app/sticker_adapter.py locate --chat 'Exact owner display name' --sticker S36
.venv/bin/python app/sticker_adapter.py locate --chat 'Exact owner display name' --sticker S01
```

Calibration matches source images to visible thumbnails and stops if a reliable match is absent. Review every ID/meaning and both end rows. `locate` opens/scrolls Favorites without sending; close the panel after checking.

Copy the resulting guest `runtime/stickers/` directory back to the host's corresponding runtime. Import semantics via the original memory API:

```bash
.venv/bin/python scripts/import_sticker_memory.py --chat 'Exact owner display name'
.venv/bin/python scripts/import_sticker_memory.py --chat 'Exact owner display name' --apply
```

The first command is a dry run. Group memory imports require `--group` and a configured group. Send a new sticker request in the test chat; physically verify opening, scrolling, correct selection and a new outgoing sticker. A tool selection is not a successful send. Uncertain actions must not be clicked again without checking.

## 10. Groups, continuous operation and shutdown

After private validation, pause, select the bound group in host settings and enable again. Read groups; respond when mentioned/directed or in a bounded same-speaker follow-up. Private owner memory stays separate from group memory.

Optional same-login-session crash recovery: set `auto_resume_on_restart: true` in the host profile, explicitly enable once to save run intent, stop the existing controller, then run `.venv/bin/python app/supervise_controller.py`. Do not start duplicate controllers. The supervisor checks its own process identity and preserves paused intent/uncertain-delivery blocks. It does not unlock the host or guarantee recovery after a host reboot.

Guest `caffeinate -dimsu` can prevent idle sleep while running; stop that process to undo it. The host must remain running too. Do not disable authentication or have scripts guess passwords. Unknown dialogs, account changes and screen locks require restoring an actually controllable UI.

Pause with `.venv/bin/python scripts/baguette.py pause`; stop owned framework/relay services with `.venv/bin/python scripts/brain.py stop`. Exit the controller/supervisor and guest wrapper you started. Stop services before an encrypted local runtime backup. The project does not delete WeChat's own databases. See [privacy](PRIVACY.md) and [troubleshooting](TROUBLESHOOTING.md).
