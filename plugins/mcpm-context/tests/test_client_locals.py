from __future__ import annotations


from mcpm_context.layers import MANAGED_LOCAL_HEADER, deploy_client_locals, scaffold_client_rule
from mcpm_context.sync import ApplyReport


def _setup(sandbox, dirname="v18_arp", with_git=True):
    scaffold_client_rule(dirname)
    clients_root = sandbox / "clients"
    repo = clients_root / dirname
    (repo / ".git" / "info").mkdir(parents=True) if with_git else repo.mkdir(parents=True)
    return clients_root, repo


def test01_deploy_writes_managed_local_and_exclude(sandbox):
    clients_root, repo = _setup(sandbox)
    report = ApplyReport()
    deploy_client_locals(clients_root, report)
    target = repo / "CLAUDE.local.md"
    content = target.read_text()
    assert MANAGED_LOCAL_HEADER in content
    assert "client context" in content
    assert "paths:" not in content and "---" not in content  # frontmatter stripped
    assert "CLAUDE.local.md" in (repo / ".git" / "info" / "exclude").read_text()


def test02_unmanaged_existing_file_left_alone(sandbox):
    clients_root, repo = _setup(sandbox)
    (repo / "CLAUDE.local.md").write_text("my own notes\n")
    report = ApplyReport()
    deploy_client_locals(clients_root, report)
    assert (repo / "CLAUDE.local.md").read_text() == "my own notes\n"
    assert any("not managed" in w for w in report.warnings)


def test03_idempotent_and_updates_on_layer_change(sandbox):
    from mcpm_context.layers import rules_dir

    clients_root, repo = _setup(sandbox)
    deploy_client_locals(clients_root, ApplyReport())
    report2 = ApplyReport()
    deploy_client_locals(clients_root, report2)
    assert not any("deployed" in a for a in report2.actions)  # unchanged → no rewrite
    skill = rules_dir() / "client-v18-arp" / "SKILL.md"
    skill.write_text(skill.read_text() + "\nNEW LINE\n")
    report3 = ApplyReport()
    deploy_client_locals(clients_root, report3)
    assert "NEW LINE" in (repo / "CLAUDE.local.md").read_text()


def test04_no_git_dir_skips_exclude_but_deploys(sandbox):
    clients_root, repo = _setup(sandbox, with_git=False)
    deploy_client_locals(clients_root, ApplyReport())
    assert (repo / "CLAUDE.local.md").exists()
    assert not (repo / ".git").exists()


def test05_dir_without_layer_untouched(sandbox):
    clients_root = sandbox / "clients"
    (clients_root / "otherclient").mkdir(parents=True)
    deploy_client_locals(clients_root, ApplyReport())
    assert not (clients_root / "otherclient" / "CLAUDE.local.md").exists()
