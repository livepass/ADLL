"""浏览器离线验收（Edge headless + CDP，无第三方依赖）。

要求真实 FastAPI 后端 + Vue3 页面；本脚本只做浏览器操作与 DOM 断言，
不直接调用业务 API（用于验证页面确实经 HTTP 工作）。

用法（服务器需已启动）：
  python scripts/browser_e2e.py --base-url http://127.0.0.1:5173 \
      --repo <synthetic-repo> --password <synthetic-password>

输出：步骤结果 JSON + 关键截图（--out-dir）。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


class CDPError(RuntimeError):
    pass


class WebSocket:
    def __init__(self, url: str) -> None:
        # ws://127.0.0.1:9222/devtools/page/<id>
        rest = url.split("://", 1)[1]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CDPError("websocket handshake closed")
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise CDPError(response.decode("latin-1")[:200])
        self._buffer = response.split(b"\r\n\r\n", 1)[1]

    def send(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        header += mask
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _read_exact(self, count: int) -> bytes:
        while len(self._buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise CDPError("websocket closed")
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def recv(self) -> str:
        chunks = []
        while True:
            first, second = self._read_exact(2)
            fin = first & 0x80
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            if second & 0x80:
                mask = self._read_exact(4)
                data = bytes(
                    byte ^ mask[index % 4]
                    for index, byte in enumerate(self._read_exact(length))
                )
            else:
                data = self._read_exact(length)
            if opcode == 0x8:
                raise CDPError("websocket closed by browser")
            if opcode == 0x9:
                continue
            chunks.append(data)
            if fin:
                return b"".join(chunks).decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class CDP:
    def __init__(self, port: int, ws_url: str | None = None) -> None:
        if ws_url is None:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/json/list", timeout=2
                    ) as response:
                        targets = json.loads(response.read())
                    page = next(t for t in targets if t.get("type") == "page")
                    ws_url = page["webSocketDebuggerUrl"]
                    break
                except Exception:
                    time.sleep(0.1)
            else:
                raise CDPError("no CDP page target")
        self.ws = WebSocket(ws_url)
        self.next_id = 0
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.send("Network.enable")

    def send(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        message_id = self.next_id
        self.ws.send(
            json.dumps({"id": message_id, "method": method, "params": params or {}})
        )
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == message_id:
                if "error" in message:
                    raise CDPError(json.dumps(message["error"]))
                return message.get("result", {})

    def evaluate(self, expression: str):
        result = self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
                "userGesture": True,
            },
        )
        if result.get("exceptionDetails"):
            raise CDPError(json.dumps(result["exceptionDetails"])[:500])
        return result.get("result", {}).get("value")

    def navigate(self, url: str) -> None:
        self.send("Page.navigate", {"url": url})
        self.wait_ready()

    def reload(self) -> None:
        self.send("Page.reload", {"ignoreCache": True})
        self.wait_ready()

    def wait_ready(self, timeout: float = 15.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                state = self.evaluate("document.readyState")
                if state == "complete":
                    return
            except Exception:
                pass
            time.sleep(0.1)
        raise CDPError("page did not become ready")

    def wait_for(self, expression: str, timeout: float = 20.0) -> None:
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                last = self.evaluate(expression)
                if last:
                    return
            except Exception as exc:  # noqa: BLE001
                last = repr(exc)
            time.sleep(0.15)
        raise CDPError(f"condition not met: {expression}; last={last}")

    def screenshot(self, path: Path) -> None:
        data = self.send("Page.captureScreenshot", {"format": "png"})
        path.write_bytes(base64.b64decode(data["data"]))

    def close(self) -> None:
        self.ws.close()


# ---- page helpers executed in the browser ----


def start_edge(port: int, profile: Path) -> subprocess.Popen:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    executable = next((p for p in candidates if p.exists()), None)
    if executable is None:
        raise CDPError("Edge executable not found")
    return subprocess.Popen(
        [
            str(executable),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def open_new_page(port: int, url: str) -> CDP:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/json/new?{urllib.request.quote(url, safe='')}",
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        target = json.loads(response.read())
    page = CDP(port, ws_url=target["webSocketDebuggerUrl"])
    page.wait_ready()
    return page


def js_set(selector: str, value: str) -> str:
    return f"""(() => {{
      const el = document.querySelector({json.dumps(selector)});
      if (!el) return 'not_found';
      const proto = el.tagName === 'TEXTAREA'
        ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, {json.dumps(value)});
      el.dispatchEvent(new Event('input', {{bubbles: true}}));
      el.dispatchEvent(new Event('change', {{bubbles: true}}));
      return 'ok';
    }})()"""


def js_set_index(selector: str, index: int, value: str) -> str:
    return f"""(() => {{
      const els = document.querySelectorAll({json.dumps(selector)});
      const el = els[{index}];
      if (!el) return 'not_found:' + els.length;
      const proto = el.tagName === 'TEXTAREA'
        ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, {json.dumps(value)});
      el.dispatchEvent(new Event('input', {{bubbles: true}}));
      el.dispatchEvent(new Event('change', {{bubbles: true}}));
      return 'ok';
    }})()"""


def js_click(text: str) -> str:
    return f"""(() => {{
      const norm = (s) => s.replace(/\\s+/g, ' ').trim();
      const target = {json.dumps(text)};
      const buttons = [...document.querySelectorAll('button')];
      const button = buttons.find((b) => norm(b.textContent).includes(target));
      if (!button) return 'not_found:' + buttons.map((b) => norm(b.textContent)).join('|');
      if (button.disabled) return 'disabled';
      button.click();
      return 'clicked';
    }})()"""


def js_click_link(text: str) -> str:
    return f"""(() => {{
      const norm = (s) => s.replace(/\\s+/g, ' ').trim();
      const target = {json.dumps(text)};
      const links = [...document.querySelectorAll('a')];
      const link = links.find((a) => norm(a.textContent).includes(target));
      if (!link) return 'not_found';
      link.click();
      return 'clicked';
    }})()"""


def body_text(page: CDP) -> str:
    return page.evaluate("document.body.innerText") or ""


def login(page: CDP, base_url: str, password: str) -> None:
    page.navigate(f"{base_url}/login")
    page.wait_for("!!document.querySelector('#password')")
    assert page.evaluate(js_set("#password", password)) == "ok"
    assert page.evaluate(js_click("登录")) == "clicked"
    try:
        page.wait_for("location.pathname === '/'", timeout=15)
        page.wait_for("document.body.innerText.includes('仓库关联')", timeout=15)
    except CDPError as exc:
        raise CDPError(
            f"login failed: href={page.evaluate('location.href')} "
            f"text={body_text(page)[:500]!r}"
        ) from exc


def link_repo(page: CDP, repo: str) -> None:
    selector = 'input[placeholder*="本地 Git 仓库"]'
    page.wait_for(f"!!document.querySelector('{selector}')")
    assert page.evaluate(js_set(selector, repo)) == "ok"
    assert page.evaluate(js_click("关联仓库")) == "clicked"
    page.wait_for("document.querySelector('.hash') && document.querySelector('.hash').textContent.length >= 40")
    page.wait_for("document.body.innerText.includes('分析基准')")


def create_task(page: CDP, title: str) -> None:
    selector = 'input[placeholder="任务标题"]'
    page.wait_for(f"!!document.querySelector('{selector}')")
    assert page.evaluate(js_set(selector, title)) == "ok"
    page.wait_for(
        "[...document.querySelectorAll('button')].some("
        "(b) => b.textContent.includes('创建任务') && !b.disabled)"
    )
    result = page.evaluate(js_click("创建任务"))
    assert result == "clicked", result
    page.wait_for("location.pathname.startsWith('/tasks/')")
    page.wait_for("document.body.innerText.includes('需求版本')")


def save_requirement(page: CDP, content: str) -> None:
    page.wait_for("!!document.querySelector('textarea')")
    assert page.evaluate(js_set("textarea", content)) == "ok"
    page.wait_for(
        "[...document.querySelectorAll('button')].some("
        "(b) => b.textContent.includes('保存为新的正式需求版本') && !b.disabled)"
    )
    assert page.evaluate(js_click("保存为新的正式需求版本")) == "clicked"
    page.wait_for("document.body.innerText.includes('已保存需求')")


def create_authorization(page: CDP, paths: str) -> None:
    page.wait_for("document.body.innerText.includes('出站授权')")
    textareas = page.evaluate(
        "[...document.querySelectorAll('textarea')].map((t) => t.placeholder || '')"
    )
    index = next(
        (i for i, placeholder in enumerate(textareas) if "src/app.py" in placeholder),
        None,
    )
    if index is None:
        raise CDPError(f"scope textarea not found: {textareas}")
    assert page.evaluate(js_set_index("textarea", index, paths)) == "ok"
    page.wait_for(
        "[...document.querySelectorAll('button')].some("
        "(b) => b.textContent.includes('创建授权') && !b.disabled)"
    )
    assert page.evaluate(js_click("创建授权")) == "clicked"
    page.wait_for(
        "document.querySelectorAll('.auth-list li').length > 0 && "
        "document.querySelector('.auth-list').innerText.includes('approved')"
    )


def start_generation(page: CDP) -> None:
    page.wait_for("document.body.innerText.includes('测试/离线模式')")
    page.wait_for("document.body.innerText.includes('离线合成生成（Mock）')")
    page.wait_for(
        "[...document.querySelectorAll('button')].some("
        "(b) => b.textContent.includes('离线合成生成（Mock）') && !b.disabled)"
    )
    assert page.evaluate(js_click("离线合成生成（Mock）")) == "clicked"
    page.wait_for("document.body.innerText.includes('completed')", timeout=30)
    page.wait_for("document.body.innerText.includes('mock（合成，非真实）')")


def approve(page: CDP) -> None:
    page.wait_for(
        "[...document.querySelectorAll('button')].some("
        "(b) => b.textContent.includes('批准此版本') && !b.disabled)",
        timeout=15,
    )
    assert page.evaluate(js_click("批准此版本")) == "clicked"
    page.wait_for("document.body.innerText.includes('已批准且有效')")


def set_baseline_available(db_path: str, task_id: int, available: int) -> None:
    """故障注入：仅操作本次临时测试数据库。"""
    with sqlite3.connect(db_path, timeout=10) as connection:
        connection.execute(
            "UPDATE analysis_baselines SET available=? "
            "WHERE id=(SELECT baseline_id FROM tasks WHERE id=?)",
            (available, task_id),
        )
        connection.commit()


def task_id_from_path(path: str) -> int:
    return int(path.rstrip("/").rsplit("/", 1)[-1])


def production_503_flow(page: CDP, base_url: str, repo: str, password: str, out_dir: Path) -> list[dict]:
    """生产模式（真实 AI 关闭）：验证 UI 阻止 + 强制点击后的 503 页面反馈。"""
    steps: list[dict] = []

    def step(name: str, ok: bool, detail: str = "") -> None:
        steps.append({"step": name, "ok": ok, "detail": detail})
        print(json.dumps(steps[-1], ensure_ascii=False))

    login(page, base_url, password)
    step("login", True)
    page.wait_for("document.body.innerText.includes('生产模式')")
    link_repo(page, repo)
    step("link_repo", True)
    create_task(page, "生产 503 验收")
    step("create_task", True)
    save_requirement(page, "生产 503 验收需求")
    step("save_requirement", True)
    create_authorization(page, "a.txt")
    step("create_authorization", True)
    page.wait_for("document.body.innerText.includes('真实 AI 未启用')")
    step("ui_blocks_real_generation", True)
    page.screenshot(out_dir / "10-production-disabled.png")
    # 故障注入：解除 DOM disabled 后点击，验证服务端 503 的真实页面反馈。
    forced = page.evaluate(
        """(() => {
          const b = [...document.querySelectorAll('button')]
            .find((x) => x.textContent.includes('发起真实生成'));
          if (!b) return 'not_found';
          b.disabled = false;
          b.click();
          return 'clicked';
        })()"""
    )
    assert forced == "clicked", forced
    page.wait_for("document.body.innerText.includes('ai_disabled')", timeout=15)
    step("503_ai_disabled_feedback", True)
    page.screenshot(out_dir / "11-503.png")
    return steps


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--repo", required=False)
    parser.add_argument("--password", default=os.environ.get("ADLL_UI_PASSWORD", ""))
    parser.add_argument("--cdp-port", type=int, default=9222)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--db", default="", help="testing SQLite path for fault injection")
    parser.add_argument("--mode", choices=["full", "503"], default="full")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    profile = Path(tempfile.mkdtemp(prefix="adll-edge-"))
    edge = start_edge(args.cdp_port, profile)
    page = None
    extra_pages: list[CDP] = []
    try:
        page = CDP(args.cdp_port)
        if args.selftest:
            page.navigate("data:text/html,<h1 id='x'>ok</h1>")
            print(json.dumps({"selftest": page.evaluate("document.querySelector('#x').textContent")}))
            return 0
        if not args.password or not args.repo:
            raise SystemExit("--password and --repo are required")
        out_dir = Path(args.out_dir) if args.out_dir else Path(tempfile.mkdtemp())
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.mode == "503":
            steps = production_503_flow(
                page, args.base_url, args.repo, args.password, out_dir
            )
            print(json.dumps({"steps": steps, "out_dir": str(out_dir)}, ensure_ascii=False))
            return 0
        steps: list[dict] = []

        def step(name: str, ok: bool, detail: str = "") -> None:
            steps.append({"step": name, "ok": ok, "detail": detail})
            print(json.dumps(steps[-1], ensure_ascii=False))

        login(page, args.base_url, args.password)
        step("login", True)
        link_repo(page, args.repo)
        step("link_repo", True, page.evaluate("document.querySelector('.hash').textContent"))
        page.screenshot(out_dir / "01-dashboard.png")
        create_task(page, "浏览器离线验收")
        step("create_task", True, page.evaluate("location.pathname"))
        task_path = page.evaluate("location.pathname")
        task_id = task_id_from_path(task_path)
        save_requirement(page, "浏览器验收需求：只发送 a.txt")
        step("save_requirement", True)
        create_authorization(page, "a.txt")
        step("create_authorization", True)
        page.screenshot(out_dir / "02-task.png")

        # 403：另一页面撤销授权，当前页面仍显示有效 → 服务端拒绝并显示反馈
        page_b = open_new_page(args.cdp_port, f"{args.base_url}{task_path}")
        extra_pages.append(page_b)
        page_b.wait_for("document.body.innerText.includes('撤销')")
        assert page_b.evaluate(js_click("撤销")) == "clicked"
        page_b.wait_for("document.body.innerText.includes('revoked')")
        page.wait_for("document.body.innerText.includes('离线合成生成（Mock）')")
        assert page.evaluate(js_click("离线合成生成（Mock）")) == "clicked"
        page.wait_for("document.body.innerText.includes('outbound_denied')", timeout=15)
        step("403_outbound_denied_feedback", True)
        page.screenshot(out_dir / "03-403.png")
        page.reload()
        page.wait_for("document.body.innerText.includes('出站授权')")

        # 重新授权后，注入基准不可用 → 423 页面反馈
        create_authorization(page, "a.txt")
        if args.db:
            set_baseline_available(args.db, task_id, 0)
        page.wait_for(
            "[...document.querySelectorAll('button')].some("
            "(b) => b.textContent.includes('离线合成生成（Mock）') && !b.disabled)"
        )
        assert page.evaluate(js_click("离线合成生成（Mock）")) == "clicked"
        page.wait_for("document.body.innerText.includes('baseline_unavailable')", timeout=15)
        step("423_baseline_unavailable_feedback", True)
        page.screenshot(out_dir / "04-423.png")
        if args.db:
            set_baseline_available(args.db, task_id, 1)
        page.reload()
        page.wait_for("document.body.innerText.includes('离线合成生成（Mock）')")

        start_generation(page)
        step("mock_generation", True)
        page.wait_for("document.body.innerText.includes('v1')")
        page.wait_for(
            "[...document.querySelectorAll('button')].some("
            "(b) => b.textContent.includes('批准此版本') && !b.disabled)",
            timeout=20,
        )

        # 409：另一页面先批准；当前页面仍显示可批准 → 服务端 409 反馈
        page_c = open_new_page(args.cdp_port, f"{args.base_url}{task_path}")
        extra_pages.append(page_c)
        page_c.wait_for(
            "[...document.querySelectorAll('button')].some("
            "(b) => b.textContent.includes('批准此版本') && !b.disabled)",
            timeout=20,
        )
        approve(page_c)
        assert page.evaluate(js_click("批准此版本")) == "clicked"
        page.wait_for("document.body.innerText.includes('approval_exists')", timeout=15)
        step("409_approval_exists_feedback", True)
        page.screenshot(out_dir / "05-409.png")
        page.reload()
        page.wait_for("document.body.innerText.includes('已批准且有效')")
        step("approve", True)
        page.screenshot(out_dir / "06-approved.png")

        # 刷新后恢复
        page.reload()
        page.wait_for("document.body.innerText.includes('已批准且有效')")
        page.wait_for("document.body.innerText.includes('v1')")
        step("reload_restores_state", True)

        # 修改需求 → 旧审批失效
        save_requirement(page, "浏览器验收需求 v2")
        page.wait_for("document.body.innerText.includes('曾批准但已失效')")
        step("requirement_change_invalidates_approval", True)
        page.screenshot(out_dir / "07-invalidated.png")

        # 撤销授权
        assert page.evaluate(js_click("撤销")) == "clicked"
        page.wait_for("document.body.innerText.includes('revoked')")
        step("revoke_authorization", True)

        # 401：清 Cookie 后访问任务页 → 登录页
        page.send("Network.clearBrowserCookies")
        page.navigate(f"{args.base_url}/tasks/1")
        page.wait_for("location.pathname === '/login'")
        step("401_redirects_to_login", True, page.evaluate("location.pathname"))

        print(json.dumps({"steps": steps, "out_dir": str(out_dir)}, ensure_ascii=False))
        return 0
    finally:
        for extra in extra_pages:
            extra.close()
        if page is not None:
            page.close()
        edge.terminate()
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())