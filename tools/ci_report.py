"""整理 GitHub Actions 這一次執行的結果（由 tools/ci.sh 呼叫）。

產出：
  web/data/status.json       網站讀取：上次資料更新時間、哪些步驟失敗（網頁的「☰ → 問題回報」會顯示）
  logs/ci/latest.md          這次的摘要＋失敗步驟的最後幾十行輸出（存回專案，git pull 後在本機就看得到）
  logs/ci/history/*.md       最近 40 次的摘要
有步驟失敗時：在 GitHub 開一張標籤為「自動回報」的 Issue（已有未關閉的就在下面留言），GitHub 會寄信通知。
必要步驟（情資匯出、資料檢查）失敗時結束代碼為 1，這次就不部署，網站維持上一版。
"""
import datetime
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "ci")
TAIL = 60


def tail(path, n=TAIL):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return "(沒有輸出紀錄)"
    return "\n".join(lines[-n:])


def run_url():
    s, r, i = os.environ.get("GITHUB_SERVER_URL"), os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    return "%s/%s/actions/runs/%s" % (s, r, i) if s and r and i else ""


def data_summary():
    try:
        with open(os.path.join(ROOT, "web", "data", "tw", "index.json"), encoding="utf-8") as f:
            idx = json.load(f)
    except (OSError, ValueError):
        return {"mode": "台南版（沒有全台資料）"}
    cs = idx.get("counties", [])
    return {"mode": "全台版", "as_of": idx.get("as_of"), "complete_through": idx.get("complete_through"),
            "tx_count": idx.get("tx_count"), "counties_with_data": sum(1 for c in cs if c.get("has_data")),
            "road_districts": sum(len(c.get("roads", [])) for c in cs),
            "town_districts": sum(c.get("towns", 0) for c in cs),
            "missing": [c["short"] for c in cs if not c.get("has_data")]}


def gh(*args, input_text=None):
    try:
        r = subprocess.run(["gh", *args], input=input_text, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def report_issue(title, body):
    """有未關閉的「自動回報」Issue 就留言，沒有就開新的。需要環境變數 GH_TOKEN（workflow 會給）。"""
    if not os.environ.get("GH_TOKEN"):
        print("沒有 GH_TOKEN，略過開 Issue")
        return
    gh("label", "create", "自動回報", "--color", "d93f0b", "--description", "GitHub Actions 自動回報的錯誤", "--force")
    rc, out, err = gh("issue", "list", "--label", "自動回報", "--state", "open", "--json", "number", "--jq", ".[0].number")
    if rc == 0 and out:
        rc, out, err = gh("issue", "comment", out, "--body-file", "-", input_text=body)
    else:
        rc, out, err = gh("issue", "create", "--title", title, "--label", "自動回報", "--body-file", "-", input_text=body)
    print("Issue：", out or err)


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    steps = []
    try:
        with open(os.path.join(LOG, "steps.tsv"), encoding="utf-8") as f:
            for line in f:
                sid, title, rc, secs, must = line.rstrip("\n").split("\t")
                steps.append({"id": sid, "title": title, "ok": rc == "0", "code": int(rc), "seconds": int(secs), "required": must == "1"})
    except OSError:
        pass
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    failed = [s for s in steps if not s["ok"]]
    data = data_summary()
    status = {"time": now.strftime("%Y-%m-%d %H:%M"), "event": event, "run_url": run_url(),
              "commit": (os.environ.get("GITHUB_SHA") or "")[:7], "ok": not failed,
              "failed": [s["title"] for s in failed], "steps": steps, "data": data}
    os.makedirs(os.path.join(ROOT, "web", "data"), exist_ok=True)
    with open(os.path.join(ROOT, "web", "data", "status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)

    md = ["# 資料更新紀錄 %s" % status["time"], "",
          "- 觸發：%s　commit：%s" % (event, status["commit"]),
          "- 結果：%s" % ("全部成功" if not failed else "失敗 %d 步：%s" % (len(failed), "、".join(s["title"] for s in failed))),
          "- 執行紀錄：%s" % (status["run_url"] or "（本機執行）"),
          "- 資料：%s" % json.dumps(data, ensure_ascii=False), "",
          "| 步驟 | 結果 | 秒 |", "|---|---|---|"]
    md += ["| %s | %s | %d |" % (s["title"], "成功" if s["ok"] else "**失敗（%d）**" % s["code"], s["seconds"]) for s in steps]
    for s in failed:
        md += ["", "## %s 的最後 %d 行輸出" % (s["title"], TAIL), "", "```", tail(os.path.join(LOG, "raw", s["id"] + ".log")), "```"]
    text = "\n".join(md) + "\n"
    with open(os.path.join(LOG, "latest.md"), "w", encoding="utf-8") as f:
        f.write(text)
    hist = os.path.join(LOG, "history")
    os.makedirs(hist, exist_ok=True)
    with open(os.path.join(hist, "%s_%s.md" % (now.strftime("%Y%m%d-%H%M"), os.environ.get("GITHUB_RUN_ID", "local"))), "w", encoding="utf-8") as f:
        f.write(text)
    for old in sorted(os.listdir(hist))[:-40]:
        os.remove(os.path.join(hist, old))
    print(text)
    if failed:
        report_issue("自動回報：資料更新有步驟失敗（%s）" % now.strftime("%Y-%m-%d"), text[:60000])
    if any(s["required"] for s in failed):
        sys.exit(1)


if __name__ == "__main__":
    main()
