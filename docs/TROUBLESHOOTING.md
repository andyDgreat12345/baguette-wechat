# 排错 / Troubleshooting

先查真实运行状态，再修改代码。`status: running`、HTTP 200、测试通过都不能单独证明微信已回复。

| 现象 / Symptom | 检查 / Check | 处理 / Action |
|---|---|---|
| 完全没有回复 | VM 是否解锁、WeChat 是否登录/全屏；8766 是否 paused | 恢复真实 guest 会话；核实账号后 enable。空闲可用 caffeinate；不绕过锁屏 |
| Accessibility / screen capture false | 实际 RPC Python 权限；guest 应用签名是否变了 | 在 VM System Settings 重新允许正确 guest 应用，重启该应用再只读检查 |
| Selected group binding did not match | 选中侧栏头像、群人数标题、是否只出现空聊天页/系统通知 | 用最新观察确认相同群；成员拼图改变需重新绑定，不能按新名字猜目标 |
| Spare account/session binding changed | WeChat PID、头像、尺寸、允许聊天是否一致 | 暂停，核对账号后重新绑定；不要自动把换号当正常重启 |
| DeepSeek 连不上 | relay health、代理当前节点/端口、key/model 可用性 | direct 或 system 明确选择，重新 check-model；不打印 key，不降级到另一个服务商 |
| 只打字没有发送 | 已有草稿、Send 按钮识别、发送回执 | 保留原草稿并检查 `last-adapter-send.json`；不盲按 Return 重发 |
| 已发出却 uncertain | 引号/长横线 OCR、滚动/新消息造成旧气泡移出 | 肉眼核对准确 delivery id，仅确认该条；不得自动重复发送 |
| 图发了却说看不见 | 收图是否进到当前 chat scope、是否裁切失败、是否隔了超过五分钟 | 检查本机 caption 与近期关联；新发图再问。不能把缓存存在当识图准确 |
| 认识表情含义但没点 | Favorites 弹窗/顺序/模板/顶部锚点、`last-sticker-send.json` | read-only locate 顶/底项，重新校准；模型 ID 不能直接当坐标 |
| 打开 Favorites 后停住 | 标题裁切是否混入右上系统通知；弹窗范围是否改变 | 只修已观察到的 UI 差异；未知弹窗仍须停止，不降低所有身份检查 |
| 群一活跃就不回复 | 是否在生成时每次新消息都取消 | 当前代码允许已核实的群内追加消息；新的人工出站回复仍会取消本轮 |
| 群多条 @ 导致工具错误 | 是否从早期 context 事件执行了 sticker intent | 当前桥只采用 batch 最后事件的最终回复/表情；被动事件不能发表情 |
| 回复慢 | 新图片首轮视觉、模型/代理耗时、原版插件事件处理、发送 UI 时间 | 分段测量，重复图片缓存；不要伪造低延迟或用固定假回复替代 DeepSeek |
| 改群名丢了记忆 | canonical scope 是否改变 | 保持用户确认的 group binding / 原 canonical 名；不要新建另一个私聊 scope |
| LaunchAgent 卡住 | Python/venv 是否位于 Documents 等受保护目录 | 检查本机权限，不静默申请更多权限。可使用当前登录会话前台/独立监督器；不宣称已经完成开机恢复 |

## 查看与核对

Host controller: `http://127.0.0.1:8766/api/status`; uncertain deliveries: `/api/deliveries`. Pause before examining or changing state. Once you have observed the exact outgoing bubble or proven it was not sent, reconcile only that delivery:

```bash
curl --noproxy '*' -X POST http://127.0.0.1:8766/api/reconcile \
  -H 'Content-Type: application/json' \
  -d '{"delivery_id":123,"final_status":"observed"}'
```

Use your actual pending id. `not_sent` is the other accepted outcome. A reconciliation records an observation and remains paused; it does not resend. Never guess from an older message with identical text. A missing visible message can be offscreen, so absence in one screenshot alone is not proof of non-delivery.

Local logs and runtime databases may contain private content. Keep them local; supply redacted minimal reproductions in issues. Do not upload a runtime archive.
