from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcpm_context.config import load_config, save_config
from mcpm_context.paths import context_config_path
from mcpm_context.schema import CF_LEGACY_SERVER_NAMES, ContextConfig, ProfileSpec


def test01_defaults():
    config = ContextConfig()
    assert config.profiles == {}
    assert config.dedupe.enabled
    assert config.dedupe.legacy_names == CF_LEGACY_SERVER_NAMES
    assert config.dedupe.require_mcpm_twin
    assert config.settings.ensure_allow == []
    assert config.cf_wrapper_hash is None


def test02_profile_spec_defaults():
    spec = ProfileSpec()
    assert spec.org and spec.org_mode == "import"
    assert spec.rules == "inherit" and spec.servers == "inherit"
    assert spec.commands and spec.skills and spec.agents
    assert spec.copy_auth and spec.link_rules


def test03_profile_name_shell_safety():
    ContextConfig(profiles={"bare": ProfileSpec()})  # valid
    ContextConfig(profiles={"v18-arp": ProfileSpec()})  # valid
    with pytest.raises(ValidationError):
        ContextConfig(profiles={"Bad Name": ProfileSpec()})
    with pytest.raises(ValidationError):
        ContextConfig(profiles={"$(rm -rf)": ProfileSpec()})


def test04_config_round_trip():
    config = ContextConfig(profiles={"bare": ProfileSpec(org=False, rules="none", servers="none")})
    config.settings.ensure_allow.append("Bash(git status)")
    save_config(config)
    loaded = load_config()
    assert loaded.profiles["bare"].org is False
    assert loaded.profiles["bare"].rules == "none"
    assert loaded.settings.ensure_allow == ["Bash(git status)"]


def test05_corrupt_config_falls_back_to_default():
    context_config_path().write_text("{not json")
    assert load_config() == ContextConfig()


def test06_explicit_lists_survive_round_trip():
    config = ContextConfig(profiles={"arp": ProfileSpec(rules=["personal", "client-v18-arp"], servers=["odh"])})
    save_config(config)
    loaded = load_config()
    assert loaded.profiles["arp"].rules == ["personal", "client-v18-arp"]
    assert loaded.profiles["arp"].servers == ["odh"]
