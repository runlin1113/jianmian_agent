"""用 CDP 驱动无头 Chrome 做一次真实交互，并截图。

为什么不用 `--screenshot`：那套走的是虚拟时间，和 CSS 过渡/异步请求的时序对不上，
经常拍到过渡中间的一帧。这里用真实时间 + 显式等待，状态和画面都能对得上。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

import websockets

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9333


def launch(profile: str) -> subprocess.Popen:
    if os.path.isdir(profile):
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", profile], capture_output=True)
    os.makedirs(profile, exist_ok=True)
    proc = subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={PORT}",
            f"--user-data-dir={profile}",
            "--window-size=1600,1000",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=1) as resp:
                targets = json.load(resp)
            for t in targets:
                if t.get("type") == "page":
                    return proc, t["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.15)
    proc.kill()
    raise RuntimeError("Chrome 调试端口没起来")


class Session:
    def __init__(self, ws):
        self.ws = ws
        self.seq = 0
        self.events: list[dict] = []

    async def call(self, method: str, **params):
        self.seq += 1
        mid = self.seq
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self.events.append(msg)

    async def drain(self, seconds: float):
        """边等边收事件，避免 buffer 塞满或丢掉异常。"""
        end = time.time() + seconds
        while time.time() < end:
            try:
                msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=0.2))
                self.events.append(msg)
            except asyncio.TimeoutError:
                continue

    def errors(self) -> list[str]:
        out = []
        for ev in self.events:
            if ev.get("method") == "Runtime.exceptionThrown":
                detail = ev["params"]["exceptionDetails"]
                out.append(detail.get("exception", {}).get("description") or detail.get("text", ""))
            if ev.get("method") == "Log.entryAdded":
                entry = ev["params"]["entry"]
                if entry.get("level") == "error":
                    out.append(f"[{entry.get('source')}] {entry.get('text')}")
        return out


async def run(url: str, shot: str, steps: list[tuple[str, str]] | None = None):
    proc, ws_url = launch(r"C:\Users\Administrator\AppData\Local\Temp\jm_cdp_profile")
    try:
        async with websockets.connect(ws_url, max_size=2**26) as ws:
            s = Session(ws)
            await s.call("Page.enable")
            await s.call("Runtime.enable")
            await s.call("Log.enable")
            await s.call("Page.navigate", url=url)
            await s.drain(3.0)

            for kind, payload in steps or []:
                if kind == "hover":
                    box = await s.call(
                        "Runtime.evaluate",
                        expression=f'(() => {{ const r = document.querySelector({payload!r}).getBoundingClientRect(); return JSON.stringify({{x: r.x + r.width/2, y: r.y + r.height/2}}); }})()',
                        returnByValue=True,
                    )
                    pos = json.loads(box["result"]["value"])
                    await s.call("Input.dispatchMouseEvent", type="mouseMoved", x=pos["x"], y=pos["y"], buttons=0)
                    print("  hover →", payload, pos)
                    await s.drain(0.8)
                if kind == "pdf":
                    res = await s.call(
                        "Page.printToPDF",
                        printBackground=True,
                        paperWidth=8.27,
                        paperHeight=11.69,
                        marginTop=0,
                        marginBottom=0,
                        marginLeft=0,
                        marginRight=0,
                    )
                    with open(payload, "wb") as fh:
                        fh.write(base64.b64decode(res["data"]))
                    print("  pdf →", payload)
                    await s.drain(0.6)
                if kind == "eval":
                    r = await s.call("Runtime.evaluate", expression=payload, returnByValue=True, awaitPromise=True)
                    print("  eval →", json.dumps(r.get("result", {}).get("value"), ensure_ascii=False)[:400])
                    await s.drain(1.6)

            state = await s.call(
                "Runtime.evaluate",
                expression="""JSON.stringify({
                  view: document.body.dataset.view,
                  modules: (window.__jmDebug?.modules ?? document.querySelectorAll('.module-card').length),
                  chatMsgs: document.querySelectorAll('#chatScroll .msg').length,
                  cards: document.querySelectorAll('#chatScroll .msg-card').length,
                  pages: document.querySelectorAll('#previewStack .page').length,
                  landingOpacity: getComputedStyle(document.querySelector('#landing')).opacity,
                  stageOpacity: getComputedStyle(document.querySelector('.stage')).opacity,
                  toasts: Array.from(document.querySelectorAll('.toast')).map(n => n.textContent),
                  hint: document.querySelector('#askHint')?.textContent || ''
                })""",
                returnByValue=True,
            )
            print("  state →", state.get("result", {}).get("value"))

            await s.drain(2.2)
            shot_res = await s.call("Page.captureScreenshot", format="png")
            with open(shot, "wb") as fh:
                fh.write(base64.b64decode(shot_res["data"]))
            print("  shot →", shot)

            errs = s.errors()
            print("  console errors →", errs if errs else "none")
    finally:
        proc.kill()


if __name__ == "__main__":
    url = sys.argv[1]
    shot = sys.argv[2]
    raw_steps = sys.argv[3] if len(sys.argv) > 3 else ""
    steps = []
    for chunk in filter(None, raw_steps.split("||")):
        if chunk.startswith("pdf:"):
            steps.append(("pdf", chunk[4:]))
        elif chunk.startswith("hover:"):
            steps.append(("hover", chunk[6:]))
        else:
            steps.append(("eval", chunk))
    asyncio.run(run(url, shot, steps))
