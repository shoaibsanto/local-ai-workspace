"""Tests for the security/storage hardening work: SSRF guard, backup/restore
round-trip, conversation export/import round-trip, and log redaction.
"""

from __future__ import annotations

import io
import json
import logging
import socket
import zipfile

import pytest

# ---------- SSRF guard ----------


def test_ssrf_guard_rejects_private_ip(monkeypatch):
    from local_ai_workspace.core.ssrf_guard import validate_outbound_url

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError):
        validate_outbound_url("http://internal.example.com/api", allow_loopback=False)


def test_ssrf_guard_rejects_cloud_metadata_ip(monkeypatch):
    from local_ai_workspace.core.ssrf_guard import validate_outbound_url

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError):
        validate_outbound_url("http://metadata.example.com/", allow_loopback=False)


def test_ssrf_guard_allows_loopback_when_flagged(monkeypatch):
    from local_ai_workspace.core.ssrf_guard import validate_outbound_url

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    # Should not raise when allow_loopback=True, even though it resolves to
    # a loopback address.
    validate_outbound_url("http://localhost:11434/v1", allow_loopback=True)


def test_ssrf_guard_rejects_loopback_without_flag(monkeypatch):
    from local_ai_workspace.core.ssrf_guard import validate_outbound_url

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError):
        validate_outbound_url("http://localhost:11434/v1", allow_loopback=False)


def test_ssrf_guard_allows_public_ip(monkeypatch):
    from local_ai_workspace.core.ssrf_guard import validate_outbound_url

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    # Public IP, not loopback -- should pass without raising.
    validate_outbound_url("https://api.example.com/v1", allow_loopback=False)


def test_ssrf_guard_dns_rebinding_guard(monkeypatch):
    """A hostname that looks public but resolves to a private IP must still
    be blocked -- this is the DNS-rebinding scenario."""
    from local_ai_workspace.core.ssrf_guard import validate_outbound_url

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError):
        validate_outbound_url("https://looks-public.example.com/v1", allow_loopback=False)


# ---------- Backup / restore round-trip ----------


def test_backup_restore_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from local_ai_workspace.storage.backup import create_backup, restore_backup
    from local_ai_workspace.storage.paths import get_data_root

    data_root = get_data_root()
    (data_root / "providers.json").write_text(json.dumps([{"id": "p1", "name": "Test"}]))
    conv_dir = data_root / "conversations" / "conv_1"
    conv_dir.mkdir(parents=True)
    (conv_dir / "meta.json").write_text(json.dumps({"id": "conv_1", "title": "Hello"}))

    backup_path = create_backup()
    assert backup_path.exists()
    assert backup_path.parent.name == "backups"

    # Corrupt/remove the original data to prove restore actually repopulates it.
    (data_root / "providers.json").unlink()
    import shutil

    shutil.rmtree(conv_dir)

    restored_count = restore_backup(backup_path)
    assert restored_count > 0
    assert (data_root / "providers.json").exists()
    assert json.loads((data_root / "providers.json").read_text()) == [{"id": "p1", "name": "Test"}]
    assert (conv_dir / "meta.json").exists()


def test_restore_backup_rejects_zip_slip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from local_ai_workspace.storage.backup import restore_backup

    malicious_zip = tmp_path / "evil.zip"
    with zipfile.ZipFile(malicious_zip, "w") as zf:
        zf.writestr("../../etc/evil.txt", "pwned")

    with pytest.raises(ValueError):
        restore_backup(malicious_zip)

    # Make sure nothing escaped onto the filesystem outside the data root.
    assert not (tmp_path.parent / "etc" / "evil.txt").exists()


def test_restore_backup_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))
    from local_ai_workspace.storage.backup import restore_backup

    with pytest.raises(FileNotFoundError):
        restore_backup(tmp_path / "does-not-exist.zip")


# ---------- Conversation export / import round-trip ----------


def test_conversation_export_import_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from local_ai_workspace.core.models import Message
    from local_ai_workspace.storage import conversation_store

    meta = conversation_store.create_conversation(title="Export Me", model="gpt-x", provider="prov-1")
    conversation_store.add_message(meta.id, Message(role="user", content="hi there"))
    conversation_store.add_message(meta.id, Message(role="assistant", content="hello!"))

    exported = conversation_store.export_conversation(meta.id)
    assert exported is not None
    assert exported["meta"]["title"] == "Export Me"
    assert len(exported["messages"]) == 2

    imported_meta = conversation_store.import_conversation(exported)

    # New conversation, never overwrites the original.
    assert imported_meta.id != meta.id
    assert imported_meta.title == "Export Me"

    original_still_exists = conversation_store.get_conversation_meta(meta.id)
    assert original_still_exists is not None

    imported_messages = conversation_store.get_messages(imported_meta.id)
    assert len(imported_messages) == 2
    assert imported_messages[0].content == "hi there"
    assert imported_messages[1].content == "hello!"
    # Message ids were re-minted, not copied verbatim.
    original_messages = conversation_store.get_messages(meta.id)
    assert {m.id for m in imported_messages}.isdisjoint({m.id for m in original_messages})


def test_export_conversation_not_found_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))
    from local_ai_workspace.storage import conversation_store

    assert conversation_store.export_conversation("conv_does_not_exist") is None


# ---------- Log redaction ----------


def test_log_redaction_filter_redacts_api_key():
    from local_ai_workspace.core.logging_setup import RedactionFilter

    logger = logging.getLogger("test.redaction")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactionFilter())
    logger.addHandler(handler)

    fake_key = "sk-THISlooksLIKEaREALapikey1234567890"
    logger.info("Using API key %s for request", fake_key)

    output = stream.getvalue()
    assert fake_key not in output
    assert "[REDACTED]" in output


def test_log_redaction_filter_redacts_bearer_token():
    from local_ai_workspace.core.logging_setup import RedactionFilter

    logger = logging.getLogger("test.redaction.bearer")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactionFilter())
    logger.addHandler(handler)

    logger.info("Authorization header: Bearer abcdef1234567890ghijklmno")

    output = stream.getvalue()
    assert "abcdef1234567890ghijklmno" not in output
    assert "[REDACTED]" in output


def test_redact_function_leaves_normal_text_alone():
    from local_ai_workspace.core.logging_setup import redact

    text = "short words here"
    assert redact(text) == text
