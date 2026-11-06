# macOS 应用图标

生成方式：内置 **imagegen**，透明背景，无需项目 OpenAI API Key。原稿已保存到工作区，保留生成文件原件。

- `assets/app-icon/forever-ai-icon.png`：1254×1254 RGBA 原稿，透明外角。
- `assets/app-icon/ForeverAI.icns`：macOS 应用图标，包含标准 16–1024 像素尺寸。
- `frontend/static/app-icon.png`：网页使用的 256 像素版本。
- `Forever AI Companion.app`：AppKit + WKWebView 独立窗口客户端，自动连接本地服务。

修复版移除了旧的 `CFBundleIconName=applet`，明确使用 `ForeverAI.icns`，并在应用运行时设置 Dock 图标。应用左上角也使用同一张图片。独立窗口与 Logo 已获用户实际确认。

Apple 的 `sips` 和 `iconutil` 仅负责标准尺寸与图标封装，没有改动构图或生成内容。重建入口：`uv run python scripts/build_macos_app.py --output "Forever AI Companion-v2.app"`；已有应用不会被覆盖。

## 最终生成提示词

```text
Use case: logo-brand / stylized-concept. Asset type: production macOS application icon for Forever AI Companion, a personal arcane companion for an undead mage. Create ONE finished square 1024x1024 icon, not a presentation board or mockup. A premium, restrained macOS rounded-square tile in near-black plum obsidian (#100D17), with a clear sculptural central emblem: a simplified ivory hooded mage skull/mask, elegant angular cheekbones and two narrow lavender eye apertures, a small violet arcane crystal on the forehead, and one clean broken circular rune orbit suggesting eternity around the hood. Original emblem, not a Warcraft or Blizzard logo. Rich but quiet material detail: satin obsidian, bone-white inlay (#E8DECC), subtle amethyst edge light (#AB84EB), very restrained muted silver. A compact, unmistakable silhouette readable at 32 pixels. Head and orbit are large, centered, with excellent optical balance. Subtle crafted depth and bevel, top-left soft studio lighting, tiny ambient purple glow contained within the tile. Approximately 85–90 percent canvas coverage, clean transparent margin and genuinely transparent outer rounded corners, light natural icon shadow. No scenery, no character body, no weapons, no excessive particles, no busy decorative lettering, no text, no initials, no watermark, no grid, no border around the canvas. Sophisticated dark fantasy artifact with modern Apple icon polish. Preserve real alpha transparency outside the tile.
```
