# fanqie-dl

番茄小说（fanqienovel.com）下载器：SSR 正文抓取 + 字体混淆解密 + 官方 App 接口搜索。

## 功能

- 下载：书 ID / 分享链接（自动清洗提取 ID），整本或指定章节范围
- 搜索：官方 App 接口（无需签名），列出完整书名，选书即下载
- 批量下载：文本文件，一行一个链接/ID
- 元数据：书名/作者/封面/简介/标签/总字数/阅读量/状态/最新章节/最近更新/章节上传时间/章节字数
- 封面：每本书独立文件夹内保存《书名》_cover.jpg
- 交互菜单：1.下载 2.搜索 3.批量下载 4.设置（Ctrl+C 退出）
- 设置持久化：请求间隔、默认保存目录（config.json）

## 安装

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 使用

```bash
# 交互模式（菜单）
.venv/bin/python main.py

# 命令行模式
.venv/bin/python main.py 7646230028388142104
.venv/bin/python main.py 7646230028388142104 --start 1 --end 10 --cover
.venv/bin/python main.py --search 你写的小说
.venv/bin/python main.py --search 你写的小说 --pick 1 --end 10
.venv/bin/python main.py 7646230028388142104 --meta
.venv/bin/python main.py 7646230028388142104 --list
```

输出结构（每本书一个文件夹）：

```
books/
└── 你写的小说，给我惹了不少麻烦呢/
    ├── 你写的小说，给我惹了不少麻烦呢.txt
    └── 你写的小说，给我惹了不少麻烦呢_cover.jpg
```

## 工作原理

1. 搜索：`novel.snssdk.com/.../search/v1/`（备：`api-lf.fanqiesdk.com`），无需签名
2. 目录：`/api/reader/directory/detail?bookId={id}&aid=1967`
3. 书籍信息：`/api/book/info?bookId={id}`
4. 正文：章节页 SSR HTML + `chapterWordNumber`（章节字数）
5. 解密：私用区混淆字符通过 `fanqie/font_map.py`（362 条映射）还原

## 冗余设计

| 环节 | 主方案 | 备用方案 |
|---|---|---|
| 搜索 | novel.snssdk.com（官方 App 接口） | api-lf.fanqiesdk.com（官方 SDK 网关） |
| 目录 | 目录 API | 目录页 SSR 解析 |
| 书籍信息 | /api/book/info | 目录页 SSR 解析 |
| 章节正文 | 章节页 SSR + 字体解密 | 内容不足标记跳过，不中断 |

## 反封控

- TLS 指纹：curl_cffi impersonate="chrome"
- 请求头：完整浏览器头（UA 轮换、Sec-Fetch-*、Accept-Language）
- 频率：随机延迟（config.json 可调），失败指数退避 + 尊重 Retry-After
- 会话：Session 复用 + 匿名 novel_web_id cookie
- 行为：Referer 翻页链

## 注意事项

- 搜索接口为番茄 App 内部接口（社区发现），随时可能加签名或下线；失效时可改用书 ID 直接下载
- 部分书籍/章节 SSR 只返回预览（内容 <100 字）会被标记跳过；付费章节不支持
- 仅供个人学习研究，禁止商用，风险自负

## 许可证

AGPL-3.0 及附加条款（禁止任何形式的商业使用）。详见 LICENSE。

## 连载下载更新（菜单 [3]）

自动扫描下载目录中标记为「连载中」的书籍，支持多选（半角逗号分隔，回车=全部），
只下载新章节并**追加到旧文件末尾**。

触发规则（必须同时满足，否则拒绝更新）：
1. 已下载章节**从第1章开始且连续**（中间缺章需先用 [1] 下载补全）
2. **未下载到最后一章**（已是最新则提示无需更新）

### 下载记录 JSON

每本书下载时会在其文件夹内生成同名 `.json` 记录：

```json
{
  "book_id": "7646230028388142104",
  "title": "你写的小说，给我惹了不少麻烦呢",
  "status": "连载中",
  "downloaded_orders": [1, 2, 3],
  "updated_at": "2026-08-04 05:26:16"
}
```

- 普通下载：全量下载，记录已下载章节序号
- 连载更新：按记录序号定位最新章节，只下增量，追加到 TXT 末尾
- 书籍状态随每次下载/更新实时刷新（连载中/已完结）
