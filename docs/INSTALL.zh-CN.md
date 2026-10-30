# 完整安装指南（开发者 Alpha）

[English](INSTALL.en.md) · [返回首页](../README.md) · [排错](TROUBLESHOOTING.md)

这份指南从一台 Apple Silicon Mac 开始。宿主机运行模型/QQ 框架；**一个独立 macOS 虚拟机**运行微信小号。不要在主号的桌面直接试点击脚本。公开源码不包含开发者的账号绑定、聊天记录或表情素材。

## 0. 先确认条件

- Apple Silicon Mac。Tart 官方要求宿主 macOS 13 或以上；项目开发环境是 Tart 2.41.1、guest macOS 26.6.2、微信 4.1.15。其他版本需要实际复验。
- 建议按 32 GB RAM、100 GB 以上空闲磁盘准备预算。VM 示例分配 4 CPU / 8 GB；这不是已验证的最低硬件要求。Tart 基础镜像和模型下载都可能很大。
- 一个你控制的微信小号、用于扫码确认的手机，以及一个主号测试联系人。保持原有主号登录不受影响。
- 自己的 DeepSeek API key；API 可能计费。本地视觉/向量模型另需内存和磁盘。
- 安装时可访问 GitHub、包仓库、Tart 镜像和模型服务。代理必须可以实际访问目标服务。

安装分为「代码就绪」「VM/权限就绪」「真实收发验收」三件事。不能用单元测试通过代替第三件事。

## 1. 获取源码和宿主工具

先安装 Apple Command Line Tools：

```bash
xcode-select --install
```

按 [Homebrew 官方页面](https://brew.sh/) 安装 Homebrew 后：

```bash
brew install uv
brew install cirruslabs/cli/tart
```

从 [Ollama 官方下载](https://ollama.com/download) 安装并打开 Ollama。下面所有仓库命令都在**宿主机**运行，除非明确写了「VM 内」。

```bash
git clone https://github.com/andyDgreat12345/baguette-wechat.git
cd baguette-wechat
python3 scripts/baguette.py init
python3 scripts/baguette.py doctor
```

`doctor` 只检查前置工具/端口。返回非零表示有待处理项；端口已被占用时先核对归属，不要杀掉别的项目。当前控制端口为 8766，AstrBot 为 6186，凭证转发为 18764，默认 Ollama 为 11434。

## 2. 本地配置和凭证

编辑 `runtime/installation.json`：

| 字段 | 示例与用途 |
|---|---|
| `bot_id` | 小号被 @ 时看到的名字，例如 `baguette` |
| `owner_id` | 本地 AstrBot 管理身份，例如 `owner`；不要用群友文本来改变它 |
| `owner_chat` | 主号在小号中的准确私聊显示名 |
| `group_chats` | 你明确选择的群名列表；先只验证私聊，再加群 |
| `vm_name` | Tart VM 名，默认 `baguette` |
| `tart_binary` | `tart` 或实际可执行文件绝对路径 |
| `proxy` | 默认 `direct`；需要时改 `system` 或 `http://127.0.0.1:端口` |
| `deepseek_model` | 默认 `deepseek-flash`，需在你的 API 账号可用 |
| `vision_model` / `embedding_model` | `qwen3.5:9b` / `bge-m3` |

在 [DeepSeek 控制台](https://platform.deepseek.com/api_keys) 创建自己的 key，仅填进 `runtime/credentials.env`：

```dotenv
DEEPSEEK_API_KEY=your-own-key
```

```bash
chmod 600 runtime/credentials.env
```

不要把 key 写进命令行、截图、issue、GitHub Secret 以外的公开配置或 guest bundle。`runtime/` 已被忽略，但发布前仍要检查 git 暂存区。

先把 `runtime/settings.json` 的 `selected_chats` 改成仅含主号私聊显示名。`persona` 已由 init 写入。保持 selected_chats 范围，不要把所有群的权限当作默认启用。

## 3. 固定上游与 Python 环境

```bash
python3 scripts/baguette.py --dry-run fetch-upstreams
python3 scripts/baguette.py fetch-upstreams
python3 scripts/baguette.py host-setup
```

第一条只展示计划。实际脚本按 `UPSTREAMS.lock.json` 固定提交下载 AstrBot、LivingMemory、Stealer 和 Dafeiyu，拒绝覆盖有本地修改的 checkout。Python 使用 uv 管理的 3.13；依赖装进仓库 `.venv/`，不会修改系统 Python。

```bash
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python scripts/check_release.py
```

若某个固定版本在你的平台不可下载，请提交版本/平台信息；不要无记录地改成任意最新版然后继续声称同一安装通过。

## 4. 本地模型

确认 Ollama 已运行，再下载模型：

```bash
ollama pull bge-m3
ollama pull qwen3.5:9b
ollama list
curl --noproxy '*' http://127.0.0.1:11434/api/tags
```

视觉与 embeddings 默认共享本地 Ollama。可以在 installation.json 指定你自己的本地端口；本项目不会重启或清空别的项目的 Ollama 服务。不要把本地地址误填成云模型地址。

本地视觉通过 AstrBot 的 Ollama 兼容路径配置禁用 thinking，并限制输出。新图片识别仍可能明显慢于文字回复，重复裁切有缓存。详见 [Ollama 兼容文档](https://docs.ollama.com/api/openai-compatibility)；不能把 `think:false` 在任意 OpenAI 兼容接口上当成已验证生效。

## 5. 创建 VM

按 [Tart 官方指南](https://tart.run/quick-start/) 使用基础镜像，或从 IPSW 手动创建。基础镜像是外部下载，不随仓库分发。

```bash
python3 scripts/baguette.py --dry-run vm-create
python3 scripts/baguette.py vm-create
# 默认 VM 名；如果改过配置，使用你配置的名字
tart run baguette --no-clipboard --no-audio --no-usb-accessories
```

脚本设置 4 CPU、8192 MB 内存、1280×800 逻辑屏幕并关闭动态 display refit。基础镜像的默认登录信息见官方指南；首次登录后由你设置合适的本地凭证。不要求在 VM 登录个人 Apple ID，不要求关闭安全保护或启用免密码 sudo。

另一种方式：`tart create --from-ipsw=latest baguette`，然后手动完成 macOS 初始化。创建不等于能操作微信；后面还需要 guest helper、权限和登录。

## 6. 构建并传入 guest bundle

宿主机：

```bash
python3 scripts/baguette.py guest-bundle
```

只把 `runtime/guest-bundle.tar.gz` 传到 VM。它含源代码、guest 安装脚本和非秘密身份配置，不含 DeepSeek key、宿主聊天历史和框架数据库。可使用 Tart 的单独共享目录，别共享整个宿主 Home：

```bash
# 先退出当前 VM 图形运行，再重新带共享目录启动；不要强杀正在工作的 VM
mkdir -p runtime/share
cp runtime/guest-bundle.tar.gz runtime/share/
tart run baguette --dir=baguette-share:./runtime/share:ro --no-clipboard --no-audio --no-usb-accessories
```

VM 内 Finder 的网络/共享位置可找到 `baguette-share`（常见挂载位置 `/Volumes/My Shared Files/baguette-share`；以实际 Finder 为准）。将压缩包复制进 VM Home 后：

```bash
cd ~
tar -xzf guest-bundle.tar.gz
cd ~/baguette
```

VM 内也需要 Command Line Tools 和 uv，按上述官方安装来源安装。然后**在 VM 内**：

```bash
zsh setup-guest.zsh
```

脚本只允许运行在 `VirtualMac`、普通用户、`~/baguette` 路径。它建立 guest Python，下载固定 v0.15.0 Tart guest-agent 并校验 archive/二进制 SHA-256，编译 `Baguette.app` 并进行本地 ad-hoc 签名。哈希不符会停止，不会绕过。guest-agent 来源见 [归属](ATTRIBUTION.md)。

## 7. VM 内权限、微信和布局

从微信官方来源安装 macOS 微信，登录**专用小号**。二维码/手机确认由你完成。把 WeChat 保持全屏、深色模式、1280×800 逻辑布局。

打开 `~/Applications/Baguette.app`，在 guest 系统设置的「隐私与安全性」中为该 guest 应用授予「辅助功能」「屏幕与系统音频录制/屏幕录制」。应用身份/签名改变可能需要重新授权。使用应用内「检查权限」后再核实**实际 guest RPC 里的 Python**也读得到画面；原生窗口显示权限成功不等于所有子进程都成功。

宿主机只读检查：

```bash
tart exec -i baguette /bin/zsh -c '"$HOME/baguette/.venv/bin/python" "$HOME/baguette/app/permission_probe.py"'
```

要求 `accessibility` 和 `screen_capture` 为 true。不能通过编辑 TCC 数据库绕过授权。

VM 内先打开与主号的私聊，肉眼确认左侧小号头像、当前联系人和空草稿。然后：

```bash
cd ~/baguette
.venv/bin/python scripts/bind_guest.py --chat '主号准确显示名' --owner-confirmed-spare
```

这个确认标记只应在你确实核对了账号后使用。绑定含小号头像指纹、PID、尺寸与聊天白名单，仅保存在 guest。微信重启 PID 改变、换账号/头像/布局后需要复核。添加群时先打开那个群：

```bash
.venv/bin/python scripts/bind_guest.py --chat '群当前准确名称' --group --owner-confirmed-spare
```

群头像绑定可跨群名变化，但并非微信服务端稳定 ID。成员头像拼图改变时也可能需要重新确认。

## 8. 启动原版 QQ 框架

回到宿主仓库：

```bash
.venv/bin/python scripts/setup_brain.py
.venv/bin/python scripts/brain.py start
.venv/bin/python scripts/brain.py install-persona
```

`setup_brain` 只为新 instance 生成配置，已有数据时拒绝覆盖。它从上游 schema 生成 LivingMemory/Stealer 配置，启用 session 隔离和五轮反思；网络回退 provider 为空。原版 QQ 自动发表情路径关闭，由微信桥发送意图来执行一次点击。

AstrBot 在 `http://127.0.0.1:6186`。随机管理凭证只写入 `runtime/brain/auth.json`，不要公开。人设通过官方实例 API 写入，不编辑框架数据库。原始 QQ 人设和 WeChat 能力覆盖分别保留，未实现的 QQ 工具不能冒充可用。

## 9. 启动控制器，先做私聊验收

肉眼确认 guest 账号、权限与绑定后，在宿主 `runtime/controller-profile.json` 将 `guest_adapter_verified` 和 `spare_account_verified` 设为 true；`adapter_mode` 保持 `visual`、`model_backend` 保持 `astrbot`。这是你对真实绑定的确认，不是安装脚本推测出来的结果。

```bash
.venv/bin/python scripts/baguette.py start
```

控制器前台运行，初始保持暂停；另开宿主终端：

```bash
.venv/bin/python scripts/baguette.py check-model
.venv/bin/python scripts/baguette.py enable
.venv/bin/python scripts/baguette.py status
```

打开 `http://127.0.0.1:8766`，从主号向小号发**新**消息。验收应包括：新消息出现 → 后台读取 → DeepSeek 最终文字 → 小号微信出现新的自己的气泡 → 无 pending/uncertain 发送。确认接收端实际收到则另外记录，自己的气泡不能证明网络送达。

模型连接测试不发送微信消息。不要把它的成功当成自动回复已经成功。无实际新消息时不会重放整段旧聊天。

## 10. 自带表情、逆序与滚动

没有表情素材也可以先运行文字。公开包不含个人收藏/PDF。准备你有权使用的 36 张 `originals/S01.jpg`…`S36.jpg`，以及一个 `catalog.json`，每项至少：

```json
{"entries":[{"id":"S01","name":"惊讶","meaning":"对意外消息的惊讶反应","use_when":["无害的意外"],"avoid_when":["严肃求助"]}]}
```

实际文件应包含全部 S01–S36。PDF/说明序号是语义 ID；微信位置反序 `37 - 序号`。五列，S36 第一、S01 最后。不同数量/布局需要改 sender 和测试，不能只改这个数字。

暂停控制器。在 VM 收藏里按真实顺序放好素材，分别截图顶部、向下滚动的中部、底部（包括最后一行）。guest 截图命令：

```bash
screencapture -x ~/baguette/runtime/favorites-top.png
# 在收藏内手动向下滚到中部，再拍 middle；滚到底，再拍 bottom
```

不要拍到真实聊天再上传；截图留在自己的 runtime。把素材目录放在 guest 本地，然后：

```bash
cd ~/baguette
.venv/bin/python scripts/calibrate_stickers.py --source /path/to/your-stickers \
  --top runtime/favorites-top.png --middle runtime/favorites-middle.png \
  --bottom runtime/favorites-bottom.png --confirm-reverse-order
```

脚本从原图匹配实际缩略图生成本地 `runtime/stickers/catalog.json`；匹配失败就停止。人工复核所有 ID/含义和顶/底行，再做**只定位不发送**检查：

```bash
.venv/bin/python app/sticker_adapter.py locate --chat '主号准确显示名' --sticker S36
.venv/bin/python app/sticker_adapter.py locate --chat '主号准确显示名' --sticker S01
```

`locate` 可能打开收藏并下滚；确认无误后关闭收藏。将同一已校准 `runtime/stickers/` 复制回宿主仓库对应 runtime，导入语义到原版记忆：

```bash
# 宿主机；默认先 dry-run
.venv/bin/python scripts/import_sticker_memory.py --chat '主号准确显示名'
.venv/bin/python scripts/import_sticker_memory.py --chat '主号准确显示名' --apply
# 群内语义独立导入需 --group 并选择已配置的群
```

请主号发送新的表情请求，实际观察一次打开收藏、滚动、选中正确图和新的出站表情。若结果 uncertain，先核对记录，不可重复点击碰碰运气。运行时的收图分类可建立表情含义；明确纠正通过 LivingMemory 保存，不把一次识图猜测当真理。

## 11. 切到群与持续运行

私聊通过后暂停，将 host settings.selected_chats 改成已绑定的目标群，再恢复。群聊被 @/定向才回复，短时同一发言者可以连续交流；群与主号私聊记忆隔离。

若要当前登录会话里自动重启控制器：profile 加 `auto_resume_on_restart: true`，显式启用控制器以保存 `run-intent.json`，停止已有 controller 后运行：

```bash
.venv/bin/python app/supervise_controller.py
```

不要同时手动启动第二个 listener。监督器只接管本项目的已核实 PID/端口；会保留暂停意图和 uncertain 阻断。它不负责开机解锁/重新扫码，也没有完成整机重启验收。

在 VM Terminal 中 `caffeinate -dimsu` 可在运行期间防止空闲休眠；退出该进程即可撤销。宿主机也必须保持运行。不要为了省一步关闭整机认证或让脚本猜密码。界面被锁、退出微信、换号、出现未知弹窗时，需要恢复真实可控状态。

## 12. 暂停、备份与卸载

```bash
.venv/bin/python scripts/baguette.py pause
.venv/bin/python scripts/brain.py stop
```

退出你启动的 controller/supervisor 和 guest Baguette.app。备份前停止服务，将整个 runtime 做加密本地副本。源代码、账号绑定、记忆库和 WeChat 自身聊天备份是不同东西。卸载时删除本项目目录/自己的 VM 前先保留要保留的数据；脚本不会删除微信数据库或更改主号文件。

排错顺序：VM 解锁/前台 → guest 权限 → 小号/聊天绑定 → 草稿和弹窗 → 模型连接 → 消息新旧基线 → 发送回执。详见 [排错表](TROUBLESHOOTING.md)。
