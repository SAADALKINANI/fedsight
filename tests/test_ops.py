from fedsight.ops import AuditLog, RateLimiter


def test_hourly_limit_is_per_visitor():
    rl = RateLimiter(per_hour=2, per_day_total=100)
    assert rl.check("a") is None and rl.check("a") is None
    assert "Rate limit" in rl.check("a")
    assert rl.check("b") is None


def test_daily_cap_applies_to_everyone():
    rl = RateLimiter(per_hour=50, per_day_total=3)
    assert [rl.check(k) for k in "abc"] == [None, None, None]
    assert "daily question limit" in rl.check("d")


def test_client_ids_are_hashed_not_raw_ips():
    h = AuditLog.hash_client("203.0.113.9")
    assert "203" not in h and len(h) == 16
    assert h == AuditLog.hash_client("203.0.113.9") != AuditLog.hash_client("203.0.113.10")


def test_audit_log_writes_json_lines(tmp_path):
    path = tmp_path / "audit.jsonl"
    AuditLog(path).write({"event": "ask", "question": "hello"})
    line = path.read_text().strip()
    assert '"event": "ask"' in line and '"ts"' in line
