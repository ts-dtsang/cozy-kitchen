"""Download the 42 Addressables bundles that contain the dish and menu images.

Input : image-bundles.json (same folder)  -> list of bundle file names + base url
Output: bundles/<name>.bundle

Usage : python download_bundles.py [--out bundles] [--base URL] [--only dish-q00]
Then  : python extract.py --bundles-dir bundles   (your existing script)
"""

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.crazygames.com/"}


def fetch(url: str) -> bytes | None:
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
            if response.headers.get("Content-Encoding") == "br":
                import brotli

                data = brotli.decompress(data)
            return data
    except urllib.error.HTTPError as error:
        print(f"  HTTP {error.code}  {url}")
    except Exception as error:
        print(f"  ERROR {error!r}  {url}")
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("data/ouput/image-bundles.json"))
    parser.add_argument("--out", type=Path, default=Path("data/bundles"))
    parser.add_argument("--base", help="override the base url (must end with /aa/WebGL/)")
    parser.add_argument("--only", help="only bundles whose name contains this text, e.g. dish-q00")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    base = args.base or manifest["base_url"]
    names = [name for name in manifest["bundles"] if not args.only or args.only in name]
    args.out.mkdir(parents=True, exist_ok=True)

    failed = []
    for number, name in enumerate(names, 1):
        target = args.out / name
        if target.exists() and target.stat().st_size > 0:
            print(f"[{number}/{len(names)}] skip  {name}")
            continue
        data = fetch(base + urllib.parse.quote(name))
        if not data:
            failed.append(name)
            continue
        target.write_bytes(data)
        print(f"[{number}/{len(names)}] saved {name} ({len(data):,} bytes)")

    print(f"\nDone: {len(names) - len(failed)}/{len(names)} bundles in {args.out}")
    if failed:
        print("Failed:", *failed, sep="\n  ")
        print("\nIf every request fails with 403/404, open the first URL in your browser to check it,")
        print("or copy a real bundle URL from DevTools and pass its folder with --base.")


if __name__ == "__main__":
    main()
