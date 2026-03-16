#!/usr/bin/env python3
"""
Apps Script Deployer Lite — scaffold + deploy Apps Script chuẩn.

Usage:
    python3 deploy.py scaffold --template daily-report --name "My Report"
    python3 deploy.py deploy --project-dir ./output/my-report
    python3 deploy.py verify --script-id abc123
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output"

# Workspace paths for credentials (used when deployed on VPS)
WORKSPACE = Path("/root/.openclaw/workspace")
TOKEN_FILE = WORKSPACE / "credentials" / "google_workspace_token.json"
CREDS_FILE = WORKSPACE / "credentials" / "google_workspace_credentials.json"
APPS_SCRIPT_API = "https://script.googleapis.com/v1/projects"

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
TEMPLATES = {
    "daily-report": {
        "description": "Báo cáo tự động hàng ngày gửi email",
        "files": {
            "Code.gs": '''\
function sendDailyReport() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var data = sheet.getDataRange().getValues();

  var subject = "Daily Report - " + Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "dd/MM/yyyy");
  var body = "Dữ liệu hôm nay:\\n\\n";

  for (var i = 1; i < data.length; i++) {
    body += data[i].join(" | ") + "\\n";
  }

  MailApp.sendEmail({
    to: Session.getEffectiveUser().getEmail(),
    subject: subject,
    body: body
  });

  Logger.log("Report sent: " + subject);
}

function createTrigger() {
  ScriptApp.newTrigger("sendDailyReport")
    .timeBased()
    .everyDays(1)
    .atHour(8)
    .create();
}
''',
            "appsscript.json": json.dumps({
                "timeZone": "Asia/Ho_Chi_Minh",
                "dependencies": {},
                "exceptionLogging": "STACKDRIVER",
                "runtimeVersion": "V8"
            }, indent=2, ensure_ascii=False),
        }
    },
    "data-sync": {
        "description": "Sync data từ Sheet sang Sheet hoặc API",
        "files": {
            "Code.gs": '''\
function syncData() {
  var sourceSheet = SpreadsheetApp.openById("SOURCE_SHEET_ID").getActiveSheet();
  var targetSheet = SpreadsheetApp.openById("TARGET_SHEET_ID").getActiveSheet();

  var data = sourceSheet.getDataRange().getValues();

  targetSheet.clear();
  targetSheet.getRange(1, 1, data.length, data[0].length).setValues(data);

  Logger.log("Synced " + data.length + " rows");
}
''',
            "appsscript.json": json.dumps({
                "timeZone": "Asia/Ho_Chi_Minh",
                "dependencies": {},
                "exceptionLogging": "STACKDRIVER",
                "runtimeVersion": "V8"
            }, indent=2, ensure_ascii=False),
        }
    },
    "trigger-setup": {
        "description": "Setup time-driven trigger cho script",
        "files": {
            "Code.gs": '''\
function setupTriggers() {
  // Xoá trigger cũ
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    ScriptApp.deleteTrigger(triggers[i]);
  }

  // Tạo trigger mới
  ScriptApp.newTrigger("mainFunction")
    .timeBased()
    .everyHours(1)
    .create();

  Logger.log("Trigger created: mainFunction every 1 hour");
}

function mainFunction() {
  Logger.log("Main function executed at " + new Date());
  // TODO: Add your logic here
}
''',
            "appsscript.json": json.dumps({
                "timeZone": "Asia/Ho_Chi_Minh",
                "dependencies": {},
                "exceptionLogging": "STACKDRIVER",
                "runtimeVersion": "V8"
            }, indent=2, ensure_ascii=False),
        }
    }
}


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_scaffold(template_name: str, project_name: str):
    """Tạo project folder từ template."""
    if template_name not in TEMPLATES:
        print(f"❌ Template '{template_name}' không tồn tại.")
        print(f"Templates có sẵn: {', '.join(TEMPLATES.keys())}")
        return False

    template = TEMPLATES[template_name]
    safe_name = project_name.lower().replace(" ", "-")
    project_dir = OUTPUT_DIR / safe_name

    project_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in template["files"].items():
        filepath = project_dir / filename
        filepath.write_text(content, encoding="utf-8")
        print(f"  ✅ Created: {filepath}")

    # Write metadata
    metadata = {
        "template": template_name,
        "name": project_name,
        "description": template["description"],
    }
    (project_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n✅ Project scaffolded: {project_dir}")
    return True


def _load_google_credentials():
    """Load and refresh Google OAuth2 credentials. Returns (creds, requests_module) or raises."""
    try:
        import requests as req_mod
        from google.oauth2.credentials import Credentials
        import google.auth.transport.requests as google_requests
    except ImportError as e:
        raise ImportError(
            f"Missing dependency: {e}\n"
            f"Install: pip install google-auth requests"
        )

    if not TOKEN_FILE.exists():
        raise FileNotFoundError(f"Token file not found: {TOKEN_FILE}")
    if not CREDS_FILE.exists():
        raise FileNotFoundError(f"Credentials file not found: {CREDS_FILE}")

    token_data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    creds_data = json.loads(CREDS_FILE.read_text(encoding="utf-8"))

    # Determine client config location (installed or web)
    client_config = creds_data.get("installed", creds_data.get("web", {}))
    if not client_config:
        raise ValueError("Invalid credentials file: missing 'installed' or 'web' key")

    # Compute expiry from token schema
    expiry = None
    updated_at_str = token_data.get("updated_at")
    expires_in = token_data.get("expires_in", 3600)
    if updated_at_str:
        try:
            updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
            expiry = updated_at + timedelta(seconds=int(expires_in))
        except (ValueError, TypeError):
            pass  # Will attempt refresh on 401

    creds = Credentials(
        token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_config.get("client_id"),
        client_secret=client_config.get("client_secret"),
        scopes=token_data.get("scope", "").split(),
        expiry=expiry,
    )

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(google_requests.Request())
            # Save updated token
            token_data["access_token"] = creds.token
            token_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            TOKEN_FILE.write_text(json.dumps(token_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"⚠️ Token refresh failed: {e}")
            print("  Will attempt API call with existing token...")

    return creds, req_mod


def _api_call(method, url, creds, req_mod, json_body=None):
    """Make authenticated API call with 401 retry."""
    import google.auth.transport.requests as google_requests

    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    kwargs = {"headers": headers, "timeout": 30}
    if json_body:
        kwargs["json"] = json_body

    resp = getattr(req_mod, method.lower())(url, **kwargs)

    # Retry once on 401 (token may have just expired)
    if resp.status_code == 401 and creds.refresh_token:
        try:
            creds.refresh(google_requests.Request())
            headers["Authorization"] = f"Bearer {creds.token}"
            kwargs["headers"] = headers
            resp = getattr(req_mod, method.lower())(url, **kwargs)
        except Exception:
            pass  # Return the 401 response

    return resp


def cmd_deploy(project_dir: str):
    """Deploy project lên Google Apps Script API."""
    project_path = Path(project_dir)
    if not project_path.exists():
        print(f"❌ Project directory không tồn tại: {project_dir}")
        return False

    # Read project files (only .gs and .json, skip directories and metadata)
    _SUPPORTED_TYPES = {".gs": "SERVER_JS", ".json": "JSON", ".html": "HTML"}
    files = []
    for f in project_path.glob("*"):
        if not f.is_file() or f.name == "metadata.json":
            continue
        file_type = _SUPPORTED_TYPES.get(f.suffix)
        if file_type is None:
            print(f"  ⚠️ Skipping unsupported file: {f.name}")
            continue
        files.append({"name": f.stem, "type": file_type,
                       "source": f.read_text(encoding="utf-8")})

    if not files:
        print("❌ Không tìm thấy files trong project")
        return False

    # Read project name from metadata
    metadata_path = project_path / "metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        project_name = metadata.get("name", project_path.name)
    else:
        project_name = project_path.name

    # Load credentials (lazy import)
    try:
        creds, req_mod = _load_google_credentials()
    except (ImportError, FileNotFoundError, ValueError) as e:
        print(f"❌ {e}")
        return False

    print(f"📦 Deploying {len(files)} files as '{project_name}'...")

    # Step 1: Create project
    resp = _api_call("post", APPS_SCRIPT_API, creds, req_mod, json_body={"title": project_name})

    if resp.status_code == 401:
        print("❌ Authentication failed (401).")
        print("  Token có thể thiếu scope 'https://www.googleapis.com/auth/script.projects'")
        print("  → Re-auth: thêm scope script.projects vào OAuth consent rồi lấy token mới")
        return False
    elif resp.status_code == 403:
        print("❌ Permission denied (403).")
        print("  Kiểm tra: Apps Script API đã enable trong Google Cloud Console chưa?")
        print("  Kiểm tra: Token có scope script.projects không?")
        return False
    elif resp.status_code not in (200, 201):
        print(f"❌ Create project failed ({resp.status_code}): {resp.text[:300]}")
        return False

    result = resp.json()
    script_id = result.get("scriptId")
    print(f"  ✅ Project created: scriptId = {script_id}")

    # Step 2: Upload files
    upload_url = f"{APPS_SCRIPT_API}/{script_id}/content"
    resp = _api_call("put", upload_url, creds, req_mod, json_body={"files": files})

    if resp.status_code == 401:
        print("❌ Upload failed: Authentication error (401)")
        print(f"  Script was created (ID: {script_id}) but files not uploaded.")
        return False
    elif resp.status_code not in (200, 201):
        print(f"❌ Upload failed ({resp.status_code}): {resp.text[:300]}")
        print(f"  Script was created (ID: {script_id}) but files not uploaded.")
        return False

    print(f"  ✅ Uploaded {len(files)} files")
    print(f"\n✅ Deployed: script_id = {script_id}")
    print(f"  Open: https://script.google.com/d/{script_id}/edit")
    return True


def cmd_verify(script_id: str):
    """Verify deployment status."""
    # Load credentials (lazy import)
    try:
        creds, req_mod = _load_google_credentials()
    except (ImportError, FileNotFoundError, ValueError) as e:
        print(f"❌ {e}")
        return False

    print(f"🔍 Checking script: {script_id}")

    # Get project metadata
    resp = _api_call("get", f"{APPS_SCRIPT_API}/{script_id}", creds, req_mod)

    if resp.status_code == 401:
        print("❌ Authentication failed (401).")
        print("  Token có thể thiếu scope 'https://www.googleapis.com/auth/script.projects'")
        return False
    elif resp.status_code == 403:
        print("❌ Permission denied (403). Kiểm tra scope và API enabled.")
        return False
    elif resp.status_code == 404:
        print(f"❌ Script not found: {script_id}")
        return False
    elif resp.status_code != 200:
        print(f"❌ API error ({resp.status_code}): {resp.text[:300]}")
        return False

    data = resp.json()
    print(f"  📌 Title: {data.get('title', 'N/A')}")
    print(f"  🆔 Script ID: {data.get('scriptId', script_id)}")
    print(f"  📅 Created: {data.get('createTime', 'N/A')}")
    print(f"  🔄 Updated: {data.get('updateTime', 'N/A')}")

    # Check deployments
    deploy_resp = _api_call("get", f"{APPS_SCRIPT_API}/{script_id}/deployments", creds, req_mod)
    if deploy_resp.status_code == 200:
        deployments = deploy_resp.json().get("deployments", [])
        if deployments:
            print(f"\n  📦 Deployments ({len(deployments)}):")
            for d in deployments:
                config = d.get("deploymentConfig", {})
                print(f"    • {d.get('deploymentId', 'N/A')} — "
                      f"version: {config.get('versionNumber', 'HEAD')} | "
                      f"description: {config.get('description', 'N/A')}")
        else:
            print("\n  📦 No deployments found (only HEAD version)")
    else:
        print(f"\n  ⚠️ Could not fetch deployments ({deploy_resp.status_code})")

    return True


def cmd_list_templates():
    """List available templates."""
    print("📋 Available templates:\n")
    for name, tmpl in TEMPLATES.items():
        print(f"  • {name}: {tmpl['description']}")
    print(f"\nUsage: python3 deploy.py scaffold --template <name> --name \"Project Name\"")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Apps Script Deployer Lite")
    subparsers = parser.add_subparsers(dest="command")

    # scaffold
    p_scaffold = subparsers.add_parser("scaffold", help="Scaffold project from template")
    p_scaffold.add_argument("--template", required=True, help="Template name")
    p_scaffold.add_argument("--name", required=True, help="Project name")

    # deploy
    p_deploy = subparsers.add_parser("deploy", help="Deploy project to Google")
    p_deploy.add_argument("--project-dir", required=True, help="Path to project directory")

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify deployment")
    p_verify.add_argument("--script-id", required=True, help="Google Script ID")

    # list
    subparsers.add_parser("list", help="List available templates")

    args = parser.parse_args()

    if args.command == "scaffold":
        cmd_scaffold(args.template, args.name)
    elif args.command == "deploy":
        cmd_deploy(args.project_dir)
    elif args.command == "verify":
        cmd_verify(args.script_id)
    elif args.command == "list":
        cmd_list_templates()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
