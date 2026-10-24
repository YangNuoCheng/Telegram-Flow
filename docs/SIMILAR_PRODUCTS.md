# Telegram-Flow 同类产品对比

核验日期：2026-10-24。仅查阅公开仓库、代码与项目文档，未安装候选产品、未登录其服务、未接入个人 Telegram 会话。功能说明是源码/文档核验，不代表实际运行验收。“未核实”不能理解为确定没有。

## 结论

最直接的同类是 **tiktok-gram**：Telegram 频道采集、竖屏刷看、兴趣匹配、已读过滤、频道分散和照片比例控制，已覆盖本项目不少核心想法。其默认媒体路径包含下载、转码和上传 Cloudflare R2，与用户当前希望仅在本机运行、尽量不保存媒体的要求存在差异。值得对照设计，尚不宜直接替换。[仓库与架构说明](https://github.com/nordost8/tiktok-gram#how-it-works)、[排序文档](https://github.com/nordost8/tiktok-gram/blob/main/docs/ranking.md)。

最值得参考播放交互的是 **Spooly** 和 **Erin**。Spooly 已提供长按二倍速、混合媒体刷看、跨设备续播；Erin 已提供视频从中间或随机位置起播。两者文档均以本地媒体目录为主要入口，本次未核实原生 Telegram 频道接入。[Spooly](https://github.com/oddloafhq/spooly#what-it-does)、[Erin](https://github.com/will-moss/erin#features)。

## 功能对比

| 项目 / 仓库 | 与 Telegram-Flow 相似之处 | 喜好与 AI 能力的证据 | 数据路径、部署与主要差异 |
| --- | --- | --- | --- |
| [tiktok-gram](https://github.com/nordost8/tiktok-gram) | Telegram Mini App 竖屏流、图片轮播、收藏、已读过滤、频道分散、照片比例上限 | 已核实 `scorePost()` 按新鲜度、应用内点赞/收藏/浏览量、兴趣类别和订阅打分；这是显式公式，未核实按个人停留学习权重。翻译可选接 OpenAI 兼容服务；图片配乐选择仍是占位实现。[排序代码](https://github.com/nordost8/tiktok-gram/blob/main/packages/api/src/lib/feed-query.ts)、[文档](https://github.com/nordost8/tiktok-gram/blob/main/docs/ranking.md)、[README](https://github.com/nordost8/tiktok-gram#readme) | Telethon + Next.js + PostgreSQL + Redis，默认视频下载/转码后上传 R2；包含 Compose 配置。更接近可多用户使用的 Telegram 产品，部署复杂度较高。[架构](https://github.com/nordost8/tiktok-gram/blob/main/docs/architecture.md) |
| [Spooly](https://github.com/oddloafhq/spooly) | 图视频混合竖屏流、双击收藏、长按 2×、横向拖动定位、续播 | 官网描述 EmbeddingGemma 语义搜索和相似视频检索，可接自托管或云端；本次为官方说明核验，未完成模型代码与运行验证。未核实停留驱动的在线偏好学习。[官方说明](https://oddloaf.dev/spooly/)、[交互文档](https://github.com/oddloafhq/spooly#flow-controls) | 以本地目录为输入；Docker 支持 amd64/arm64。普通播放在自有服务器；可选 AI 按配置向提供商发送所选图片。未核实原生 Telegram 接入。[README](https://github.com/oddloafhq/spooly#readme) |
| [Erin](https://github.com/will-moss/erin) | 本地图片/视频竖屏流、屏蔽媒体、自动翻刷、视频从开头/中间/随机位置播放 | 已核实随机播放列表和媒体屏蔽；未核实机器学习推荐、语义搜索或个人停留学习。[功能说明](https://github.com/will-moss/erin#features) | React + Caddy，Docker 挂载本地媒体目录。更适合作为轻量播放器参考；未核实原生 Telegram 接入。[部署说明](https://github.com/will-moss/erin#deployment-and-examples) |
| [Televizor](https://github.com/s0larpunk/televizor) | 把多个 Telegram 频道汇入同一个阅读入口；关键词、媒体类型过滤和频道频率限制 | README 明确采用时间顺序，宣称无算法和无跟踪；未核实 AI 或偏好学习。[功能说明](https://github.com/s0larpunk/televizor#readme) | 将源频道消息转发到目标频道，在 Telegram 内阅读。Python/Next.js/PostgreSQL/Redis；当前 README 自托管步骤为手动部署，并仍把 Docker Compose 列为待贡献事项，不能据 Reddit 宣传认定现成 Docker 已可用。[安装说明](https://github.com/s0larpunk/televizor#self-hosting)、[待贡献项](https://github.com/s0larpunk/televizor#contributing) |
| [Telegramedia](https://github.com/kernoeb/telegramedia) | 聚合选中聊天的视频、边下载边播放、预缓冲、跨次打开续播、搜索和速度控制 | 未核实个性化推荐或 AI；已核实可选 30 秒至 2 分钟提前缓冲。[功能说明](https://github.com/kernoeb/telegramedia#features) | Android arm64，TDLib + libmpv；不是 Mac/浏览器 Docker 服务。流式缓存与离线下载均有存储管理。[平台与功能](https://github.com/kernoeb/telegramedia#readme) |
| [Telegram Media Downloader](https://github.com/botnick/telegram-media-downloader) | 自托管 Telegram 媒体库、网页图库、搜索、PWA、视频定位预览 | 可选人脸聚类和 媒体分类 sidecar；本次仅核实项目明确列出的功能与容器入口，未跑模型。未核实按个人口味自动排序。[README](https://github.com/botnick/telegram-media-downloader#readme) | Go 服务，Docker amd64/arm64；核心目标是下载归档和备份，媒体保存在配置的存储中。更适合收藏归档而非尽量不落盘的刷看。[仓库说明](https://github.com/botnick/telegram-media-downloader) |

## 项目规模快照

下表通过 GitHub API 查询；`pushed_at` 是最近推送时间，不能等同于最后一次实质代码修改时间，也不用于证明产品成熟。

| 项目 | Stars | 最近推送（UTC 日期） | 许可证 | 元数据来源 |
| --- | ---: | --- | --- | --- |
| tiktok-gram | 0 | 2026-09-01 | MIT | [API](https://api.github.com/repos/nordost8/tiktok-gram) |
| Spooly | 5 | 2026-10-20 | MIT | [API](https://api.github.com/repos/oddloafhq/spooly) |
| Erin | 364 | 2026-08-15 | MIT | [API](https://api.github.com/repos/will-moss/erin) |
| Televizor | 22 | 2026-08-05 | GPL-3.0 | [API](https://api.github.com/repos/s0larpunk/televizor) |
| Telegramedia | 4 | 2026-07-11 | GPL-3.0 | [API](https://api.github.com/repos/kernoeb/telegramedia) |
| Telegram Media Downloader | 19 | 2026-10-18 | MIT | [API](https://api.github.com/repos/botnick/telegram-media-downloader) |

## 对当前项目的建议

继续保留当前实现，对照 tiktok-gram 的“媒体就绪后可见”、排序和多样性逻辑，参考 Spooly/Erin 的播放交互。这是基于文档与架构差异的工程判断，尚未做候选产品的实机性能比较。[tiktok-gram 可见性代码](https://github.com/nordost8/tiktok-gram/blob/main/packages/api/src/lib/feed-query.ts)、[Spooly 交互](https://github.com/oddloafhq/spooly#flow-controls)、[Erin 功能](https://github.com/will-moss/erin#features)。

当前 Telegram-Flow 已在本项目中实现事件记录、停留信号、关键词及组合权重、已读过滤、频道分散和媒体比例控制，但这些是轻量的特征模型与规则；没有据此验证推荐质量优于上述产品，也没有完整的 agent 发现或视觉语义理解。[本项目实现](../app.py)、[前端](../index.html)。

## 查过但未列入重点比较

- [Foldergram](https://github.com/foldergram/foldergram)：公开介绍偏向本地目录的 Instagram 式图库，与本次 Telegram 在线流的主线较远，本次未继续核验其 AI 和 Telegram 能力。
- [Igloo](https://github.com/screwys/Igloo)：项目定位是 YouTube、X、Instagram、TikTok 社交收件箱，本次未核实 Telegram 接入，因此未列为直接替代品。

名称检索未形成商标或全球项目重名排查结论。Telegram-Flow 是独立项目名称，不代表 Telegram 官方产品。
