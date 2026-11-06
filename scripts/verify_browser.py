"""Optional rendered QA: uv run --with playwright python scripts/verify_browser.py."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="验证当前本地网页的响应式布局并保存截图")
    parser.add_argument("--url", default="http://127.0.0.1:18761")
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright
    output = Path(__file__).resolve().parents[1] / "outputs/browser"
    output.mkdir(parents=True, exist_ok=True)
    errors, reports = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            for width, height in ((1440, 1000), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                for path in ("/", "/growth", "/equipment", "/economy", "/ask", "/tasks", "/references", "/settings"):
                    response = page.goto(args.url + path, wait_until="networkidle")
                    assert response.status == 200, (path, response.status)
                    state = page.evaluate("""() => ({
                        width:innerWidth, contentWidth:document.documentElement.scrollWidth,
                        heading:document.querySelector('h1')?.innerText,
                        manualInputs:document.querySelectorAll('[name=price_gold],[name=manual_stats],[name=manual_recipe],[name=game_path]').length,
                        icon:document.querySelector('link[rel=icon]')?.getAttribute('href')
                    })""")
                    assert state["contentWidth"] <= width, (path, state)
                    assert state["manualInputs"] == 0, (path, state)
                    assert state["icon"] == "/static/app-icon.png"
                    reports.append({"path": path, "viewport": [width, height], **state})
                    if (path == "/" and width == 1440) or (path == "/tasks" and width == 390):
                        page.screenshot(path=str(output / ("overview-desktop.png" if path == "/" else "tasks-mobile.png")), full_page=True)
            assert page.request.get(args.url + "/static/app-icon.png").status == 200
            assert not errors, errors
        finally:
            browser.close()
    (output / "report.json").write_text(json.dumps({"pages": reports, "console_errors": errors}, ensure_ascii=False, indent=2))
    print(f"BROWSER_OK: {len(reports)} rendered checks, no overflow/manual data inputs/console errors; icon loaded")


if __name__ == "__main__":
    main()
