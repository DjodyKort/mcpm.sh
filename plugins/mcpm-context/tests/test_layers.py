from __future__ import annotations

from mcpm_context.layers import (
    list_layers,
    rules_dir,
    scaffold_client_rule,
    scaffold_personal_rule,
)


def test01_personal_scaffold_idempotent():
    created = scaffold_personal_rule()
    assert created and created.exists()
    created.write_text(created.read_text() + "\nMY EDIT\n")
    assert scaffold_personal_rule() is None  # never overwrites
    assert "MY EDIT" in (rules_dir() / "personal" / "SKILL.md").read_text()


def test02_client_underscore_name_slugged_glob_raw():
    created = scaffold_client_rule("v18_arp")
    assert created
    content = created.read_text()
    assert "name: client-v18-arp" in content  # slug satisfies skills name regex
    assert 'globs: "**/clients/v18_arp/**"' in content  # comma-string form; glob keeps real dir name
    assert created.parent.name == "client-v18-arp"


def test03_client_custom_glob():
    created = scaffold_client_rule("kvgm", glob="/abs/path/kvgm/**")
    assert 'globs: "/abs/path/kvgm/**"' in created.read_text()


def test04_list_layers_parses_globs():
    scaffold_personal_rule()
    scaffold_client_rule("kvgm")
    layers = {layer.name: layer for layer in list_layers()}
    assert layers["personal"].globs == []
    assert layers["client-kvgm"].globs == ["**/clients/kvgm/**"]
