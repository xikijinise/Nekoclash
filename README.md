<div align="center">

<img src="assets/images/icon.png" alt="NekoClash" width="88">

# NekoClash

A personal Android fork of [FlClash](https://github.com/chen08209/FlClash): FlClash's core and features, dressed in
[NekoBox](https://github.com/MatsuriDayo/NekoBoxForAndroid)'s look.

**English** · [简体中文](README_zh_CN.md)

[![License](https://img.shields.io/github/license/xikijinise/NekoClash?style=flat-square)](LICENSE)
[![Upstream](https://img.shields.io/badge/upstream-chen08209%2FFlClash-934172?style=flat-square)](https://github.com/chen08209/FlClash)

</div>

> This is an unofficial, personally maintained fork for Android only. Please report problems here rather than to the
> FlClash or NekoBox authors.

## How it differs from FlClash

- **NekoBox's layout**: a pink top bar whose ☰ opens a side drawer in place of the bottom navigation. The drawer has
  three groups: proxies, profiles and dashboard / requests, connections, DNS queries and resources / tools and about.
- **Proxies as the home page**: groups sit in a pink tab strip under the bar, nodes are one-column cards, and the node
  in use carries a pink bar on its left with its protocol in pink.
- **NekoBox's connect button and stats bar**: the round button at the foot shows NekoBox's paper plane; while
  connected, a stats bar slides up with the upload and download speed and tests the connection when tapped.
- **Pink theme**: the default theme color is NekoBox's `#FB7299`.
- **Its own package**, `com.nekoclash`, so it installs beside FlClash with separate profiles and settings.

The core (mihomo), profiles, rules, overrides, TUN, per-app proxy and backups all come from FlClash unchanged.

## Install

Download `NekoClash-<version>-android-arm64-v8a.apk` from [Releases](https://github.com/xikijinise/NekoClash/releases/latest);
it suits most Android phones and installs beside FlClash. There is also a
[NekoClash website](https://xikijinise.github.io/Nekoclash/).

Signing certificate SHA-256: `0d50e1fe2df180097d95df86fce31d378d6b3a8914393c2930675b4767eca247`

## Build from source

You need [Flutter](https://docs.flutter.dev/get-started/install) 3.47, [Go](https://go.dev/dl/) 1.27 and the Android
SDK with the NDK.

```bash
git clone --recursive https://github.com/xikijinise/NekoClash.git
cd NekoClash
flutter pub get
flutter build apk --release --target-platform android-arm64 --dart-define=APP_ENV=stable
```

The APK lands in `build/app/outputs/flutter-apk/app-release.apk`; the Go core builds along with it.

- Without `--dart-define=APP_ENV=stable` the app shows a "PRE" banner.
- **Signing**: put your key in `android/app/keystore.jks` and `storePassword`, `keyAlias` and `keyPassword` in
  `android/local.properties`. Without them the build is signed with this machine's debug key, and a build from another
  machine cannot update it in place.
- Debug builds use the package `com.nekoclash.dev` and never replace the release app.

## Usage

**Import a profile from a link.** Opening a link in this form imports the subscription; `clashmeta://` and
`flclash://` work as well.

```text
clash://install-config?url=<URL-encoded subscription link>
```

**Android automation.** Tasker, MacroDroid and similar apps can start, stop or toggle the proxy by starting an
activity with one of these actions:

```text
com.nekoclash.action.START
com.nekoclash.action.STOP
com.nekoclash.action.TOGGLE
```

From a computer, adb does the same:

```bash
adb shell am start -a com.nekoclash.action.TOGGLE
```

## Keeping up with upstream

This fork does not merge FlClash wholesale; fixes and core updates are picked one by one. It is based on FlClash
v0.9.1 and carries v0.9.2's fix for reloading a running VPN when the app opens, and the mihomo v1.19.33 core.

## Credits and license

- [FlClash](https://github.com/chen08209/FlClash) by chen08209: every feature and the codebase this fork stands on.
- [NekoBox for Android](https://github.com/MatsuriDayo/NekoBoxForAndroid): the layout, colors and connect button icon.

Like both of them, NekoClash is released under the [GPL-3.0 license](LICENSE).
