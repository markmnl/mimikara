"""Load the extension unpacked in Chromium (via Playwright), inject it on a page
with a <video> the way the toolbar button does, load an .ass through the panel,
toggle the layers, check that settings persist across a reload, and screenshot.

    pip install playwright && playwright install chromium
    (cd extension && python -m http.server 8777) &
    python extension/dev/test_extension.py out/ [URL]

The toolbar click grants activeTab on a user gesture; an automated test has no
gesture, so a copy of the extension with host_permissions for the test URL is
loaded instead.  Nothing else differs from the shipped extension.
"""
import json, shutil, sys, tempfile, time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
EXT = HERE.parent
ASS = HERE / "luffy.all.ass"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="mimikara-ext-"))
URL = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8777/dev/video.html"
OUT.mkdir(parents=True, exist_ok=True)

ext_copy = OUT / "ext"
shutil.rmtree(ext_copy, ignore_errors=True)
shutil.copytree(EXT, ext_copy, ignore=shutil.ignore_patterns("dev", "package", "*.tgz"))
manifest = json.loads((ext_copy / "manifest.json").read_text())
u = urlsplit(URL)
manifest["host_permissions"] = [f"{u.scheme}://{u.hostname}/*"]
(ext_copy / "manifest.json").write_text(json.dumps(manifest, indent=2))

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        str(OUT / "profile"), channel="chromium", headless=True,
        args=[f"--disable-extensions-except={ext_copy}", f"--load-extension={ext_copy}",
              "--autoplay-policy=no-user-gesture-required"],
        viewport={"width": 1280, "height": 800})
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    print("extension service worker:", sw.url)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(URL)
    page.wait_for_selector("video")
    page.evaluate("async () => { const v = document.querySelector('video'); v.muted = true; try { await v.play(); } catch (e) {} v.pause(); v.currentTime = 0; }")

    def click_action():
        # what background.js does when the toolbar button is clicked
        sw.evaluate("""async () => {
            const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
            await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ['content.js'] });
            return tab.id; }""")

    click_action()
    page.wait_for_selector("iframe[src^='chrome-extension://']", timeout=10000)
    print("overlay iframe injected:", page.locator("iframe[src^='chrome-extension://']").get_attribute("src"))
    page.locator("#panel #file").set_input_files(str(ASS))
    for _ in range(50):
        if ".ass" in (page.locator("#panel #name").text_content() or ""):
            break
        time.sleep(0.2)
    for k in ("romaji", "kana"):
        page.locator(f"#panel #{k}").check()
    time.sleep(1.5)
    page.evaluate("async () => { const v = document.querySelector('video'); await v.play(); }")
    time.sleep(2.3)
    page.evaluate("() => document.querySelector('video').pause()")
    time.sleep(0.5)
    print("status:", page.locator("#panel #status").text_content(), "| file:", page.locator("#panel #name").text_content(),
          "| t=%.2f" % page.evaluate("() => document.querySelector('video').currentTime"))
    page.screenshot(path=str(OUT / "ext_japanese.png"))
    for k in ("romaji", "kana"):
        page.locator(f"#panel #{k}").uncheck()
    time.sleep(1.0)
    print("status (english only):", page.locator("#panel #status").text_content())
    page.screenshot(path=str(OUT / "ext_english.png"))

    # the file and the toggles persist in chrome.storage: reload, inject again
    page.reload()
    page.wait_for_selector("video")
    click_action()
    page.wait_for_selector("iframe[src^='chrome-extension://']", timeout=10000)
    time.sleep(1.5)
    print("after reload:", page.locator("#panel #name").text_content(), "|", page.locator("#panel #status").text_content())
    ctx.close()
print("OK; screenshots in", OUT)
