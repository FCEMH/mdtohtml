# MD2HTML

**一个linux系统上将markdown转化成html的小工具**

- 支持：**单文件、文件夹、gpt对话** 转换
- 原理：逐文档使用 Pandoc AST 解析；按来源文件目录解析资源和链接，再合并正文。原 Markdown、图片和 `.obsidian` 始终只读。


## 先看成品

打开 [`examples/example_book.html`](examples/example_book.html)，查看示例，不需要服务器。

包含中文多层目录、4 篇笔记、独立来源目录插图、WikiLink、Callout、C++/Python/Bash、矩阵及 MPC 多行公式。全文搜索支持中文短语和 Unicode 规范化；数学字体、图片、CSS、JS、搜索索引都内嵌。

## 从零安装（Ubuntu 22.04 / Python 3.10+）

以下命令在**解压后的项目根目录**执行，不会替换系统 Pandoc：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
# 若只使用 CLI：python -m pip install -e '.[pandoc]'

# 构建机需要 Node.js >=20；先确认本机已有可用版本。
node --version
# 锁文件固定 KaTeX；postinstall 复制 CSS、20 个 WOFF2 字体与本地 SSR 代码。
npm ci

md2html doctor
md2html check tests/fixtures/sample_vault --strict
md2html build tests/fixtures/sample_vault \
  --title 'CAN 与控制学习手册' \
  --strict --report dist/report.json -o dist/example_book.html
```

- 若缺少 `venv`，在 Ubuntu 上由系统管理员安装 `python3-venv`；本工具不自动修改操作系统。
- Pandoc 要求 `>=3.1,<4`，AST API 支持 `1.23–1.24`；实测 **3.9 / API 1.23.1.1**。
- `.[pandoc]`/`.[dev]` 的 `pypandoc_binary` 提供独立二进制，优先于旧系统 Pandoc。
- 也可使用自己安装的兼容版本：`MD2HTML_PANDOC=/absolute/path/pandoc md2html doctor`。
- 如 shell 注入了 ROS 的 `PYTHONPATH`，出现不相关包冲突时使用 `env -u PYTHONPATH python -m pip ...`，不要卸载 ROS 包。
- 源码和 wheel 已包含 KaTeX vendor 资源；普通 CLI 用户无需联网 `npm ci`，只有更新/重新准备资源时才需要它。Node 仍是构建期依赖。

安装依赖可能访问 Python/npm 软件仓库；`check`/`build` **不主动联网，不下载文档引用的远程资源**。

## 图形界面与桌面入口（Linux）

在已建立的项目虚拟环境中安装 GUI 依赖，然后运行：

```bash
.venv/bin/python -m pip install -e '.[gui,pandoc]'
.venv/bin/md2html-gui
```

Linux 还需要 pywebview 可用的 GTK/WebKit 或 Qt 图形后端。安装说明见 [pywebview 官方文档](https://pywebview.flowrl.com/guide/installation.html)。Pandoc、Node 等转换依赖仍按上面的说明准备。

如需从应用菜单启动，在项目根目录运行一次：

```bash
python3 scripts/install_desktop.py
```

脚本从自身位置识别项目目录，默认使用当前项目的 `.venv/bin/md2html-gui`，将生成的 `md2html.desktop` 写到当前用户的应用目录（默认 `~/.local/share/applications`，遵循 `XDG_DATA_HOME`）。随后可在应用菜单中搜索 **MD2HTML**，无需先打开终端激活虚拟环境，也无需 sudo。

仓库中的 `md2html.desktop.in` 是模板，由安装脚本填入本机的启动路径和工作目录；不要直接把模板复制到应用目录。项目复制到另一台电脑后，先在当地重建并安装虚拟环境，再运行脚本。项目位置改变后也需要重新生成桌面入口；重复运行会更新同名启动项。

使用其他安装环境时，可明确指定已安装的启动程序：

```bash
python3 scripts/install_desktop.py --executable /absolute/path/to/md2html-gui
```

`--applications-dir` 可指定其他入口安装目录。脚本在 GUI 启动程序缺失或不可执行时拒绝写入，并给出安装提示。

## 使用自己的笔记

```bash
md2html build '/path/to/课程笔记' -o '/path/to/教材.html'
md2html check '/path/to/课程笔记' --strict --report '/path/to/report.json'
# 可选：明确生成配置；已有文件不覆盖，除非 --force。
md2html init '/path/to/课程笔记'
```

所有命令也支持 `python -m md2html`。路径带空格或中文时使用正常 shell 引号。

### 命令与选项

| 命令                     | 用途                                           |
| ---------------------- | -------------------------------------------- |
| `init INPUT [--force]` | 仅写入 `INPUT/md2html.yml`                      |
| `doctor`               | 一次检查 Python/Pandoc/Node/KaTeX/模板/字体；缺失依赖退出 3 |
| `check INPUT`          | 完整解析、检查引用、公式与最终 HTML；不写 HTML                 |
| `build INPUT`          | 原子写入单 HTML；默认 `./dist/<输入目录名>.html`          |

`build` 和 `check` 接受 `--config`、`--title`、`--theme light|dark|auto`、`--toc-depth 1..6`、`--search/--no-search`、`--offline`、`--strict`、`--report`、`--verbose`；`build` 额外接受 `--output/-o`。

**优先级：显式 CLI > YAML > 默认值。** 不传 `--strict` 时保留 YAML 的 strict 设置。

- 默认排除 `.git`、`.obsidian`、`node_modules`、`dist`、`build`、隐藏文件/目录、符号链接。
- 顺序：显式 `content.order` → 同级 `nav_order` → 自然排序；目录保持为连续组，不把不同目录拆散混排。
- 标题：front matter `title` → 第一个 H1 → 文件名。
- 资源：先来源目录；Wiki 附件再查根目录/配置附件目录/唯一文件名。歧义必须指定路径，**不会随机取第一张**。
- 普通文本双括号标签的标准链接 `[[源码]](URL)` 优先作为普通链接，不再查找名为“源码”的笔记。真正的 `[[笔记]]`、代码和数学保留原语义。
- 安全的 `<a id="...">` / `<a name="...">` 和原生Span/Div自定义ID会转为命名空间锚点；其余原始HTML仍作为文本，不放开脚本。
- 本地图片超链接转为内嵌原图预览；引用的UTF-8 JSON作为只读附件收录，支持查看和下载原始字节，不依赖源文件。**这些JSON内容会随HTML一起分发，请在分享前确认其中没有敏感信息。**
- 所有输出都做离线检查，没有在线模式；`offline` 必须为 `true`。
- 严格模式对失效引用、公式错误、不支持语法等警告拒绝写入成品。禁用原始 HTML 是 `info`，不是内容错误。
- 失败保留上一次 HTML；输入目录内已有非本工具产物的 HTML/JSON 拒绝覆盖；不写隐藏配置目录。

### 可选配置

参考 [`examples/sample_config.yml`](examples/sample_config.yml)。路径相对输入根目录；输出路径相对命令执行目录。

```yaml
version: 1
book:
  title: "课程手册"
content:
  order: ["00_总纲.md", "第一阶段/第2课.md"]
  attachment_dirs: ["assets", "images"]
  skip_draft: true
render:
  theme: auto
  toc_depth: 4
  search: true
  offline: true
  strict: false
```

## 退出码与诊断

| 码 | 意义 |
|---|---|
| 0 | 成功；普通模式可能有警告 |
| 1 | 参数/配置/输出路径或 IO 错误 |
| 2 | 源内容错误，或严格模式内容检查失败 |
| 3 | 运行依赖缺失/版本不兼容 |
| 4 | 转换内部错误/输出完整性验证失败 |

默认终端只汇总INFO类兼容/安全处理，WARNING/ERROR仍逐条显示；`--verbose`展开INFO，`--report`始终保存全部诊断。`md2html --version`确认实际加载版本。

JSON 报告含 `generator/status/exit_code/stats/issues`。每条 Issue 包含类型、源文件、严重性、建议；Pandoc AST 不提供精确行号时 `line=null`，日志标注“位置未知”，不伪造位置。

## 范围与文档

- [架构与安全边界](docs/ARCHITECTURE.md)
- [兼容矩阵与明确降级](docs/COMPATIBILITY.md)
- [排错指南](docs/TROUBLESHOOTING.md)
- [T01–T24 历史验收](docs/ACCEPTANCE.md)
- [0.1.1 真实课程修复记录](docs/REPAIR_0.1.1.md)
- [逐阶段运行记录](docs/DEVELOPMENT_LOG.md)
- [原始需求方案的只读副本](docs/IMPLEMENTATION_PLAN.zh-CN.md)
- [第三方许可](THIRD_PARTY_NOTICES.md)

非目标：Markdown 编辑器、服务器、多页站点、浏览器执行 Python/C++、PDF/EPUB、插件脚本运行环境。P2 的笔记正文嵌入、块引用、Mermaid/Dataview/Graphviz 等会诊断并保留代码/文本/占位，不声称已实现。

MIT License。
