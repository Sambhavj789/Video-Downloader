"""Ad-hoc probe for the metadata proxy — dev helper, not used by the app.

    python tools/probe.py /batches/<batchId>
    python tools/probe.py "/batches/<batchId>/subject/<subjectId>/topics?page=1"

Cloudflare blocks plain HTTP clients on ``proxy.streamvideo.co.in``, so this goes
through the same headless Chromium context the app uses (:mod:`vd.proxy`).
Prints a compact summary of the payload instead of dumping megabytes.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vd.proxy import MetadataClient  # noqa: E402


def summarize(payload: dict) -> None:
    data = payload.get("data")
    print("success:", payload.get("success"), "| keys:", list(payload.keys()))
    if isinstance(data, dict):
        print("data keys:", list(data.keys()))
        for key in ("_id", "name", "batchName", "subjectName"):
            if key in data:
                print(f"  {key}: {data[key]}")
        for key in ("subjects", "topics", "contents"):
            if isinstance(data.get(key), list):
                print(f"  {key} ({len(data[key])}):")
                for entry in data[key][:40]:
                    label = entry.get("name") or entry.get("subject") or entry.get("topic")
                    print("   -", entry.get("_id"), "|", label)
    elif isinstance(data, list):
        print(f"data: {len(data)} item(s)")
        for entry in data[:20]:
            print(" -", entry.get("_id"), "|", entry.get("name") or entry.get("topic"))
    else:
        print(json.dumps(payload, ensure_ascii=False)[:2000])


async def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = argv[1]
    raw = "--raw" in argv
    version = "v3" if "--v3" in argv else "v2"
    async with MetadataClient() as client:
        payload = await client.get_json_version(path, version=version)
    if raw:
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:20000])
    else:
        summarize(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv)))
