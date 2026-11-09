"""Rendered boss loot and item reverse links against an isolated mock service."""
import argparse
import json
from pathlib import Path


def main():
    from playwright.sync_api import sync_playwright, expect

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18775")
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "outputs/v042/browser"
    output.mkdir(parents=True, exist_ok=True)
    errors, layouts = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page()
            page.set_default_timeout(20000)
            assert page.request.get(args.url + "/api/health").json()["mode"] == "mock"
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            paths = ("/references/bosses/902732", "/references/instances/389", "/references/bosses/902780",
                     "/references/items/272998", "/addons/atlasloot-forever")
            for width, height in ((1320, 900), (900, 620), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                for path in paths:
                    response = page.goto(args.url + path, wait_until="networkidle", timeout=60000)
                    assert response.status == 200
                    state = page.evaluate("""() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
                        heading:document.querySelector('h1').textContent,
                        broken:Array.from(document.images).filter(i=>i.getAttribute('src')&&i.complete&&!i.naturalWidth).map(i=>i.src)})""")
                    assert state["scroll"] <= width and not state["broken"], (path, state)
                    if path.endswith("/bosses/902732"):
                        expect(page.locator(".loot-grid .reference-card")).to_have_count(5)
                        expect(page.locator(".boss-loot-group > h3")).to_contain_text("Spyglass · 无限参考")
                    if path.endswith("/bosses/902780"):
                        expect(page.locator(".boss-loot-group > h3")).to_contain_text("QuestieDB · 经典旧世参考")
                    layouts.append({"path": path, "viewport": [width, height], **state})
                    if path.endswith("/bosses/902732") or path.endswith("/instances/389"):
                        page.screenshot(path=str(output / f"{path.strip('/').replace('/','-')}-{width}.png"), full_page=True)
            page.set_viewport_size({"width": 1320, "height": 900})
            page.goto(args.url + "/references/bosses/902732", wait_until="networkidle")
            page.locator('.loot-grid a[href="/references/items/272998"]').click()
            expect(page.locator("h1")).to_have_text("骨质指虎")
            page.locator('.reference-relations a[href="/references/bosses/902732"]').click()
            expect(page.locator("h1")).to_have_text("奥格弗林特")
            page.goto(args.url + "/references/instances/389", wait_until="networkidle")
            expect(page.locator(".boss-loot-group")).to_have_count(4)
            assert page.locator(".loot-grid .reference-card").count() > 5
            assert not errors, errors
            report = {"layouts": layouts, "flows": ["boss loot to item", "item reverse boss link", "instance grouped loot"],
                      "script_errors": errors}
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps({"layouts": len(layouts), "flows": 3, "script_errors": errors}))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
