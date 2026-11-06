"""Build a native AppKit/WKWebView client with the generated macOS icon."""
import argparse
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def build(output: Path):
    if sys.platform != "darwin":
        raise ValueError("macOS 应用需在 Mac 上构建；Windows 可直接使用启动.ps1")
    if output.exists():
        raise ValueError("输出应用已存在；请用 --output 指定新名称，避免覆盖已有应用")
    output.parent.mkdir(parents=True, exist_ok=True)
    source = ROOT / "assets/app-icon/forever-ai-icon.png"
    if not source.is_file():
        raise ValueError("缺少生成的应用图标")
    iconset = ROOT / "outputs/macos/ForeverAI.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    sizes = ((16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1), (512, 2))
    for size, scale in sizes:
        name = f"icon_{size}x{size}" + ("@2x" if scale == 2 else "") + ".png"
        # Standard packaging downsampling only; the generated art and alpha are unchanged.
        subprocess.run(["sips", "-z", str(size * scale), str(size * scale), str(source), "--out", str(iconset / name)],
                       check=True, stdout=subprocess.DEVNULL)
    icns = ROOT / "assets/app-icon/ForeverAI.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)
    executable = output / "Contents/MacOS/ForeverAI"
    executable.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fmodules", "-Os", "-arch", "x86_64", "-arch", "arm64",
                    "-mmacosx-version-min=12.0", "-framework", "Cocoa", "-framework", "WebKit", "-framework", "UniformTypeIdentifiers",
                    str(ROOT / "native/macos/main.m"), "-o", str(executable)], check=True)
    resources = output / "Contents/Resources"
    resources.mkdir(parents=True, exist_ok=True)
    shutil.copy2(icns, resources / "ForeverAI.icns")
    plist = output / "Contents/Info.plist"
    data = dict(CFBundleName="Forever AI Companion", CFBundleDisplayName="Forever AI Companion",
                CFBundleExecutable="ForeverAI", CFBundlePackageType="APPL", CFBundleInfoDictionaryVersion="6.0",
                CFBundleIdentifier="local.foreverai.companion.launcher", CFBundleIconFile="ForeverAI.icns",
                CFBundleVersion="0.2.1", CFBundleShortVersionString="0.2.1", NSHighResolutionCapable=True,
                LSMinimumSystemVersion="12.0", ForeverAIProjectPath=str(ROOT),
                NSPrincipalClass="NSApplication",
                NSAppTransportSecurity={"NSAllowsLocalNetworking": True, "NSExceptionDomains": {
                    "127.0.0.1": {"NSExceptionAllowsInsecureHTTPLoads": True},
                    "localhost": {"NSExceptionAllowsInsecureHTTPLoads": True}}})
    plist.write_bytes(plistlib.dumps(data))
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(output)], check=True)
    shutil.copy2(iconset / "icon_128x128@2x.png", ROOT / "frontend/static/app-icon.png")
    print("MAC_APP_BUILT", output)
    print("ICON", icns)


def main():
    parser = argparse.ArgumentParser(description="构建带定制图标和独立窗口的 macOS 客户端")
    parser.add_argument("--output", type=Path, default=ROOT / "Forever AI Companion.app")
    args = parser.parse_args()
    try:
        build(args.output.expanduser().resolve())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"构建未完成：{exc}\n")


if __name__ == "__main__":
    main()
