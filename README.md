# fanqie-dl

番茄小说（fanqienovel.com）下载器，基于**服务端渲染(SSR)正文 + 字体混淆解密**实现。

## ✨ 特点

- 🚀 纯 HTTP 请求，无需浏览器（1~2 秒/章）
- 📖 目录通过官方 API 获取，无需登录、无需签名
- 🔓 字体混淆（PUA 私用区字符）自动解密还原
- 📦 输出整本 TXT，支持章节范围、断点续跑（已写文件）

## 工作原理

1. **目录**：`GET /api/reader/directory/detail?bookId={id}&aid=1967` → 章节列表（含付费标记）
2. **正文**：`GET /reader/{item_id}` 的 SSR HTML 中提取正文（多数免费书直接含全文）
3. **解密**：页面把正文中的汉字替换为私用区混淆字符，通过字体映射表 `fanqie/font_map.py` 还原

> ⚠️ 部分书籍/章节 SSR 只返回预览（内容 <100 字），会被标记跳过。付费章节（needPay=1）不在本工具支持范围。

## 安装

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 使用

```bash
# 下载全书
.venv/bin/python main.py 7646230028388142104

# 下载 1~10 章
.venv/bin/python main.py 7646230028388142104 --start 1 --end 10

# 支持分享链接（自动提取 book_id）
.venv/bin/python main.py "https://changdunovel.com/ug/pages/book-share?book_id=7646230028388142104&..."

# 仅列出章节
.venv/bin/python main.py 7646230028388142104 --list

# 指定输出目录
.venv/bin/python main.py 7646230028388142104 --out /path/to/books

# 调节请求间隔（反封控节奏，默认 1~3 秒随机）
.venv/bin/python main.py 7646230028388142104 --delay-min 2 --delay-max 5

# 查看书籍/章节元数据（书名/作者/封面/简介/标签/总字数/阅读量/状态/更新时间/章节上传时间）
.venv/bin/python main.py 7646230028388142104 --meta

# 搜索选书下载一条龙（官方 App 接口，无需签名）
.venv/bin/python main.py --search 十日终焉
.venv/bin/python main.py --search 你写的小说 --pick 1        # 直接下载第1个结果
.venv/bin/python main.py --search 你写的小说 --pick 1 --end 10   # 只下前10章

# 下载时保存封面图
.venv/bin/python main.py 7646230028388142104 --cover
```

输出：`books/《书名》.txt`（含书籍信息头 + 每章字数/更新时间），
`--cover` 时额外保存 `《书名》_cover.jpg` 封面。

## 🔁 冗余设计（每步都有备用方案）

| 环节 | 主方案 | 备用方案 |
|---|---|---|
| 搜索 | `novel.snssdk.com`（官方 App 接口） | `api-lf.fanqiesdk.com`（官方 SDK 网关），自动回退 |
| 目录 | `/api/reader/directory/detail` | 目录页 SSR 解析（原项目同款选择器） |
| 书籍信息 | `/api/book/info` | 目录页 SSR 解析（标题/作者/标签/字数/状态/简介/封面） |
| 章节正文 | 章节页 SSR + 字体解密 | 内容不足时标记跳过，不中断 |
| 章节字数 | 章节页 SSR `chapterWordNumber` | 下载正文时顺带获取，零额外请求 |

> ⚠️ 搜索接口是番茄 App 内部接口（社区发现，非官方文档），随时可能加签名或下线；
> 失效时请改用已知书 ID 直接下载。

## 📊 可获取的元数据（与 APP 版一致）

| 数据 | 来源 |
|---|---|
| 书名 / 作者 / 封面 | `/api/book/info` |
| 简介（完整 abstract） | `/api/book/info` |
| 标签（都市/校花/1v1 等） | `/api/book/info` → categoryV2 |
| 总字数 / 阅读量 | `/api/book/info` |
| 连载状态 / 最新章节 / 最近更新 | `/api/book/info` |
| 章节上传时间 | `/api/reader/directory/detail` → firstPassTime |
| 章节字数 | 章节页 SSR → chapterWordNumber（下载时顺带获取） |

用 `--meta` 即可快速查看一本书的全部元数据，无需下载正文。

## 🛡️ 反封控设计（分层防御）

| 检测层 | 对应措施 |
|---|---|
| TLS 指纹 | `curl_cffi impersonate="chrome"` 模拟浏览器 TLS 握手 |
| User-Agent | 8 组真实桌面 UA 池随机轮换 |
| 请求头 | 完整浏览器头：Accept / Accept-Language / Sec-Fetch-* / Sec-CH-UA 等 |
| 频率检测 | 每次请求前随机延迟（默认 1~3s，可调 `--delay-min/--delay-max`） |
| 限流(429/403) | 指数退避重试 + 尊重 `Retry-After` 响应头 |
| Cookie 检测 | 复用 Session + 匿名 `novel_web_id` 访客 cookie |
| 行为特征 | Referer 翻页链（本章 Referer 指向上一章，模拟真实阅读） |

> ⚠️ 任何伪装都无法 100% 保证不被封控。请控制下载频率、只下载免费章节、
> 勿用于商用或滥用，风险自负。

## 常见问题

- **连接超时/卡住**：若系统 IPv6 链路异常，可在 `/etc/hosts` 固定 IPv4：
  ```
  163.181.201.184 fanqienovel.com
  163.181.201.185 fanqienovel.com
  ```
- **章节被跳过**：该章为预览或付费章节。

## 免责声明

本工具仅供个人学习 Python 爬虫与网页处理技术使用，请勿用于任何商业或非法用途。
使用前请确认符合相关法律法规及网站使用政策，由此产生的一切责任由使用者承担。

## 致谢

- 字体解密思路：[RChow 博客](https://www.cnblogs.com/ruichow/p/18209338)
- 映射表参考：[fanqienovel-downloader](https://github.com/ying-ck/fanqienovel-downloader) (AGPL-3.0)、[fanqienovel-decryptor](https://github.com/romcere/fanqienovel-decryptor)

## 许可证

**AGPL-3.0 及附加条款：禁止任何形式的商业使用。**
详见 [LICENSE](LICENSE)。
