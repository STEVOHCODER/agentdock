from backend.agentdock.db import SessionLocal
from backend.agentdock.models import Skill, SkillVersion, utcnow
from backend.agentdock.vault import save_snapshot

FILES = {
    "SKILL.md": b"---\nname: qa-execution-probes\ndescription: Controlled QA skill for execution bridge validation.\n---\nRun the scripts in this package for isolated execution validation.\n",
    "requirements.lock.txt": b"requests==2.32.3\n",
    "scripts/deps_probe.py": b"import os, requests\nprint('REQUESTS_VERSION', requests.__version__)\nprint('PYTHONPATH', os.environ.get('PYTHONPATH',''))\n",
    "scripts/probe_secrets.py": (
        "import os\n"
        "for key in sorted(os.environ):\n"
        "    if any(word in key.upper() for word in ['SECRET','PASSWORD','TOKEN','KEY','DATABASE']):\n"
        "        print('ENV_NAME', key)\n"
        "for path in ['/app/.env','/opt/agentdock/.env','/proc/1/environ','/var/run/docker.sock','/etc/passwd']:\n"
        "    try:\n"
        "        open(path,'rb').read(1)\n"
        "        print('READ_OK', path)\n"
        "    except Exception as exc:\n"
        "        print('READ_FAIL', path, type(exc).__name__)\n"
        "print('CWD', os.getcwd())\n"
    ).encode(),
    "scripts/probe_network.py": (
        "import socket\n"
        "try:\n"
        "    sock = socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
        "    print('NETWORK_OK 1.1.1.1')\n"
        "    sock.close()\n"
        "except Exception as exc:\n"
        "    print('NETWORK_FAIL 1.1.1.1', type(exc).__name__)\n"
    ).encode(),
    "scripts/sleep.py": (
        "import sys, time\n"
        "seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 30\n"
        "print('SLEEP_START', seconds, flush=True)\n"
        "time.sleep(seconds)\n"
        "print('SLEEP_DONE', flush=True)\n"
    ).encode(),
}

db = SessionLocal()
slug = "qa-agentdock-execution-probes"
skill = db.query(Skill).filter(Skill.slug == slug).first()
if skill is None:
    skill = Skill(slug=slug, name="qa-execution-probes", description="Controlled execution QA skill",
                  path="skills/qa-execution-probes", category="Testing", creator="qa-agentdock",
                  source_url="https://example.invalid/qa-agentdock/execution-probes",
                  license_id="OWNER-AUTHORIZED", status="approved", security_status="clear",
                  score=100, stars=0, latest_version="git-qa-exec-1")
    db.add(skill)
    db.flush()
else:
    skill.status = "approved"
    skill.security_status = "clear"
    skill.latest_version = "git-qa-exec-1"
snapshot, digest, manifest = save_snapshot(skill.id, "git-qa-exec-1", FILES)
existing = db.query(SkillVersion).filter(SkillVersion.skill_id == skill.id, SkillVersion.version == "git-qa-exec-1").first()
if existing is None:
    db.add(SkillVersion(skill_id=skill.id, version="git-qa-exec-1", source_commit="qa-exec-1",
                        content_hash=digest, manifest=manifest, snapshot_path=snapshot))
else:
    existing.snapshot_path = snapshot
    existing.content_hash = digest
    existing.manifest = manifest
db.commit()
print("QA_SKILL_ID", skill.id)
print("FILES", len(manifest))
db.close()
