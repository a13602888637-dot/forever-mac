"""Rendered desktop acceptance against the explicitly isolated desktop QA server."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18774")
    parser.add_argument("--interactions-only", action="store_true")
    parser.add_argument("--interactions", action="store_true", help="Only use with desktop_qa_server.py")
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright, expect
    output = ROOT / "outputs/v04/browser"
    output.mkdir(parents=True, exist_ok=True)
    errors, reports, actions = [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(20000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            paths = ("/", "/discover", "/addons/ellesmere", "/profiles", "/downloads", "/overview",
                     "/overview?tab=equipment", "/overview?tab=bags", "/overview?tab=professions", "/overview?tab=quests",
                     "/references", "/references/recipes/125", "/equipment", "/economy", "/ask", "/settings", "/workshop", "/growth", "/tasks")
            # Choose an actual cached recipe id rather than depending on a source id existing forever.
            recipes = page.request.get(args.url + "/api/references/browse?kind=recipes&page_size=1").json()["results"]
            actual_recipe = recipes[0]["record"]["id"] if recipes else None
            for width, height in (() if args.interactions_only else ((1320, 900), (900, 620), (390, 844))):
                page.set_viewport_size({"width": width, "height": height})
                for raw_path in paths:
                    path = f"/references/recipes/{actual_recipe}" if raw_path == "/references/recipes/125" and actual_recipe else raw_path
                    response = page.goto(args.url + path, wait_until="networkidle", timeout=60000)
                    assert response.status == 200, (path, response.status)
                    state = page.evaluate("""() => ({width:innerWidth,contentWidth:document.documentElement.scrollWidth,
                        heading:document.querySelector('h1')?.innerText,
                        visibleRows:Array.from(document.querySelectorAll('[data-addon-id]')).filter(r=>r.getBoundingClientRect().bottom<=innerHeight).length,
                        imageCount:document.images.length,brokenImages:Array.from(document.images).filter(i=>i.complete&&!i.naturalWidth).map(i=>i.getAttribute('src'))})""")
                    assert state["contentWidth"] <= width, (path, state)
                    if path == "/" and width == 1320:
                        assert state["visibleRows"] >= 8, state
                    reports.append({"path": path, "viewport": [width, height], **state})
                    if path in ("/", "/discover", "/profiles", "/overview?tab=bags", "/references"):
                        name = path.replace("/", "").replace("?tab=", "-") or "addons"
                        page.screenshot(path=str(output / f"{name}-{width}.png"), full_page=True)
            if reports:
                (output / "layout-report.json").write_text(json.dumps({"pages":reports,"script_errors":errors}, ensure_ascii=False,indent=2))
            if args.interactions or args.interactions_only:
                health = page.request.get(args.url + "/api/health").json()
                assert health["mode"] == "mock", "Mutation acceptance requires the isolated mock client"
                fixture = json.loads((ROOT / "outputs/v04/qa-server.json").read_text())
                assert str(fixture["port"]) == args.url.rsplit(":", 1)[-1]
                page.set_viewport_size({"width": 1320, "height": 900})
                page.goto(args.url, wait_until="networkidle")
                expect(page.locator('[data-addon-id="dbm"] [data-enablement]')).to_have_text("已启用")
                page.locator('#addon-search').fill("BigWigs")
                expect(page.locator('[data-addon-id]:visible')).to_have_count(2)
                page.locator('#addon-search').fill("")
                page.locator('#addon-status').select_option("release_differs")
                expect(page.locator('[data-addon-id]:visible')).to_have_count(1)
                page.locator('#addon-status').select_option("all")
                page.locator('#addon-sort').select_option("update")
                page.locator('.addon-check').first.check()
                page.locator('.addon-check').nth(2).click(modifiers=["Shift"])
                expect(page.locator('.addon-check:checked')).to_have_count(3)
                page.locator('#select-all-addons').check()
                expect(page.locator('.addon-check:checked')).to_have_count(9)
                page.locator('#select-all-addons').uncheck()
                page.locator('[data-addon-id="details"] .addon-check').check()
                page.locator('[data-manage="disable"]').click()
                page.wait_for_url('**/addons/management/*')
                expect(page.locator('h1')).to_have_text('停用预览')
                page.locator('[data-management-apply]').click()
                page.locator('#confirm-accept').click()
                expect(page.locator('[data-management-apply]')).to_have_text('当前不可应用')
                page.goto(args.url, wait_until="networkidle")
                expect(page.locator('[data-addon-id="details"] [data-enablement]')).to_have_text('已停用')
                expect(page.locator('[data-addon-id="details"] .addon-check')).to_be_checked()
                page.locator('[data-manage="enable"]').click()
                page.wait_for_url('**/addons/management/*')
                page.locator('[data-management-apply]').click()
                page.locator('#confirm-accept').click()
                expect(page.locator('[data-management-apply]')).to_have_text('当前不可应用')
                actions.append('search/filter/sort/shift-select/all-select/selection-retained/character-disable-enable')
                page.goto(args.url + '/overview?tab=bags', wait_until='networkidle')
                page.locator('#bag-search').fill('兜帽')
                expect(page.locator('.bag-item:visible')).to_have_count(1)
                page.locator('.bag-item:visible').click()
                expect(page.locator('#bag-item-dialog')).to_be_visible()
                page.locator('#bag-compare-form button').click()
                expect(page.locator('#bag-compare-result')).to_contain_text('+4')
                page.screenshot(path=str(output/'bag-comparison.png'))
                page.locator('[data-close-bag]').click()
                page.reload(wait_until='networkidle')
                expect(page.locator('#bag-search')).to_have_value('兜帽')
                page.locator('#bag-search').fill('')
                page.locator('#bag-sort').select_option('count')
                expect(page.locator('.bag-item').first).to_contain_text('丝绸')
                page.locator('#global-character').select_option(label='战士（演示）')
                page.locator('.character-switch button').click()
                expect(page.locator('.character-header')).to_contain_text('战士（演示）')
                expect(page.locator('.character-header')).to_contain_text('兽人')
                actions.append('interactive-bags/search/sort/details/compare/state-retained/character-switch')
                page.goto(args.url+'/profiles',wait_until='networkidle')
                page.locator('[data-image]').first.click()
                expect(page.locator('#image-dialog')).to_be_visible()
                expect(page.locator('#image-dialog img')).to_have_js_property('complete',True)
                page.locator('[data-close-image]').click()
                page.locator('[data-profile-plan="ForeverUI"]').click()
                expect(page.locator('#profile-preview')).to_be_visible()
                page.locator('#profile-apply').click()
                page.locator('#confirm-accept').click()
                page.wait_for_url('**/downloads')
                actions.append('profile-image-zoom/switch-preview/apply')
                page.goto(args.url,wait_until='networkidle')
                page.locator('[data-open-import]').click()
                page.locator('#addon_zip').set_input_files(fixture['zip'])
                page.locator('#import-dialog button[type=submit]').click()
                page.wait_for_url('**/addons/plans/*')
                expect(page.locator('h1')).to_have_text('安装变更预览')
                assert page.locator('.plan-change[open]').count()==0
                page.locator('[data-home]').click()
                page.locator('#confirm-accept').click()
                page.wait_for_url('**/downloads')
                page.goto(args.url,wait_until='networkidle')
                page.locator('#addon-search').fill('DesktopFixture')
                page.locator('#select-all-addons').check()
                page.locator('[data-manage="uninstall"]').click()
                page.wait_for_url('**/addons/management/*')
                page.locator('[data-management-apply]').click()
                page.locator('#confirm-accept').click()
                expect(page.locator('[data-management-apply]')).to_have_text('当前不可应用')
                page.goto(args.url+'/downloads',wait_until='networkidle')
                page.locator('button[data-api$="/rollback"]').first.click()
                expect(page.locator('#restore-dialog')).to_contain_text('恢复变更预览')
                page.locator('#restore-dialog .button-primary').click()
                expect(page.locator('.history-row').filter(has_text='已回滚')).not_to_have_count(0)
                actions.append('zip-import/preview/collapsed-file-details/apply/uninstall/restore')
                page.goto(args.url+'/references?kind=recipes',wait_until='networkidle')
                page.locator('.reference-card').first.click()
                expect(page.locator('h1')).not_to_be_empty()
                relation=page.locator('.reference-relations a').first
                if relation.count():
                    relation.click()
                    expect(page.locator('h1')).not_to_be_empty()
                page.goto(args.url+'/references',wait_until='networkidle')
                page.get_by_role('link',name='下一页',exact=True).click()
                expect(page.locator('.pagination')).to_contain_text('2 /')
                actions.append('reference-detail/material-jump/pagination')
            assert not errors, errors
            (output / ("interaction-report.json" if args.interactions_only else "report.json")).write_text(json.dumps({"pages": reports, "actions":actions,"script_errors":errors},ensure_ascii=False,indent=2))
            print(f"DESKTOP_BROWSER_OK: {len(reports)} rendered checks; {len(actions)} interaction groups; no overflow or script errors")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
