<div align="center">
<img src="assets/hero.svg" alt="Baguette — 微信大肥鱼" width="880" />

# Baguette 🥖 · 微信大肥鱼

**会接话、记得住，也看得懂表情的微信伙伴。**

纯视觉微信桥 × DeepSeek × 原版 QQ 记忆与表情框架

[English](README.en.md) · [安装指南](docs/INSTALL.zh-CN.md) · [Agent 安装](AGENTS.md) · [架构](docs/ARCHITECTURE.md) · [致谢](docs/ATTRIBUTION.md)

![status](https://img.shields.io/badge/status-alpha-f0b35b)
![platform](https://img.shields.io/badge/platform-Apple%20Silicon-222222)
![python](https://img.shields.io/badge/Python-3.13-3776AB)
![license](https://img.shields.io/badge/license-AGPL--3.0-4a8f72)
</div>

## 它做什么

Baguette 把一个独立 macOS 虚拟机里的普通微信小号接到 AstrBot。它从**可见聊天窗口的截图**读消息和表情，用 DeepSeek 回应，通过真实微信界面输入、点击和滚动发送。窗口定位、权限检查和点击使用 macOS 原生接口；**不读取微信聊天数据库，不注入微信进程**。

这里的「纯视觉」指聊天内容来自屏幕，而不是微信协议或私有数据库。它不是点对点网络模型，也不是微信官方机器人 API。

- **有性格的回复**：大肥鱼人设，中文、英文、群聊混合语境。
- **沿用 QQ 的记忆**：真实 AstrBot + LivingMemory，分会话召回、总结、明确纠正和群体用语学习。
- **表情语义**：原版 `astrbot_plugin_stealer` 负责视觉分类、情绪和使用场景，本地视觉结果交给 DeepSeek 理解。
- **表情动作**：打开收藏，按目录定位，下滚到剩余行，核对缩略图后点一次。
- **群聊参与**：读群；被提及、被定向及短时连续交流时回应。主号私聊和群聊记忆隔离。
- **可核对的发送**：空草稿、账号和目标验证；发送后检查自己的气泡。结果不明确时暂停，避免重复发送。

## 开始使用

需要 Apple Silicon Mac、一个独立 macOS VM、微信小号、DeepSeek API key，以及本地 Ollama。建议 **32 GB 内存 / 100 GB 以上空闲磁盘**作为部署预算，并非测得的最低配置；本地 9B 视觉模型占用较大。DeepSeek API 可能计费，软件不会替换到别的模型服务商。

```bash
git clone https://github.com/andyDgreat12345/baguette-wechat.git
cd baguette-wechat
python3 scripts/baguette.py init
python3 scripts/baguette.py doctor
```

然后按 [中文完整安装](docs/INSTALL.zh-CN.md) 配置宿主机、VM、权限、QQ 框架、私聊验证和表情校准。二维码登录和 macOS 权限由你在本机完成。**当前是开发者 alpha，不是一键即用的通用微信安装器。**

## 实现状态

| 能力 | 当前边界 |
|---|---|
| 可见文字读取与自动回复 | 已在项目专用 VM 中验证；不同微信版本/布局需重新校准 |
| 记忆与学习 | 原版 LivingMemory；分会话，归纳可能出错，应允许用户纠正 |
| 图片/表情理解 | 可见截图裁切；动图仅当前帧；视觉模型可能误读 |
| 收藏表情发送 | 专用环境的 36 张逆序收藏已校准；公开版需导入自己的素材和语义 |
| 改群名 | 用户确认过的群头像绑定可保持会话；头像变化需重新核实 |
| 自动恢复 | 可选保存运行/暂停意图 + 当前登录会话内的进程监督；未完成跨主机重启验收 |
| 所有群、完整历史、语音/视频 | 尚未完整支持；不能承诺读取每一条或每个动画帧 |
| 全新机器安装 | 提供脚本/分步指南；未在第二台空白 Mac 上完成全流程验收 |

## 为什么沿用 QQ 框架

本项目的桥接代码负责微信 UI。记忆、检索、反思与表情分类来自已有开源项目，没有把这些上游工作包装成自己的原创算法：

| 项目 | 本项目使用的部分 |
|---|---|
| [AstrBot](https://github.com/AstrBotDevs/AstrBot) | 原生消息流水线、模型调用、工具与会话 |
| [LivingMemory](https://github.com/lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory) | 长期记忆、召回、总结和学习 |
| [Stealer](https://github.com/nagatoquin33/astrbot_plugin_stealer) | 表情视觉分类与本地索引 |
| [大肥鱼](https://github.com/whyever77/dafeiyu-astrbot) | 原版人设与行为参考；不声称移植了所有 QQ 工具 |

版本、固定提交和许可证见 [归属说明](docs/ATTRIBUTION.md) 与 [UPSTREAMS.lock.json](UPSTREAMS.lock.json)。

## 参与项目

欢迎提交可复现的 UI 兼容问题、脱敏测试样例、文档翻译和安装验证结果。先看 [贡献指南](CONTRIBUTING.md)。截图请遮住昵称、头像和聊天内容。喜欢这个方向，可以给仓库一个 ⭐，也欢迎把失败案例带回来一起修。

[隐私与限制](docs/PRIVACY.md) · [排错](docs/TROUBLESHOOTING.md) · [路线图](docs/ROADMAP.md) · [安全报告](SECURITY.md)

本项目与腾讯/微信没有官方关联。代码以 AGPL-3.0 发布；上游和模型、虚拟机、第三方素材分别遵循各自许可。请仅在自己有权使用的账号、素材和聊天中部署。
