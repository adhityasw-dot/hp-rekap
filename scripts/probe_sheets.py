import json
import re

import httpx

SHEET = "18LzVzlXT0EUOjrE8hb23mANjCiBJSSGzXc-hXB2W4Cw"


def main():
    r = httpx.get(
        f"https://docs.google.com/spreadsheets/d/{SHEET}/htmlview",
        follow_redirects=True,
        timeout=30,
    )
    print("htmlview", r.status_code, len(r.text))
    tabs = re.findall(r"docs-sheet-tab-name[^>]*>([^<]+)", r.text)
    print("tabs", tabs)
    gids = list(dict.fromkeys(re.findall(r"gid=(\d+)", r.text)))
    print("gids", gids)

    # Try export each gid
    for gid in gids[:20] or [str(i) for i in range(0, 15)]:
        rr = httpx.get(
            f"https://docs.google.com/spreadsheets/d/{SHEET}/export?format=csv&gid={gid}",
            follow_redirects=True,
            timeout=30,
        )
        if rr.status_code != 200 or len(rr.text) < 20:
            print(f"gid={gid} fail {rr.status_code} len={len(rr.text)}")
            continue
        lines = rr.text.splitlines()
        print(f"\n=== gid={gid} lines={len(lines)} chars={len(rr.text)} ===")
        for i, line in enumerate(lines[:4]):
            print(f"  {i}: {line[:160]}")
        # detect interesting headers
        head = lines[0].lower() if lines else ""
        if any(k in head for k in ("jual", "untung", "laba", "harga", "uang", "cash", "omzet")):
            print("  ** interesting header **")

    # gviz first sheet richer columns
    gviz = httpx.get(
        f"https://docs.google.com/spreadsheets/d/{SHEET}/gviz/tq?tqx=out:csv",
        follow_redirects=True,
        timeout=30,
    )
    print("\n=== gviz default ===")
    for i, line in enumerate(gviz.text.splitlines()[:8]):
        print(f"  {i}: {line[:180]}")

    # Try sheet name in gviz
    for name in [
        "FEBRUARI",
        "Februari",
        "MARET",
        "Maret",
        "APRIL",
        "April",
        "MEI",
        "Mei",
        "JUNI",
        "Juni",
        "JULI",
        "Juli",
        "JANUARI",
        "Januari",
        "Rekap",
        "Sheet1",
        "Penjualan",
    ]:
        url = (
            f"https://docs.google.com/spreadsheets/d/{SHEET}/gviz/tq"
            f"?tqx=out:csv&sheet={httpx.QueryParams({'x': name})['x']}"
        )
        # encode sheet name properly
        url = f"https://docs.google.com/spreadsheets/d/{SHEET}/gviz/tq?tqx=out:csv&sheet={name}"
        rr = httpx.get(url, follow_redirects=True, timeout=20)
        if rr.status_code == 200 and "error" not in rr.text[:80].lower() and len(rr.text) > 40:
            lines = rr.text.splitlines()
            print(f"\nSHEET name={name!r} lines={len(lines)}")
            for i, line in enumerate(lines[:3]):
                print(f"  {i}: {line[:180]}")


if __name__ == "__main__":
    main()
