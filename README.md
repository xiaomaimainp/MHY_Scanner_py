# MHY_Scanner_py

米哈游扫码登录器（Python 版），基于 PyQt6 的米哈游游戏账号扫码登录工具。

来源与参考：

- C++ 侧逻辑对齐 [loqwe/ErYouScanner](https://github.com/loqwe/ErYouScanner)（v2.0.2，原 `loqwe/MHY_Scanner2`）
- 原始项目 [DSVVA/MHY_Scanner](https://github.com/DSVVA/MHY_Scanner)（原 `Theresa-0328/MHY_Scanner`）
- 本仓库 fork 自 `MR-LIYA/MHY_Scanner`（该上游仓库现已 404，不可访问）

- **当前版本**：`2026.10.22`（版本号即更新日期，统一定义于 `utils/update.py` 的 `VERSION`）
- **项目主页**：<https://github.com/xiaomaimainp/MHY_Scanner_py>

> 自用分支，**不做自动更新**：菜单「设置 → 打开项目主页」直接跳转仓库页面，不下载、不安装安装包。
> 版本号按更新日期命名（`YYYY.MM.DD`），与原 fork 的 `1.0.x` 迭代号区分；每次改动代码即改为当天日期。

首次运行需等待片刻以生成配置文件。

---

## 功能特性

- **扫码登录**：基于 hoyolab Passport API，米游社 APP 扫码确认后直接返回 Token
- **短信登录**：手机号 + 验证码登录，触发风控时自动弹出极验 v4 滑块
- **Cookie 登录**：粘贴 SToken Cookie 直接登录（`stuid` + `stoken` + `mid`）
- **B站崩坏3登录**：BiliBili 服账号密码登录
- **Cookie 刷新**：抖音 / B站 Cookie 刷新（设置 → 刷新Cookie）
- **屏幕扫描**：监视屏幕中出现的游戏内二维码，一键确认登录
- **直播流扫描**：从 B站 / 抖音直播间实时检测二维码并自动登录
- **多账号管理**：多账号存储、默认账号标记、服务器与备注编辑
- **四种游戏**：崩坏3、原神、星穹铁道、绝区零
- **双服务器**：官服 + BiliBili 服（崩坏3）
- **开关项**：自动二次确认（默认开）、登录后自动退出（默认关）、窗口置顶（默认开）、监视直播间时联动监视屏幕（默认关）
- **内置配置编辑器**：JSON 语法高亮、行号、智能缩进、缩放

---

## 支持的游戏与服务器

| 游戏 | 官服 | BiliBili 服 |
| ------ | :----: | :-----------: |
| 崩坏3 (Honkai Impact 3rd) | ✅ | ✅ |
| 原神 (Genshin Impact) | ✅ | ❌ |
| 星穹铁道 (Honkai: Star Rail) | ✅ | ❌ |
| 绝区零 (Zenless Zone Zero) | ✅ | ❌ |

---

## 系统要求

| 项目 | 要求 |
| ------ | ------ |
| 操作系统 | Windows 10 21H2 及以上（主要测试环境） |
| Python | 3.8+ |
| 内存 | 建议 4GB+ |
| FFmpeg | 直播流扫描需要（加入 PATH，Win10 21H2+ 通常自带） |
| VC++ Redist | 运行打包 exe 需要，[下载地址](https://aka.ms/vs/17/release/vc_redist.x64.exe) |

---

## 安装（源码运行）

```bash
git clone https://github.com/xiaomaimainp/MHY_Scanner_py.git
cd MHY_Scanner_py
pip install -r requirements.txt
python main.py
```

**可选依赖**：

- `curl_cffi`：模拟真实 TLS 指纹，绕过 WAF `-3503` 风控，提高扫码轮询成功率
- `PyQt6-WebEngine`：极验滑块验证与 Cookie 刷新需要

```bash
pip install curl_cffi PyQt6-WebEngine
```

---

## 使用说明

### 扫码登录

1. 点击「扫码登录」，选择游戏和服务器
2. 用米游社 APP 扫描屏幕上显示的二维码
3. 手机点击「确认登录」，Token 自动获取并保存到账号列表

> 基于 hoyolab Passport API（`passport-api.miyoushe.com`），确认后 Token 通过 `Set-Cookie` 直接返回，无需 ticket 兑换。

### 短信登录

1. 点击「短信登录」，输入手机号后发送验证码
2. 若触发风控（`-3101`），会自动弹出极验滑块，完成验证后自动重发验证码
3. 输入收到的验证码即可登录

### Cookie 登录

1. 点击「Cookie 登录」，粘贴 `stuid=xxx; stoken=xxx; mid=xxx`
2. 选择游戏和服务器，点击登录

### B站崩坏3 登录

1. 点击「B站崩坏3」，输入 B站 账号密码
2. 登录成功后账号自动保存

### 屏幕 / 直播流扫描

1. 右侧选择平台并填写直播间号（留空则扫描屏幕）
2. 点击「开始监视」
3. 游戏内打开扫码登录界面，程序自动检测并确认

### 账号管理

| 操作 | 方式 |
| ------ | ------ |
| 设为默认账号 | 右键账号 → 设为默认（左侧圆点标记） |
| 编辑备注 | 双击备注列 |
| 编辑 MID | 右键 → 编辑 MID |
| 添加/修改/移除默认账号 | 右键或顶部账号管理 |
| 删除账号 | 右键 → 删除账号 |

---

## 配置说明

配置文件位于 `Config/` 目录。

### config.json（应用设置）

| 配置项 | 类型 | 默认值 | 说明 |
| ------ | ---- | ------ | ---- |
| `auto_exit` | bool | `true` | 登录成功后自动退出 |
| `auto_login` | bool | `true` | 自动二次确认登录 |
| `auto_start` | bool | `false` | 监视直播间时联动监视屏幕 |
| `always_on_top` | bool | `true` | 窗口始终置顶 |
| `last_platform` | int | `0` | 上次使用的直播平台 |
| `room_id` | string | `""` | 上次输入的直播间号 |
| `log_output_mode` | string | `"console"` / `"file"` | 日志输出模式 |
| `log_level` | int | `0` / `2` | 0=DEBUG, 1=INFO, 2=WARN, 3=ERROR |
| `editor_font_cn` | string | `"Microsoft YaHei"` | 编辑器中文字体 |
| `editor_font_en` | string | `"Consolas"` | 编辑器英文字体 |
| `editor_font_size` | int | `12` | 编辑器字号 |

> 源码运行默认 `console` + `0`（DEBUG），打包后默认 `file` + `2`（WARN）。

### userinfo.json（账号数据）

格式兼容 C++ 版 MHY_Scanner。设置环境变量 `MHY_USERINFO_PATH` 指向 C++ 项目的 `userinfo.json` 即可数据互通：

1. `Win + R` → `sysdm.cpl` → 高级 → 环境变量
2. 用户变量新建 `MHY_USERINFO_PATH`，值为完整路径（如 `D:\MHY_Scanner\Config\userinfo.json`），重启程序生效

`type` 字段映射：`"官服"` → 官服/原神，`"崩坏3B服"` → B服/崩坏3。

---

## 项目结构

```text
MHY_Scanner/
├── main.py                     # 程序入口（版本号统一管理）
├── requirements.txt            # 依赖清单
├── api/
│   ├── api.py                  # 米哈游 API（扫码 / 短信登录 / 游戏内二维码 / Token 交换）
│   └── bsgamesdk.py            # B站 SDK（崩坏3 B服 账号密码登录）
├── core/
│   ├── config.py               # 配置管理（单例，兼容 C++ userinfo.json）
│   └── logger.py               # 日志系统（控制台 / 文件，多标签分类）
├── scanner/
│   ├── scanner.py              # 屏幕 + 直播流二维码扫描器
│   └── livestream.py           # 直播流获取（B站 / 抖音）
├── ui/
│   ├── main_window.py          # 主窗口（账号管理 / 扫描控制 / 菜单栏）
│   ├── login_window.py         # 登录窗口（4 种登录方式 Tab）
│   ├── geetest_verify.py       # 极验 v4 滑块验证对话框
│   ├── account_manager.py      # 账号管理器
│   ├── add_account_dialog.py   # 手动添加账号
│   ├── config_editor.py        # 内置配置编辑器
│   └── cookie_refresh_dialog.py # Cookie 刷新（抖音/B站）
├── utils/update.py             # 更新检查
├── hooks/                      # PyInstaller 打包钩子
├── Config/                     # 配置文件（自动生成）
└── log/                        # 日志目录（自动生成）
```

---

## 编译打包

```bash
pip install pyinstaller
pyinstaller --onefile --windowed \
    --name="MHY_Scanner" \
    --icon=icons/app.png \
    --add-data="Config;Config" \
    --add-data="icons;icons" \
    --hidden-import=curl_cffi \
    --hidden-import=pyzbar \
    --hidden-import=PIL \
    --additional-hooks-dir=hooks \
    main.py
```

- `curl_cffi` 建议打包以提升扫码成功率
- `hooks/` 确保子模块被正确收集
- 打包后日志默认输出到 `log/` 而非控制台
- 运行 exe 需安装 VC++ Redist；直播流扫描需 FFmpeg 在 PATH

---

## 注意事项

1. **米游社 APP**：扫码登录需手机安装米游社 APP 并登录目标账号
2. **B站崩坏3**：仅支持崩坏3 BiliBili 服
3. **直播流扫描**：需安装 FFmpeg，且非免流直播间
4. **网络环境**：需可正常访问米哈游 API
5. **配置编辑器**：修改前建议备份，格式错误可能导致程序异常

### WAF 风控

- 米哈游 API 有 WAF 风控（错误码 `-3503`）
- **扫码登录**（自生成二维码）走 hoyolab Passport API，策略较宽松、轮询稳定
- **屏幕扫描**（游戏内二维码）走 hk4e-sdk 端点，仍可能触发
- 推荐安装 `curl_cffi` 模拟真实 TLS 指纹；轮询间隔已加 0~500ms 随机抖动

### 日志

- 位于 `log/`，单文件上限 100KB，自动滚动归档，保留 7 天
- 源码运行输出控制台（DEBUG），打包后输出文件（WARN）
- 日志已脱敏：`stoken` / `ltoken` / `mid` / 各类 token / 手机号 / 邮箱统一打码，`uid` / `ticket` 保留便于排查

---

## 依赖清单

| 依赖 | 最低版本 | 用途 |
| ------ | ------- | ------ |
| PyQt6 | ≥6.4.0 | GUI 框架 |
| PyQt6-WebEngine | ≥6.4.0 | 极验滑块验证、Cookie 刷新浏览器内核 |
| opencv-python | ≥4.8.0 | 图像处理与二维码检测 |
| numpy | ≥1.24.0 | 数值计算 |
| requests | ≥2.31.0 | HTTP 请求 |
| Pillow | ≥10.0.0 | 图像处理 |
| mss | ≥9.0.1 | 屏幕截图 |
| cryptography | ≥41.0.0 | RSA 加密 |
| python-dateutil | ≥2.8.0 | 日期处理 |
| qrcode | ≥7.4.0 | 二维码生成 |
| ffmpeg-python | — | 视频流处理 |
| pyzbar | ≥0.1.9 | 二维码解码（优先使用） |

**可选**：`curl_cffi`（模拟真实 TLS 指纹绕过 WAF）。

---

## 更新日志

> 版本号即更新日期，按改动当天填写；无迭代版本号。

### 2026-10-22

- **极验升级 v4**：改用 `static.geetest.com/v4/gt4.js`（`/static/js/gt4.js` 实测 404，会导致窗口空白）；v4 配置必须带 `userInfo:{"session_id":...}`，否则服务端回 `-3102 图片验证码失败`
- **极验渲染**：采用 `product:'bind'` + `showCaptcha()`，并加看门狗——2.5 秒内无可见极验元素时自动回退 `popup` + `nativeButton`，保证窗口不空白
- **结果回传**：QtWebEngine 下重写 `QWebEnginePage.acceptNavigationRequest` 拦截 `geetest://`（未注册 scheme 不会触发 `urlChanged`，结果会永远收不到）
- **登录身份修正**：短信登录改用米游社身份 `app_id=bll8iq97cem8`（原游戏客户端 `c76ync6mutq8` 只下发 `v2_` 短期 token，导致扫码二次确认恒 `-100`）
- **日志脱敏**：`stoken` / `mid` / 手机号等统一打码
- **配置保存**：原子写（临时文件 + `os.replace`）+ `RLock`，对齐 C++ `QSaveFile`
- **版本与更新**：版本号改为日期命名（`2026.10.22`）；移除自动更新与安装包下载，菜单改为「打开项目主页」跳转仓库；仓库地址统一改为 `xiaomaimainp/MHY_Scanner_py`
- `v2_token → stoken` 兑换实验代码移入 `api/api_test.py`，已加入 `.gitignore`

### 2026-07

- **直播流扫描**：改用 FFmpeg 子进程管道读帧（对齐 C++ `avformat_open_input`），按平台注入 HTTP 头（B站缺 `Referer`/`Origin` 会 403）；保留 `cv2.VideoCapture` 回退
- **官服扫码**：补齐 `x-rpc-app_id` / `x-rpc-device_id` 头
- **自动监视语义修正**：原「启动时自动监视屏幕」改为「监视直播间时联动监视屏幕」，重启不再自动触发

### 2026-06

- 新增 Cookie 刷新（抖音直接刷新，B站需扫码登录提取登录态）
- 验证码暂不支持 HarmonyOS 及 iOS

---

## 开源协议

本项目仅供学习交流使用，请勿用于非法用途。

## 参考项目

- [loqwe/ErYouScanner](https://github.com/loqwe/ErYouScanner) — C++ 侧对齐对象，二游扫码 v2.0.2（原 `loqwe/MHY_Scanner2`）
- [DSVVA/MHY_Scanner](https://github.com/DSVVA/MHY_Scanner) — 原始项目（原 `Theresa-0328/MHY_Scanner`）
