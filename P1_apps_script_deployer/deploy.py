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

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output"

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


def cmd_deploy(project_dir: str):
    """Deploy project lên Google Apps Script API."""
    project_path = Path(project_dir)
    if not project_path.exists():
        print(f"❌ Project directory không tồn tại: {project_dir}")
        return False

    # Read project files
    files = []
    for f in project_path.glob("*"):
        if f.name == "metadata.json":
            continue
        files.append({"name": f.stem, "type": "SERVER_JS" if f.suffix == ".gs" else "JSON",
                       "source": f.read_text(encoding="utf-8")})

    if not files:
        print("❌ Không tìm thấy files trong project")
        return False

    # TODO: Call Google Apps Script API to create/update project
    # Needs credentials/google_workspace_token.json
    print(f"📦 Ready to deploy {len(files)} files")
    print("⚠️ Deploy API chưa implement — cần Google Workspace OAuth credentials")
    return True


def cmd_verify(script_id: str):
    """Verify deployment status."""
    # TODO: Call Apps Script API to check project status
    print(f"🔍 Checking script: {script_id}")
    print("⚠️ Verify API chưa implement")
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
