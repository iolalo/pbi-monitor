import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone

TENANT_ID       = os.environ["PBI_TENANT_ID"]
CLIENT_ID       = os.environ["PBI_CLIENT_ID"]
REFRESH_TOKEN   = os.environ["PBI_REFRESH_TOKEN"]
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

BASE = "https://api.powerbi.com/v1.0/myorg"
INACTIVE_DAYS = 30


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_access_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    resp = requests.post(url, data={
        "grant_type":    "refresh_token",
        "client_id":     CLIENT_ID,
        "refresh_token": REFRESH_TOKEN,
        "scope":         "https://analysis.windows.net/powerbi/api/.default offline_access",
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def pbi(token, path, params=None):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{BASE}{path}", headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


# ── Power BI fetchers ─────────────────────────────────────────────────────────

def fetch_workspaces(token):
    data = pbi(token, "/admin/groups", {
        "$top": 100,
        "$expand": "users,reports,datasets",
    })
    return data.get("value", [])


def fetch_activity(token, days=30):
    events = []
    for i in range(days):
        day = (datetime.now(timezone.utc) - timedelta(days=i + 1)).strftime("%Y-%m-%d")
        try:
            data = pbi(token, "/admin/activityevents", {
                "startDateTime": f"'{day}T00:00:00.000Z'",
                "endDateTime":   f"'{day}T23:59:59.999Z'",
            })
            events.extend(data.get("activityEventEntities", []))
        except Exception as e:
            print(f"  Warning — activity {day}: {e}")
        time.sleep(0.3)
    return events


# ── Processing ────────────────────────────────────────────────────────────────

def process(workspaces, activity):
    report_views = {}
    report_unique_users = {}
    user_last_seen = {}

    for ev in activity:
        if ev.get("Activity") != "ViewReport":
            continue
        rid  = ev.get("ReportId", "")
        uid  = (ev.get("UserId") or "").lower()
        ts   = ev.get("CreationTime", "")

        report_views[rid] = report_views.get(rid, 0) + 1
        report_unique_users.setdefault(rid, set()).add(uid)
        if ts > user_last_seen.get(uid, ""):
            user_last_seen[uid] = ts

    cutoff = (datetime.now(timezone.utc) - timedelta(days=INACTIVE_DAYS)).isoformat()

    ws_out = []
    all_users = {}

    for ws in workspaces:
        reports  = ws.get("reports", [])
        datasets = ws.get("datasets", [])
        users    = ws.get("users", [])

        for r in reports:
            rid = r.get("id", "")
            r["views_30d"]        = report_views.get(rid, 0)
            r["unique_users_30d"] = len(report_unique_users.get(rid, set()))

        for u in users:
            email = (u.get("emailAddress") or "").lower()
            last  = user_last_seen.get(email, "")
            u["last_activity"] = last
            u["is_active"]     = bool(last) and last >= cutoff
            all_users[email]   = u

        ws_out.append({
            "id":            ws["id"],
            "name":          ws["name"],
            "type":          ws.get("type", "Workspace"),
            "state":         ws.get("state", ""),
            "report_count":  len(reports),
            "dataset_count": len(datasets),
            "user_count":    len(users),
            "reports":       sorted(reports, key=lambda r: r["views_30d"], reverse=True),
            "datasets":      datasets,
            "users":         users,
        })

    total_reports   = sum(w["report_count"] for w in ws_out)
    active_users    = sum(1 for u in all_users.values() if u["is_active"])
    inactive_users  = len(all_users) - active_users
    unused_reports  = sum(1 for ws in ws_out for r in ws["reports"] if r["views_30d"] == 0)

    top_reports = sorted(
        [{"id": k, "views": v} for k, v in report_views.items()],
        key=lambda x: x["views"], reverse=True
    )[:10]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_workspaces":  len(ws_out),
            "total_reports":     total_reports,
            "total_users":       len(all_users),
            "active_users":      active_users,
            "inactive_users":    inactive_users,
            "unused_reports":    unused_reports,
            "top_reports":       top_reports,
        },
        "workspaces": ws_out,
        "all_users":  list(all_users.values()),
    }


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(msg):
    if not TELEGRAM_TOKEN:
        return
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
        timeout=10,
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("🔑 Autenticando...")
    token = get_access_token()

    print("🗂  Obteniendo workspaces...")
    workspaces = fetch_workspaces(token)
    print(f"   → {len(workspaces)} workspaces")

    print("📈 Obteniendo actividad (últimos 30 días)...")
    activity = fetch_activity(token, days=30)
    print(f"   → {len(activity)} eventos")

    print("⚙️  Procesando datos...")
    output = process(workspaces, activity)
    s = output["summary"]

    os.makedirs("docs/data", exist_ok=True)
    with open("docs/data/data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ data.json guardado")
    print(f"   Workspaces: {s['total_workspaces']} | Reportes: {s['total_reports']} | Usuarios: {s['total_users']}")
    print(f"   Activos: {s['active_users']} | Inactivos: {s['inactive_users']} | Sin uso: {s['unused_reports']}")

    today = datetime.now().strftime("%d/%m/%Y")
    msg = (
        f"📊 <b>PBI Monitor — {today}</b>\n\n"
        f"🗂 Workspaces: <b>{s['total_workspaces']}</b>\n"
        f"📋 Reportes totales: <b>{s['total_reports']}</b>\n"
        f"👥 Usuarios únicos: <b>{s['total_users']}</b>\n"
        f"✅ Activos (30d): <b>{s['active_users']}</b>\n"
        f"💤 Inactivos (30d): <b>{s['inactive_users']}</b>\n"
        f"🚫 Reportes sin uso (30d): <b>{s['unused_reports']}</b>"
    )
    send_telegram(msg)
    print("📨 Telegram notificado")


if __name__ == "__main__":
    main()
