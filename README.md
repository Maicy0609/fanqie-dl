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
```

输出：`books/《书名》.txt`

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
