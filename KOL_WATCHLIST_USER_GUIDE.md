# KOL Watchlist Briefing 使用说明

这份说明面向第一次使用这个工具的人。你不需要懂 Python 或 YAML，也不需要知道 Codex skill 是什么。可以把它理解成一个“我关注的人和频道的更新提醒器”：

- 你把想关注的账号、频道、播客、RSS、GitHub 项目放进关注列表。
- 手动运行一次，工具会抓取这些来源最近的更新。
- 报告会按“最值得先看什么”排序，而不是只按发布时间堆在一起。
- 开发阶段先手动运行；稳定后可以每天定时运行。

## 适合监控什么

当前最适合接入这些稳定来源：

- YouTube 频道
- 小宇宙播客
- RSS / Atom 订阅源
- GitHub releases
- 微信公众号本地库，也就是 We-MP-RSS 已经抓到的文章
- 通过 RSSHub 提供的 B站 UP 主、Telegram 公开频道等

不建议一开始就依赖这些不稳定来源：

- X / Twitter 无官方 API 或可靠第三方 feed 的账号
- 小红书、知乎、抖音等需要登录态、浏览器态、反爬绕行的平台
- Discord 私有频道，除非你有明确授权的 bot

这些平台后续可以接，但适合放在第二阶段。

## 文件分别是什么

这个功能主要用到几类文件：

- `config/kol_watchlist.yaml`：你的本地关注列表。每台电脑都可以不同。不要提交到 GitHub。
- `config/kol_watchlist.yaml.bak`：每次修改关注列表前自动备份的旧版本。
- `config/kol_watchlist.example.yaml`：公开示例配置，可以给同事参考。
- `config/kol_watchlist.recipes.yaml`：平台接入样例集合，用来查“某个平台要怎么填”。
- `reports/kol_watchlist/`：每次运行生成的报告。
- `skills/kol-watchlist-briefing/SKILL.md`：给 Codex 看的操作规则，让你可以用自然语言说“把这个频道加进去”。

## 第一次使用

在项目根目录运行：

```bash
python -X utf8 -m scripts.kol_watchlist.cli init
```

这会做一件事：如果 `config/kol_watchlist.yaml` 不存在，就从示例文件复制一份出来。

然后检查当前电脑是否准备好：

```bash
python -X utf8 -m scripts.kol_watchlist.cli doctor
```

你会看到类似这样的信息：

- 当前关注了几个源
- 每个源是否能被当前工具识别
- 这台电脑还缺什么配置
- 哪些东西不能提交，比如 token、cookie、本地数据库路径

## 查看当前关注列表

```bash
python -X utf8 -m scripts.kol_watchlist.cli list
```

输出会列出：

- 平台
- 显示名称
- 优先级
- 主题标签
- 每次抓取数量
- 是否做全文或备注增强

## 添加一个 RSS 来源

适用于博客、Newsletter、Substack、GitHub Atom、RSSHub 等。

```bash
python -X utf8 -m scripts.kol_watchlist.cli add-rss "https://example.com/feed.xml" --display-name "Example Feed" --topics "ai, markets"
```

常用参数：

- `--display-name`：你希望报告里显示的名字。
- `--priority`：优先级，可选 `low`、`medium`、`high`。
- `--topics`：主题标签，用英文逗号隔开。
- `--fetch-limit`：每次最多取多少条。
- `--enrichment-level`：增强级别，当前常用 `metadata`。

添加 GitHub releases 也用这个命令。例如：

```bash
python -X utf8 -m scripts.kol_watchlist.cli add-rss "https://github.com/unclecode/crawl4ai/releases.atom" --display-name "unclecode/crawl4ai Releases" --priority high --topics "ai, developer-tools, crawler, fulltext" --source-mode atom
```

## 添加 YouTube 频道

最稳定的是使用 YouTube channel ID：

```bash
python -X utf8 -m scripts.kol_watchlist.cli add-youtube "https://www.youtube.com/channel/CHANNEL_ID" --display-name "Channel Name" --topics "ai, video"
```

也可以直接传 channel ID：

```bash
python -X utf8 -m scripts.kol_watchlist.cli add-youtube "CHANNEL_ID" --display-name "Channel Name"
```

如果你给的是 `@handle` 页面，工具会尝试解析 channel ID。解析失败时，会提示你提供 channel ID 或 feed URL。

YouTube 频道的官方 RSS 格式是：

```text
https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID
```

## 添加小宇宙播客

推荐给播客主页 URL：

```bash
python -X utf8 -m scripts.kol_watchlist.cli add-xiaoyuzhou "https://www.xiaoyuzhoufm.com/podcast/PODCAST_ID" --display-name "Podcast Name" --topics "macro, ai"
```

如果你只有单集 URL，也可以先给单集：

```bash
python -X utf8 -m scripts.kol_watchlist.cli add-xiaoyuzhou "https://www.xiaoyuzhoufm.com/episode/EPISODE_ID" --display-name "Podcast Name"
```

工具会把它记录为小宇宙来源。运行时 provider 会尝试从单集解析到所属播客。

小宇宙默认使用 `episode_notes` 增强，也就是尽量读取单集 shownotes。注意：这还不是音频转写；如果节目没有文字稿，就只能拿到页面上公开的节目说明和时间轴。

## 添加微信公众号来源

微信公众号目前推荐走 We-MP-RSS 本地数据库。

你需要先在自己的电脑上运行 We-MP-RSS，并让它已经抓到文章。然后把数据库路径配置到本地环境或 `config/kol_watchlist.yaml`。

如果只想关注其中几个公众号，可以用 `include_mp_names`。例如：

```yaml
- platform: we_mp_rss
  display_name: Selected WeChat Accounts
  db_path: C:/path/to/we_mp_rss.db
  include_mp_names:
    - 赛博禅心
    - 清科研究
  priority: high
  topics: [ai, investing, macro]
  fetch_limit: 20
  enrichment_level: fulltext
  source_mode: local_sqlite
```

这类本地路径不要提交到 GitHub，也不要发到报告正文里。

## 添加 B站 UP 主

当前推荐先用 RSSHub。

你需要知道 UP 主 UID。然后使用 RSSHub 的动态或视频 feed：

```text
https://rsshub.app/bilibili/user/dynamic/UID
https://rsshub.app/bilibili/user/video/UID
```

添加命令示例：

```bash
python -X utf8 -m scripts.kol_watchlist.cli add-rss "https://rsshub.app/bilibili/user/dynamic/UID" --display-name "B站 UP 主名" --topics "ai, tech" --source-mode rsshub
```

RSSHub 是第三方服务，公共实例可能限流或不可用。如果要稳定运行，建议以后自建 RSSHub。

## 添加 Telegram 公开频道

公开频道也可以先用 RSSHub：

```text
https://rsshub.app/telegram/channel/CHANNEL_USERNAME
```

添加示例：

```bash
python -X utf8 -m scripts.kol_watchlist.cli add-rss "https://rsshub.app/telegram/channel/CHANNEL_USERNAME" --display-name "Telegram Channel" --topics "ai, markets" --source-mode rsshub
```

私有 Telegram 群或频道不适合用这个方式。

## 手动跑一版报告

开发阶段推荐 dry-run：

```bash
python -X utf8 -m scripts.kol_watchlist.cli run --lookback-hours 24 --format md,json --dry-run
```

`--dry-run` 的意思是：生成报告，但不把这些内容标记为“已经看过”。

如果你想正式运行，并让下次不再重复出现同一批内容：

```bash
python -X utf8 -m scripts.kol_watchlist.cli run --lookback-hours 24 --format md,json
```

报告会生成在：

```text
reports/kol_watchlist/<运行时间>/
```

常看两个文件：

- `report.md`：人读的 Markdown 报告。
- `report.json`：给后续程序处理的结构化结果。

## 怎么理解报告排序

当前 MVP 的重要性排序主要看这些因素：

- 关注对象的优先级：`high` 会更靠前。
- 是否命中你配置的主题：比如 `ai`、`macro`、`developer-tools`。
- 发布时间是否足够新。
- 平台有没有 engagement 信号，比如播放量、评论数。
- 内容类型，比如视频、播客、文章。
- 是否有全文、shownotes、评论等增强内容。
- 来源稳定性，比如官方 RSS 比临时抓取更可靠。

这不是完美的智能判断，但比单纯时间线更接近“我最该先看什么”。

## 每天自动运行

稳定后有几种方式：

- Codex app 的自动化/心跳任务。
- Windows Task Scheduler。
- macOS/Linux 的 cron。
- 接入已有 daily-newsletter pipeline。

开发阶段建议先手动跑，等关注源稳定后再定时。

## 迁移给同事

同事拿到项目后按这个顺序：

1. 安装依赖。
2. 运行 `python -X utf8 -m scripts.kol_watchlist.cli init`。
3. 运行 `python -X utf8 -m scripts.kol_watchlist.cli doctor`。
4. 添加自己的关注源。
5. 运行 `python -X utf8 -m scripts.kol_watchlist.cli run --dry-run`。

不要直接复制你的：

- `config/kol_watchlist.yaml`
- cookie
- token
- 浏览器登录态
- 本地数据库
- `reports/`
- `data/`

如果要共享一个公共模板，修改 `config/kol_watchlist.example.yaml` 或另建公开模板；真实关注列表仍然放在每个人自己的 `config/kol_watchlist.yaml`。

## 常见问题

**为什么每次修改配置前要备份？**

因为关注列表会越来越长，也可能包含本地路径。一旦误改，`config/kol_watchlist.yaml.bak` 可以帮你回到上一个版本。

**为什么不把真实关注列表提交到 GitHub？**

真实关注列表可能包含本地路径、私有 RSS、公司内部源，甚至未来可能关联 token。默认不提交更安全。

**RSSHub 和 MediaCrawler 是一类东西吗？**

不是。RSSHub 更像“把网页或平台公开内容转成 RSS 的路由服务”；MediaCrawler 更像“用浏览器态或登录态抓平台内容的采集器”。前者更适合稳定订阅，后者更适合低频探索。

**能保证每条更新都抓到吗？**

官方 RSS、Atom、本地数据库这类来源更接近可追踪。登录态抓取、公共搜索、反爬平台不能保证每条都抓到。如果必须完整覆盖，优先找官方 API、官方 RSS、邮件订阅、本地数据库、平台通知 webhook 或自建稳定抓取服务。

**摘要是怎么来的？**

当前摘要主要来自来源自带的 description、RSS 内容、小宇宙 shownotes、We-MP-RSS 本地正文。还不是统一 LLM 总结。后续可以加“全文/字幕 -> LLM 摘要 -> 重点提炼”的统一 summarizer。

## 给 Codex 的自然语言例子

你可以直接这样说：

- “列出我现在关注了哪些源。”
- “跑一版 KOL briefing。”
- “把这个 RSS 加进去：URL 是……”
- “把这个 YouTube 频道加到 KOL watchlist：……”
- “新增这个小宇宙播客：……”
- “帮我检查这台电脑接 KOL watchlist 还缺什么配置。”
- “把 we-mp-rss 里的赛博禅心和清科研究设为 high priority。”

Codex 应该优先使用 `scripts.kol_watchlist.cli` 的 `init`、`list`、`doctor`、`add-*`、`run` 命令来完成这些操作。
