"""Build a native AppKit/WKWebView client with the generated macOS icon."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ID = "local.foreverai.companion.launcher"


def existing_app(output: Path):
    if output.is_symlink():
        raise ValueError("输出应用不能是符号链接")
    if not output.exists():
        return None
    if not output.resolve().is_relative_to(ROOT):
        raise ValueError("仅自动归档本项目内的旧应用；外部输出请指定新名称")
    try:
        info = plistlib.loads((output / "Contents/Info.plist").read_bytes())
    except (OSError, plistlib.InvalidFileException):
        raise ValueError("已有输出不是可确认的 Forever 应用，保留原文件") from None
    if info.get("CFBundleIdentifier") != BUNDLE_ID:
        raise ValueError("已有输出不是本项目应用，保留原文件")
    processes = subprocess.check_output(["/bin/ps", "-ww", "-axo", "comm="], text=True, timeout=5)
    if any(Path(line.strip()).is_relative_to(output.resolve()) for line in processes.splitlines() if line.strip()):
        raise ValueError("旧应用仍在运行；退出 Forever 窗口后再构建，当前应用保持原样")
    return info


def install_built_app(staged: Path, output: Path, version: str):
    info = existing_app(output)
    if info is None:
        staged.rename(output)
        return
    batch = ROOT / "delete" / datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f-build")
    relative = output.relative_to(ROOT)
    archived = batch / relative.with_name(relative.name + ".disabled")
    archived.parent.mkdir(parents=True)
    manifest = {"source": str(relative), "destination": str(archived.relative_to(ROOT)),
                "old_version": info.get("CFBundleShortVersionString"), "new_version": version,
                "status": "prepared"}
    receipt = batch / "manifest.json"
    receipt.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    output.rename(archived)
    try:
        staged.rename(output)
    except OSError:
        archived.rename(output)
        manifest["status"] = "restored_after_install_failure"
        receipt.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        raise
    manifest["status"] = "installed"
    receipt.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("PREVIOUS_APP_ARCHIVED", archived)


def compile_app(output: Path, work: Path, version: str):
    source = ROOT / "assets/app-icon/forever-ai-icon.png"
    if not source.is_file():
        raise ValueError("缺少生成的应用图标")
    iconset = work / "ForeverAI.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    sizes = ((16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1), (512, 2))
    for size, scale in sizes:
        name = f"icon_{size}x{size}" + ("@2x" if scale == 2 else "") + ".png"
        # Standard packaging downsampling only; the generated art and alpha are unchanged.
        subprocess.run(["sips", "-z", str(size * scale), str(size * scale), str(source), "--out", str(iconset / name)],
                       check=True, stdout=subprocess.DEVNULL)
    icns = work / "ForeverAI.icns"
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
    data = dict(CFBundleName="Forever", CFBundleDisplayName="Forever",
                CFBundleExecutable="ForeverAI", CFBundlePackageType="APPL", CFBundleInfoDictionaryVersion="6.0",
                CFBundleIdentifier=BUNDLE_ID, CFBundleIconFile="ForeverAI.icns",
                CFBundleVersion=version, CFBundleShortVersionString=version, NSHighResolutionCapable=True,
                LSMinimumSystemVersion="12.0", ForeverAIProjectPath=str(ROOT),
                NSPrincipalClass="NSApplication",
                NSAppTransportSecurity={"NSAllowsLocalNetworking": True, "NSExceptionDomains": {
                    "127.0.0.1": {"NSExceptionAllowsInsecureHTTPLoads": True},
                    "localhost": {"NSExceptionAllowsInsecureHTTPLoads": True}}})
    plist.write_bytes(plistlib.dumps(data))
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(output)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(output)], check=True)


def build(output: Path):
    if sys.platform != "darwin":
        raise ValueError("macOS 应用需在 Mac 上构建；Windows 可直接使用启动.ps1")
    import fcntl
    output = output.expanduser().absolute()
    output = output.parent.resolve() / output.name
    if output.suffix != ".app":
        raise ValueError("输出路径必须以 .app 结尾")
    archive_root = ROOT / "delete"
    if archive_root.is_symlink():
        raise ValueError("delete 归档目录不能是符号链接")
    archive_root.mkdir(exist_ok=True)
    lock_path = archive_root / ".macos-build.lock"
    if lock_path.is_symlink():
        raise ValueError("构建锁不能是符号链接")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("另一个 Mac 应用构建正在进行，请稍后重试") from None
        existing_app(output)
        version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".forever-build-", dir=output.parent) as temporary:
            work = Path(temporary)
            staged = work / output.name
            compile_app(staged, work, version)
            install_built_app(staged, output, version)
    print("MAC_APP_BUILT", output)


def main():
    parser = argparse.ArgumentParser(description="构建带定制图标和独立窗口的 macOS 客户端")
    parser.add_argument("--output", type=Path, default=ROOT / "Forever AI Companion.app")
    args = parser.parse_args()
    try:
        build(args.output)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"构建未完成：{exc}\n")


if __name__ == "__main__":
    main()
