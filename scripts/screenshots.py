#!/usr/bin/env python3
"""
Regenerate docs/screenshots/*.png against a running fhir-codebridge instance.

Matches the originals: 1280x800 viewport, viewport-only (not full page), so the
images stay cropped to the app with no browser chrome, URL bar or desktop in
frame. Run with the service already listening on --base.
"""
import argparse
import pathlib
import sys

from playwright.sync_api import sync_playwright

TABS = [
    ("dashboard.png", "Dashboard"),
    ("lookup.png", "Single Lookup"),
    ("bulk.png", "Bulk Upload"),
    ("analytics.png", "Analytics"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--out", default="docs/screenshots")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--hide-scrollbars"])
        page = browser.new_page(viewport={"width": 1280, "height": 800},
                                device_scale_factor=1)
        page.goto(args.base, wait_until="networkidle")

        for filename, label in TABS:
            page.get_by_role("button", name=label, exact=True).click()
            page.wait_for_timeout(600)

            if filename == "lookup.png":
                # The original showed a completed lookup rather than a blank
                # form. Reproduce it so the image documents a result.
                page.fill("#lookup-code", "E11.9")
                page.select_option("#lookup-source", "ICD-10-CM")
                page.select_option("#lookup-target", "SNOMED-CT")
                page.get_by_role("button", name="Map It", exact=True).click()
                page.wait_for_timeout(1200)

            page.screenshot(path=str(out / filename))
            print("wrote %s" % (out / filename))

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
