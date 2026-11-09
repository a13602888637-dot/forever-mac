"""Focused rendered checks for the world catalog, against an isolated QA server."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    from playwright.sync_api import sync_playwright, expect

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18775")
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "outputs/v041/browser"
    output.mkdir(parents=True, exist_ok=True)
    errors, layouts = [], []
    paths = ["/", "/discover?category=地图", "/discover?category=任务", "/addons/atlas-classic",
             "/addons/dbm-dungeons", "/addons/questie", "/references?kind=instances", "/references?kind=bosses",
             "/references?kind=maps", "/references?kind=quests", "/references/instances/389",
             "/references/bosses/902732", "/references/maps/1454", "/references/quests/5722", "/references/quests/10"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page()
            page.set_default_timeout(20000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            assert page.request.get(args.url + "/api/health").json()["mode"] == "mock"
            for width, height in ((1320, 900), (900, 620), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                for path in paths:
                    response = page.goto(args.url + path, wait_until="networkidle", timeout=60000)
                    assert response.status == 200, (path, response.status)
                    state = page.evaluate("""() => ({heading:document.querySelector('h1').textContent,
                        width:innerWidth,scroll:document.documentElement.scrollWidth,
                        broken:Array.from(document.images).filter(i=>i.getAttribute('src')&&i.complete&&!i.naturalWidth).map(i=>i.src)})""")
                    assert state["scroll"] <= width, (path, state)
                    assert not state["broken"], (path, state)
                    for pin in page.locator("[data-map-x]").all():
                        offset = pin.evaluate("""node => { const r=node.getBoundingClientRect(),p=node.closest('.reference-map').getBoundingClientRect();
                            return Math.max(Math.abs((r.x+r.width/2-p.x)/p.width*100-Number(node.dataset.mapX)),
                                Math.abs((r.y+r.height/2-p.y)/p.height*100-Number(node.dataset.mapY))); }""")
                        assert offset < .5, (path, "map marker misplaced", offset)
                    layouts.append({"path": path, "viewport": [width, height], **state})
                    if path in ("/discover?category=地图", "/references/instances/389", "/references/quests/5722"):
                        name = path.strip("/").replace("/", "-").replace("?category=", "-")
                        page.screenshot(path=str(output / f"{name}-{width}.png"), full_page=True)
            page.set_viewport_size({"width": 1320, "height": 900})
            page.goto(args.url + "/references?kind=quests", wait_until="networkidle")
            page.get_by_role("link", name="下一页", exact=True).click()
            expect(page.locator(".pagination")).to_contain_text("2 /")
            page.get_by_label("搜索图鉴").fill("寻找背包")
            page.get_by_role("button", name="筛选", exact=True).click()
            expect(page.locator(".reference-card")).to_have_count(1)
            page.locator(".reference-card").click()
            expect(page.locator("h1")).to_have_text("寻找背包")
            page.locator('.reference-relations a[href="/references/instances/389"]').click()
            expect(page.locator("h1")).to_have_text("怒焰裂谷")
            page.locator('.reference-relations a[href="/references/bosses/902732"]').click()
            expect(page.locator("h1")).to_have_text("奥格弗林特")
            page.goto(args.url + "/references/maps/1454", wait_until="networkidle")
            page.locator('.map-pin[href="/references/instances/389"]').click()
            expect(page.locator("h1")).to_have_text("怒焰裂谷")
            page.goto(args.url + "/references?kind=quests&category=clues", wait_until="networkidle")
            expect(page.locator(".reference-card").first).to_contain_text("仅编号")
            page.goto(args.url + "/addons/questie", wait_until="networkidle")
            page.get_by_role("link", name="导入作者 ZIP", exact=True).click()
            expect(page.locator("#import-dialog")).to_be_visible()
            assert page.locator("#import-dialog input[name=forever_confirmed]").is_checked() is False
            assert not errors, errors
            report = {"layouts": layouts, "script_errors": errors, "flows": [
                "quest pagination and search", "quest-instance-boss links", "map entrance link",
                "unconfirmed quest filter", "catalog ZIP import handoff without confirmation"]}
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps({"layouts": len(layouts), "flows": len(report["flows"]), "script_errors": errors}))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
