import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def config_path() -> Path:
    root = Path(os.environ.get("APPDATA", Path.home() / ".config"))
    folder = root / "AgentDock"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "config.json"


def read_config() -> dict:
    path = config_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"url": "http://localhost:8000", "token": ""}


def write_config(value: dict) -> None:
    path = config_path()
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def call(method: str, path: str, data: dict | None = None, *, token: str = "", base: str = ""):
    config = read_config()
    root = base.rstrip("/") or config["url"].rstrip("/")
    headers = {"Accept": "application/json"}
    if token or config.get("token"):
        headers["Authorization"] = f"Bearer {token or config['token']}"
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    request = Request(root + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as error:
        try:
            message = json.loads(error.read().decode()).get("detail", f"Request failed ({error.code})")
        except Exception:
            message = f"Request failed ({error.code})"
        raise RuntimeError(message) from None
    except URLError as error:
        raise RuntimeError(f"Could not reach AgentDock: {error.reason}") from None


def download(path: str) -> bytes:
    config = read_config()
    request = Request(config["url"].rstrip("/") + path,
                      headers={"Authorization": "Bearer " + config.get("token", "")})
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except HTTPError as error:
        try:
            message = json.loads(error.read().decode()).get("detail", f"Request failed ({error.code})")
        except Exception:
            message = f"Request failed ({error.code})"
        raise RuntimeError(message) from None
    except URLError as error:
        raise RuntimeError(f"Could not reach AgentDock: {error.reason}") from None


def print_table(rows: list[dict], columns: list[tuple[str, str]]) -> None:
    if not rows:
        print("Nothing to show.")
        return
    widths = {key: len(label) for key, label in columns}
    for row in rows:
        for key, _label in columns:
            widths[key] = max(widths[key], len(str(row.get(key, ""))))
    print("  ".join(label.ljust(widths[key]) for key, label in columns))
    print("  ".join("-" * widths[key] for key, _label in columns))
    for row in rows:
        print("  ".join(str(row.get(key, "")).ljust(widths[key]) for key, _label in columns))


def main() -> None:
    parser = argparse.ArgumentParser(prog="agentdock", description="Search and retrieve AgentDock skills on demand")
    sub = parser.add_subparsers(dest="command", required=True)
    login = sub.add_parser("login", help="Connect this CLI to your AgentDock account")
    login.add_argument("--url", default="http://localhost:8000")
    login.add_argument("--email")
    login.add_argument("--password")
    sub.add_parser("logout", help="Remove the saved AgentDock connection")
    search = sub.add_parser("search", help="Search the curated skill catalogue")
    search.add_argument("query", nargs="*", default=[])
    search.add_argument("--limit", type=int, default=20)
    skills = sub.add_parser("skills", help="List approved skills")
    skills.add_argument("--limit", type=int, default=20)
    get = sub.add_parser("get", help="Retrieve a skill and its instructions")
    get.add_argument("skill")
    get.add_argument("--output", type=Path)
    sub.add_parser("collections", help="List your saved collections")
    sub.add_parser("plans", help="List published subscription plans")
    subscribe = sub.add_parser("subscribe", help="Create a subscription checkout")
    subscribe.add_argument("--plan", required=True)
    subscribe.add_argument("--interval", choices=["month", "year"], default="month")
    subscribe.add_argument("--team", default="")
    sub.add_parser("billing", help="Show your subscription, payments and purchases")
    marketplace = sub.add_parser("marketplace", help="Browse marketplace listings")
    marketplace.add_argument("--limit", type=int, default=20)
    purchase = sub.add_parser("purchase", help="Purchase a marketplace listing")
    purchase.add_argument("listing")
    purchase.add_argument("--team", default="")
    sub.add_parser("teams", help="List teams and workspaces")
    invite = sub.add_parser("invite", help="Invite a teammate to a team")
    invite.add_argument("--team", required=True)
    invite.add_argument("--email", required=True)
    invite.add_argument("--role", choices=["admin", "member"], default="member")
    connect = sub.add_parser("connect", help="Print an MCP connection configuration")
    connect.add_argument("integration", choices=["mcp"])
    sub.add_parser("config", help="Show the configured AgentDock server")
    sub.add_parser("status", help="Check the AgentDock connection")
    sub.add_parser("doctor", help="Check the server, database and catalogue health")
    sub.add_parser("update", help="Show the installed AgentDock CLI version")
    args = parser.parse_args()
    try:
        if args.command == "login":
            email = args.email or input("Email: ").strip()
            password = args.password or getpass.getpass("Password: ")
            token = call("POST", "/api/v1/auth/token", {"email": email, "password": password}, base=args.url)["access_token"]
            write_config({"url": args.url.rstrip("/"), "token": token})
            print("AgentDock connected. Your API key is stored in your local user configuration.")
        elif args.command == "logout":
            write_config({"url": read_config()["url"], "token": ""})
            print("AgentDock credentials removed.")
        elif args.command == "config":
            print(json.dumps({"url": read_config()["url"], "connected": bool(read_config().get("token"))}, indent=2))
        elif args.command == "status":
            result = call("GET", "/api/v1/auth/me")
            print(f"Connected as {result['user']['email']} ({result['user']['role']}).")
        elif args.command == "doctor":
            health = call("GET", "/api/health")
            plans = call("GET", "/api/v1/plans")
            print(json.dumps({"health": health, "plans": len(plans.get("items", [])),
                              "billing": plans.get("billing", {})}, indent=2))
        elif args.command == "search" or args.command == "skills":
            q = " ".join(args.query) if args.command == "search" else ""
            limit = min(max(getattr(args, "limit", 20), 1), 50)
            result = call("GET", f"/api/v1/skills/search?q={quote(q)}&limit={limit}")
            print_table([{"slug": item["slug"], "name": item["name"], "category": item["category"],
                           "license": item["license"], "price": item["price_cents"] or "Free"}
                          for item in result["items"]],
                        [("slug", "SLUG"), ("name", "NAME"), ("category", "CATEGORY"),
                         ("license", "LICENCE"), ("price", "PRICE")])
            if not result["items"]:
                print("No matching skills found.")
        elif args.command == "get":
            result = call("POST", f"/api/v1/skills/{quote(args.skill)}/retrieve", {})
            skill = result["skill"]
            if args.output:
                args.output.mkdir(parents=True, exist_ok=True)
                for item in result["resource_manifest"]:
                    rel = Path(item["path"])
                    if rel.is_absolute() or ".." in rel.parts:
                        raise RuntimeError("Unsafe path in skill manifest")
                    content = download(f"/api/v1/skills/{quote(skill['id'])}/resources/{quote(item['path'], safe='/')}?version={quote(result['version'])}")
                    destination = args.output / rel
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                print(f"Retrieved {skill['name']} v{result['version']} into {args.output}")
            else:
                print(skill["instructions"])
        elif args.command == "collections":
            print(json.dumps(call("GET", "/api/v1/user/library"), indent=2))
        elif args.command == "plans":
            result = call("GET", "/api/v1/plans")
            print_table([{"code": plan["code"], "name": plan["name"],
                           "monthly": plan["price_cents"] or "Free",
                           "annual": plan["annual_price_cents"] or "—",
                           "members": plan["member_limit"]} for plan in result["items"]],
                        [("code", "CODE"), ("name", "NAME"), ("monthly", "MONTHLY"), ("annual", "ANNUAL"), ("members", "MEMBERS")])
            if not result["items"]:
                print("No plans published.")
        elif args.command == "subscribe":
            payload = {"plan_code": args.plan, "interval": args.interval}
            if args.team:
                payload["team_id"] = args.team
            result = call("POST", "/api/v1/account/subscription/checkout", payload)
            print(json.dumps(result, indent=2))
            if result.get("checkout_url"):
                print(f"Open the checkout URL to complete payment: {result['checkout_url']}")
        elif args.command == "billing":
            result = call("GET", "/api/v1/account/billing")
            print(json.dumps(result, indent=2))
        elif args.command == "marketplace":
            result = call("GET", f"/api/v1/marketplace/listings?limit={min(max(args.limit, 1), 50)}")
            print_table([{"title": item["title"], "creator": item["creator"],
                           "price": item["price_cents"] or "Free", "rating": item["rating"] or "—",
                           "listing": item["id"]} for item in result["items"]],
                        [("title", "TITLE"), ("creator", "CREATOR"), ("price", "PRICE"),
                         ("rating", "RATING"), ("listing", "LISTING ID")])
        elif args.command == "purchase":
            payload = {"listing_id": args.listing}
            if args.team:
                payload["team_id"] = args.team
            result = call("POST", "/api/v1/marketplace/purchases", payload)
            print(json.dumps(result, indent=2))
            if result.get("checkout_url"):
                print(f"Open the checkout URL to complete payment: {result['checkout_url']}")
        elif args.command == "teams":
            result = call("GET", "/api/v1/teams")
            print_table([{"name": team["name"], "plan": team["plan_name"],
                           "members": f"{team['member_count']}/{team['seat_limit']}",
                           "role": team["role"]} for team in result["items"]],
                        [("name", "TEAM"), ("plan", "PLAN"), ("members", "SEATS"), ("role", "ROLE")])
        elif args.command == "invite":
            result = call("POST", f"/api/v1/teams/{quote(args.team)}/invitations",
                          {"email": args.email, "role": args.role})
            print(json.dumps(result, indent=2))
            print(f"Share this one-time invitation link: {result.get('invite_link', '')}")
        elif args.command == "connect":
            config = read_config()
            print(json.dumps({"mcpServers": {"agentdock": {"url": config["url"].rstrip("/") + "/mcp",
                  "headers": {"Authorization": "Bearer <your AgentDock API key>"}}}}, indent=2))
        elif args.command == "update":
            from importlib.metadata import version, PackageNotFoundError
            try:
                print(f"AgentDock CLI {version('agentdock')}")
            except PackageNotFoundError:
                print("AgentDock CLI is running from a source checkout.")
    except (RuntimeError, KeyError) as error:
        print(f"agentdock: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
