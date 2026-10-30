<div align="center">

<img src="assets/images/icon.png" alt="NekoClash" width="88">

# NekoClash

[FlClash](https://github.com/chen08209/FlClash) 的个人 Android 分支：内核与功能保持 FlClash 原样，界面换成 [NekoBox](https://github.com/MatsuriDayo/NekoBoxForAndroid) 的样子。

[English](README.md) · **简体中文**

[![License](https://img.shields.io/github/license/xikijinise/NekoClash?style=flat-square)](LICENSE)
[![Upstream](https://img.shields.io/badge/upstream-chen08209%2FFlClash-934172?style=flat-square)](https://github.com/chen08209/FlClash)

</div>

> 这是个人维护的非官方分支，只面向 Android。问题请提交到本仓库，不要打扰 FlClash 与 NekoBox 的作者。

## 和 FlClash 的区别

- **NekoBox 的布局**：粉色顶栏，左上角 ☰ 打开侧滑抽屉，取代底部导航栏。抽屉分三组：代理、配置、仪表盘 / 最近请求、实时连接、DNS 查询、资源 / 工具、关于。
- **代理页作为主页**：分组放在顶栏下的粉色标签栏里，节点是单列卡片，正在使用的节点左侧有粉色竖条，协议名为粉色。
- **NekoBox 的连接按钮与统计栏**：底部圆形按钮使用 NekoBox 的纸飞机图标；连接后底部滑出统计栏，显示上传与下载速度，点击即可测试连接延迟。
- **粉色主题**：默认主题色为 NekoBox 的 `#FB7299`。
- **独立的包名** `com.nekoclash`：可以与 FlClash 同时安装，订阅与设置互不影响。

内核（mihomo）、订阅、规则、覆写、TUN、分应用代理、备份等功能都来自 FlClash，没有改动。

## 安装

在 [Releases](https://github.com/xikijinise/NekoClash/releases/latest) 下载 `NekoClash-版本号-android-arm64-v8a.apk`，适用于绝大多数 Android 手机，
可以和 FlClash 同时安装。也可以访问 [NekoClash 网站](https://xikijinise.github.io/NekoClash/)。

签名证书 SHA-256：`0d50e1fe2df180097d95df86fce31d378d6b3a8914393c2930675b4767eca247`

## 从源码构建

需要 [Flutter](https://docs.flutter.dev/get-started/install) 3.47、[Go](https://go.dev/dl/) 1.27，以及带 NDK 的 Android SDK。

```bash
git clone --recursive https://github.com/xikijinise/NekoClash.git
cd NekoClash
flutter pub get
flutter build apk --release --target-platform android-arm64 --dart-define=APP_ENV=stable
```

安装包输出到 `build/app/outputs/flutter-apk/app-release.apk`。Go 内核会在构建过程中一并编译。

- 不加 `--dart-define=APP_ENV=stable` 时，界面右上角会显示“PRE”。
- **签名**：把密钥放在 `android/app/keystore.jks`，并在 `android/local.properties` 里写入 `storePassword`、`keyAlias`、`keyPassword`，即可用自己的密钥签名。没有密钥时使用本机的调试密钥签名，换一台电脑构建的版本将无法覆盖安装。
- debug 构建的包名是 `com.nekoclash.dev`，与正式版互不覆盖。

## 使用

**通过链接导入配置。** 打开下面格式的链接，即可导入订阅。`clashmeta://` 和 `flclash://` 开头的链接同样可用。

```text
clash://install-config?url=<经过 URL 编码的订阅链接>
```

**Android 自动化。** Tasker、MacroDroid 等应用可以用下面的 Action 启动 Activity，从而启动、停止或切换代理：

```text
com.nekoclash.action.START
com.nekoclash.action.STOP
com.nekoclash.action.TOGGLE
```

在电脑上也可以通过 adb 触发：

```bash
adb shell am start -a com.nekoclash.action.TOGGLE
```

## 与上游同步

本分支不整体合并 FlClash 的更新，只挑选修复与内核更新单独移植。目前基于 FlClash v0.9.1，并移植了 v0.9.2 中的
“打开应用不再重新加载正在运行的 VPN”修复与 mihomo v1.19.33 内核。

## 致谢与许可证

- [FlClash](https://github.com/chen08209/FlClash)：本项目的全部功能与代码基础，作者 chen08209。
- [NekoBox for Android](https://github.com/MatsuriDayo/NekoBoxForAndroid)：界面布局、配色与连接按钮图标的来源。

NekoClash 与上述两个项目一样，以 [GPL-3.0 协议](LICENSE)发布。
