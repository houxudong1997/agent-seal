"""Comprehensive tests for Grafana dashboard JSON provisioning.

Coverage targets:
  - JSON schema / structural validity
  - Dashboard metadata (uid, title, schemaVersion, tags)
  - Data source configurations (Prometheus, PostgreSQL)
  - Panel definitions: titles, types, gridPos, queries
  - PromQL expressions validity
  - PostgreSQL raw SQL queries
  - Threshold configurations
  - Templating variables
  - Timepicker and refresh settings
  - Edge cases: missing fields, empty panels, invalid types
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# ── Fixtures ────────────────────────────────────────────────────

DASHBOARD_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "grafana"
    / "dashboards"
    / "agent-seal-overview.json"
)

# Expected dashboard metadata
EXPECTED_UID = "agent-seal-overview"
EXPECTED_TITLE = "Agent Seal — Overview"
EXPECTED_SCHEMA_VERSION = 39
EXPECTED_TAGS = ["agent-seal", "production"]
EXPECTED_REFRESH = "30s"

# Expected panels: (id, title, type, datasource_type)
EXPECTED_PANELS = [
    (1, "Event Throughput", "timeseries", "prometheus"),
    (2, "Error Rate", "timeseries", "prometheus"),
    (3, "Active Sessions", "gauge", "prometheus"),
    (4, "Storage Usage", "gauge", "prometheus"),
    (5, "Total Events", "stat", "prometheus"),
    (6, "LLM Latency (P50 / P95 / P99)", "timeseries", "postgresql"),
    (7, "Token Usage", "timeseries", "postgresql"),
    (8, "Top Models", "table", "postgresql"),
    (9, "Policy Activity", "timeseries", "prometheus"),
    (10, "Integrity Verifications", "timeseries", "prometheus"),
    (11, "Uptime", "stat", "prometheus"),
    (12, "Events by Type", "table", "postgresql"),
]

# Data source UIDs that should appear
EXPECTED_DS_UIDS = {"prometheus", "postgresql"}

# Panel types allowed in Grafana
ALLOWED_PANEL_TYPES = {
    "timeseries",
    "gauge",
    "stat",
    "table",
    "bargauge",
    "piechart",
    "heatmap",
    "logs",
    "candlestick",
    "state-timeline",
    "status-history",
    "graph",
}


# ── Helpers ─────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def dashboard() -> dict:
    """Load and parse the Grafana dashboard JSON once per session."""
    assert DASHBOARD_PATH.exists(), f"Dashboard not found at {DASHBOARD_PATH}"
    with open(DASHBOARD_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def db(dashboard: dict) -> dict:
    """Shortcut to dashboard['dashboard']."""
    return dashboard.get("dashboard", {})


@pytest.fixture(scope="module")
def meta(dashboard: dict) -> dict:
    """Shortcut to dashboard['meta']."""
    return dashboard.get("meta", {})


def _panel_by_id(panels: list[dict], pid: int) -> dict | None:
    """Find a panel by its numeric id."""
    for p in panels:
        if p.get("id") == pid:
            return p
    return None


def _panel_by_title(panels: list[dict], title: str) -> dict | None:
    """Find a panel by its title string."""
    for p in panels:
        if p.get("title") == title:
            return p
    return None


# ═══════════════════════════════════════════════════════════════
# 1.  JSON Structure & Schema
# ═══════════════════════════════════════════════════════════════


class TestJsonSchema:
    """Top-level JSON structure and required fields."""

    def test_file_exists(self):
        """The dashboard JSON file must exist on disk."""
        assert DASHBOARD_PATH.exists(), f"Dashboard JSON not found at {DASHBOARD_PATH}"

    def test_valid_json(self):
        """The file must be parseable as JSON."""
        with open(DASHBOARD_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict), "Top-level must be a JSON object"

    def test_top_level_keys(self, dashboard: dict):
        """Must have 'dashboard' and 'meta' keys."""
        assert "dashboard" in dashboard, "Missing top-level 'dashboard' key"
        assert "meta" in dashboard, "Missing top-level 'meta' key"

    def test_dashboard_keys(self, db: dict):
        """Dashboard object must have required metadata keys."""
        required = {
            "uid",
            "title",
            "tags",
            "timezone",
            "schemaVersion",
            "version",
            "refresh",
            "panels",
            "templating",
            "time",
            "timepicker",
        }
        missing = required - set(db.keys())
        assert not missing, f"Missing dashboard keys: {missing}"

    def test_meta_keys(self, meta: dict):
        """Meta object must have provisioning keys."""
        required = {
            "canSave",
            "canEdit",
            "canStar",
            "slug",
            "expires",
            "created",
            "updated",
            "updatedBy",
            "createdBy",
            "version",
        }
        missing = required - set(meta.keys())
        assert not missing, f"Missing meta keys: {missing}"


# ═══════════════════════════════════════════════════════════════
# 2.  Dashboard Identity
# ═══════════════════════════════════════════════════════════════


class TestDashboardIdentity:
    """Dashboard metadata correctness."""

    def test_uid(self, db: dict):
        assert db["uid"] == EXPECTED_UID, f"Expected uid={EXPECTED_UID!r}, got {db['uid']!r}"

    def test_title(self, db: dict):
        assert db["title"] == EXPECTED_TITLE, (
            f"Expected title={EXPECTED_TITLE!r}, got {db['title']!r}"
        )

    def test_schema_version(self, db: dict):
        assert db["schemaVersion"] == EXPECTED_SCHEMA_VERSION, (
            f"Expected schemaVersion={EXPECTED_SCHEMA_VERSION}, got {db['schemaVersion']}"
        )

    def test_tags(self, db: dict):
        assert db.get("tags") == EXPECTED_TAGS, (
            f"Expected tags={EXPECTED_TAGS}, got {db.get('tags')}"
        )

    def test_timezone(self, db: dict):
        assert db.get("timezone") == "browser", (
            f"Expected timezone='browser', got {db.get('timezone')!r}"
        )

    def test_refresh(self, db: dict):
        assert db.get("refresh") == EXPECTED_REFRESH, (
            f"Expected refresh={EXPECTED_REFRESH!r}, got {db.get('refresh')!r}"
        )

    def test_meta_slug(self, meta: dict):
        assert meta.get("slug") == EXPECTED_UID, (
            f"Meta slug mismatch: {meta.get('slug')!r} != {EXPECTED_UID!r}"
        )

    def test_meta_provisioner(self, meta: dict):
        assert meta.get("createdBy") == "agent-seal-provisioner", (
            f"Expected createdBy='agent-seal-provisioner', got {meta.get('createdBy')!r}"
        )

    def test_meta_saveable(self, meta: dict):
        assert meta.get("canSave") is True, "Dashboard should be saveable"
        assert meta.get("canEdit") is True, "Dashboard should be editable"


# ═══════════════════════════════════════════════════════════════
# 3.  Panel Definitions
# ═══════════════════════════════════════════════════════════════


class TestPanels:
    """Panel count, structure and required fields."""

    def test_panel_count(self, db: dict):
        """Must have exactly 12 panels as designed."""
        panels = db.get("panels", [])
        assert len(panels) == len(EXPECTED_PANELS), (
            f"Expected {len(EXPECTED_PANELS)} panels, found {len(panels)}"
        )

    def test_panel_ids_unique(self, db: dict):
        """All panel IDs must be unique."""
        panels = db.get("panels", [])
        ids = [p["id"] for p in panels if "id" in p]
        assert len(ids) == len(set(ids)), (
            f"Duplicate panel IDs: {[i for i in ids if ids.count(i) > 1]}"
        )

    def test_panel_required_fields(self, db: dict):
        """Each panel must have id, title, type, gridPos, datasource, targets."""
        for p in db.get("panels", []):
            assert "id" in p, f"Panel missing 'id': {p.get('title', '?')}"
            assert "title" in p, f"Panel {p['id']} missing 'title'"
            assert "type" in p, f"Panel {p['id']} missing 'type'"
            assert "gridPos" in p, f"Panel {p['id']} missing 'gridPos'"
            assert "datasource" in p, f"Panel {p['id']} missing 'datasource'"
            assert "targets" in p, f"Panel {p['id']} missing 'targets'"

    def test_panel_gridpos_structure(self, db: dict):
        """gridPos must have h, w, x, y."""
        for p in db.get("panels", []):
            gp = p.get("gridPos", {})
            for key in ("h", "w", "x", "y"):
                assert key in gp, f"Panel {p['id']} gridPos missing '{key}'"

    def test_panel_types_valid(self, db: dict):
        """Panel types must be among known Grafana types."""
        for p in db.get("panels", []):
            assert p["type"] in ALLOWED_PANEL_TYPES, (
                f"Panel {p['id']} has unknown type: {p['type']!r}"
            )

    def test_panel_titles_match(self, db: dict):
        """Check titles match expected spec."""
        titles = {t for _, t, _, _ in EXPECTED_PANELS}
        actual = {p["title"] for p in db.get("panels", [])}
        missing = titles - actual
        extra = actual - titles
        assert not missing, f"Missing expected panel titles: {missing}"
        assert not extra, f"Unexpected panel titles: {extra}"

    def test_expected_panels_present(self, db: dict):
        """All 12 expected panels must be present by title."""
        panels = db.get("panels", [])
        for _pid, title, ptype, _dstype in EXPECTED_PANELS:
            p = _panel_by_title(panels, title)
            assert p is not None, f"Panel '{title}' not found"
            assert p["type"] == ptype, (
                f"Panel '{title}': expected type={ptype!r}, got {p['type']!r}"
            )

    def test_active_sessions_thresholds(self, db: dict):
        """Active Sessions (id=3) must have yellow@50, red@100."""
        p = _panel_by_id(db.get("panels", []), 3)
        assert p is not None, "Active Sessions panel not found"
        fc = p.get("fieldConfig", {}).get("defaults", {})
        th = fc.get("thresholds", {})
        assert th.get("mode") == "absolute"
        steps = th.get("steps", [])
        assert len(steps) == 3, f"Expected 3 threshold steps, got {len(steps)}"
        # Green: value=null (default)
        assert steps[0]["value"] is None and steps[0]["color"] == "green"
        # Yellow at 50
        assert steps[1]["value"] == 50 and steps[1]["color"] == "yellow", (
            f"Expected yellow@50, got {steps[1]}"
        )
        # Red at 100
        assert steps[2]["value"] == 100 and steps[2]["color"] == "red", (
            f"Expected red@100, got {steps[2]}"
        )

    def test_storage_usage_thresholds(self, db: dict):
        """Storage Usage (id=4) must have yellow@1GB, red@5GB."""
        p = _panel_by_id(db.get("panels", []), 4)
        assert p is not None, "Storage Usage panel not found"
        fc = p.get("fieldConfig", {}).get("defaults", {})
        th = fc.get("thresholds", {})
        steps = th.get("steps", [])
        assert len(steps) == 3, f"Expected 3 threshold steps, got {len(steps)}"
        assert steps[0]["value"] is None and steps[0]["color"] == "green"
        # Yellow at 1 GB (1073741824 bytes)
        assert steps[1]["value"] == 1073741824 and steps[1]["color"] == "yellow", (
            f"Expected yellow@1073741824, got {steps[1]}"
        )
        # Red at 5 GB (5368709120 bytes)
        assert steps[2]["value"] == 5368709120 and steps[2]["color"] == "red", (
            f"Expected red@5368709120, got {steps[2]}"
        )

    def test_uptime_threshold(self, db: dict):
        """Uptime stat (id=11) must have two threshold steps (green + red@0)."""
        p = _panel_by_id(db.get("panels", []), 11)
        assert p is not None, "Uptime panel not found"
        fc = p.get("fieldConfig", {}).get("defaults", {})
        th = fc.get("thresholds", {})
        steps = th.get("steps", [])
        assert len(steps) == 2, f"Expected 2 threshold steps, got {len(steps)}"
        assert steps[0]["value"] is None and steps[0]["color"] == "green"
        assert steps[1]["value"] == 1 and steps[1]["color"] == "red", (
            f"Expected red@1, got {steps[1]}"
        )

    def test_fieldconfig_min(self, db: dict):
        """Panels with numeric values should have min=0."""
        for p in db.get("panels", []):
            fc = p.get("fieldConfig", {}).get("defaults", {})
            # Skip panels that don't have fieldConfig with defaults
            if "fieldConfig" in p and "defaults" in p["fieldConfig"]:
                unit = fc.get("unit", "")
                if unit in ("reqps", "percent", "bytes", "ms", "short", "s"):
                    assert fc.get("min") == 0, (
                        f"Panel {p['id']} ({p['title']}): expected min=0, got {fc.get('min')}"
                    )


# ═══════════════════════════════════════════════════════════════
# 4.  Data Sources
# ═══════════════════════════════════════════════════════════════


class TestDataSources:
    """Data source configuration correctness."""

    def test_datasource_in_panel(self, db: dict):
        """Every panel must declare a datasource with type and uid."""
        for p in db.get("panels", []):
            ds = p.get("datasource", {})
            assert "type" in ds, f"Panel {p['id']} datasource missing 'type'"
            assert "uid" in ds, f"Panel {p['id']} datasource missing 'uid'"

    def test_only_expected_ds_types(self, db: dict):
        """Only prometheus and postgresql data sources should appear."""
        for p in db.get("panels", []):
            dstype = p["datasource"]["type"]
            assert dstype in EXPECTED_DS_UIDS, (
                f"Panel {p['id']} uses unexpected DS type: {dstype!r}"
            )

    def test_datasource_uid_consistency(self, db: dict):
        """Prometheus panels should all use uid='prometheus', "
        "PostgreSQL panels should use uid='postgresql'."""
        for p in db.get("panels", []):
            ds = p["datasource"]
            if ds["type"] == "prometheus":
                assert ds["uid"] == "prometheus", (
                    f"Panel {p['id']}: Prometheus DS uid should be 'prometheus', got {ds['uid']!r}"
                )
            elif ds["type"] == "postgresql":
                assert ds["uid"] == "postgresql", (
                    f"Panel {p['id']}: PostgreSQL DS uid should be 'postgresql', got {ds['uid']!r}"
                )

    def test_prometheus_panels_count(self, db: dict):
        """Count Prometheus panels (Event Throughput, Error Rate,
        Active Sessions, Storage Usage, Total Events, Policy Activity,
        Integrity Verifications, Uptime = 8)."""
        prom_panels = [
            p for p in db.get("panels", []) if p.get("datasource", {}).get("type") == "prometheus"
        ]
        assert len(prom_panels) == 8, f"Expected 8 Prometheus panels, found {len(prom_panels)}"

    def test_postgresql_panels_count(self, db: dict):
        """Count PostgreSQL panels."""
        pg_panels = [
            p for p in db.get("panels", []) if p.get("datasource", {}).get("type") == "postgresql"
        ]
        # Panels 6 (latency), 7 (tokens), 8 (top models), 12 (events by type)
        assert len(pg_panels) == 4, f"Expected 4 PostgreSQL panels, found {len(pg_panels)}"

    def test_target_datasource_consistency(self, db: dict):
        """Individual targets should reference the same DS as their panel."""
        for p in db.get("panels", []):
            panel_ds = p.get("datasource", {})
            for t in p.get("targets", []):
                target_ds = t.get("datasource", {})
                if target_ds:
                    assert target_ds["type"] == panel_ds["type"], (
                        f"Panel {p['id']} target {t.get('refId', '?')}: "
                        f"target DS type {target_ds['type']!r} != "
                        f"panel DS type {panel_ds['type']!r}"
                    )
                    assert target_ds["uid"] == panel_ds["uid"], (
                        f"Panel {p['id']} target {t.get('refId', '?')}: "
                        f"target DS uid {target_ds['uid']!r} != "
                        f"panel DS uid {panel_ds['uid']!r}"
                    )


# ═══════════════════════════════════════════════════════════════
# 5.  Prometheus Queries (PromQL)
# ═══════════════════════════════════════════════════════════════


class TestPrometheusQueries:
    """PromQL expression validation."""

    def test_event_throughput_query(self, db: dict):
        """Event Throughput should use rate(audit_events_total[5m])."""
        p = _panel_by_id(db.get("panels", []), 1)
        assert p is not None
        expr = p["targets"][0]["expr"]
        assert "rate(audit_events_total[5m])" in expr, (
            f"Unexpected event throughput query: {expr!r}"
        )

    def test_error_rate_query(self, db: dict):
        """Error Rate should compute % via rate ratio."""
        p = _panel_by_id(db.get("panels", []), 2)
        assert p is not None
        expr = p["targets"][0]["expr"]
        assert "event_type" in expr, f"Error rate query missing event_type filter: {expr!r}"
        assert "/ rate(audit_events_total[5m])" in expr, (
            f"Error rate query missing denominator: {expr!r}"
        )
        assert "* 100" in expr, f"Error rate query missing * 100: {expr!r}"

    def test_active_sessions_query(self, db: dict):
        """Active Sessions should use simple gauge metric."""
        p = _panel_by_id(db.get("panels", []), 3)
        assert p is not None
        expr = p["targets"][0]["expr"]
        assert expr == "audit_sessions_active", f"Unexpected active sessions query: {expr!r}"

    def test_storage_usage_query(self, db: dict):
        """Storage Usage should use audit_storage_bytes."""
        p = _panel_by_id(db.get("panels", []), 4)
        assert p is not None
        expr = p["targets"][0]["expr"]
        assert expr == "audit_storage_bytes", f"Unexpected storage query: {expr!r}"

    def test_total_events_query(self, db: dict):
        """Total Events should use audit_events_total counter."""
        p = _panel_by_id(db.get("panels", []), 5)
        assert p is not None
        expr = p["targets"][0]["expr"]
        assert expr == "audit_events_total", f"Unexpected total events query: {expr!r}"

    def test_policy_activity_queries(self, db: dict):
        """Policy Activity should have denial and approval targets."""
        p = _panel_by_id(db.get("panels", []), 9)
        assert p is not None
        targets = p["targets"]
        assert len(targets) == 2, f"Policy Activity expected 2 targets, got {len(targets)}"
        denials = [t for t in targets if "denial" in t["expr"]]
        approvals = [t for t in targets if "approval" in t["expr"]]
        assert len(denials) == 1, "Missing denials target"
        assert len(approvals) == 1, "Missing approvals target"
        assert "rate(audit_policy_denials_total[5m])" in denials[0]["expr"]
        assert "rate(audit_policy_approvals_total[5m])" in approvals[0]["expr"]

    def test_integrity_verifications_query(self, db: dict):
        """Integrity Verifications should use rate(audit_verify_checks_total[5m])."""
        p = _panel_by_id(db.get("panels", []), 10)
        assert p is not None
        expr = p["targets"][0]["expr"]
        assert "rate(audit_verify_checks_total[5m])" in expr, (
            f"Unexpected integrity query: {expr!r}"
        )

    def test_uptime_query(self, db: dict):
        """Uptime should use audit_uptime_seconds."""
        p = _panel_by_id(db.get("panels", []), 11)
        assert p is not None
        expr = p["targets"][0]["expr"]
        assert expr == "audit_uptime_seconds", f"Unexpected uptime query: {expr!r}"

    def test_promql_rate_wrapping(self, db: dict):
        """rate() expressions must include [5m] duration."""
        prometheus_panels = [
            p
            for p in db.get("panels", [])
            if p.get("datasource", {}).get("type") == "prometheus" and p.get("type") == "timeseries"
        ]
        for p in prometheus_panels:
            for t in p.get("targets", []):
                expr = t.get("expr", "")
                if "rate(" in expr and "error" not in expr.lower():
                    # Check that rate() includes [5m]
                    assert "[5m]" in expr, (
                        f"Panel {p['id']}: rate() missing [5m] duration: {expr!r}"
                    )

    def test_legend_format(self, db: dict):
        """Prometheus panels should have meaningful legendFormat."""
        prometheus_panels = [
            p for p in db.get("panels", []) if p.get("datasource", {}).get("type") == "prometheus"
        ]
        for p in prometheus_panels:
            for t in p.get("targets", []):
                assert "legendFormat" in t, (
                    f"Panel {p['id']} target {t.get('refId', '?')} missing legendFormat"
                )

    def test_promql_no_sql_injection_patterns(self, db: dict):
        """PromQL targets should not contain SQL keywords."""
        prometheus_panels = [
            p for p in db.get("panels", []) if p.get("datasource", {}).get("type") == "prometheus"
        ]
        sql_keywords = re.compile(
            r"\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|FROM|WHERE)\b",
            re.IGNORECASE,
        )
        for p in prometheus_panels:
            for t in p.get("targets", []):
                expr = t.get("expr", "")
                if sql_keywords.search(expr):
                    pytest.fail(f"Panel {p['id']} PromQL target contains SQL-like syntax: {expr!r}")


# ═══════════════════════════════════════════════════════════════
# 6.  PostgreSQL Queries
# ═══════════════════════════════════════════════════════════════


class TestPostgresQueries:
    """PostgreSQL raw SQL query validation."""

    def test_latency_query(self, db: dict):
        """LLM Latency should use percentile_cont on llm_calls.latency_ms."""
        p = _panel_by_id(db.get("panels", []), 6)
        assert p is not None
        t = p["targets"][0]
        assert t["rawSql"] is True, "Latency query should have rawSql=true"
        sql = t["expr"]
        assert "percentile_cont" in sql, f"Missing percentile_cont: {sql}"
        assert "latency_ms" in sql, f"Missing latency_ms: {sql}"
        assert "llm_calls" in sql, f"Missing llm_calls table: {sql}"
        assert "$__timeFilter" in sql, f"Missing $__timeFilter: {sql}"

    def test_latency_has_all_percentiles(self, db: dict):
        """Latency panel must query P50, P95, and P99."""
        p = _panel_by_id(db.get("panels", []), 6)
        assert p is not None
        sql = p["targets"][0]["expr"]
        for percentile in ("0.50", "0.95", "0.99"):
            assert percentile in sql, f"Missing P{int(float(percentile) * 100)} percentile in query"

    def test_token_usage_query(self, db: dict):
        """Token Usage should SUM prompt_tokens and completion_tokens."""
        p = _panel_by_id(db.get("panels", []), 7)
        assert p is not None
        t = p["targets"][0]
        assert t["rawSql"] is True, "Token query should have rawSql=true"
        sql = t["expr"]
        assert "SUM(prompt_tokens)" in sql, f"Missing SUM(prompt_tokens): {sql}"
        assert "SUM(completion_tokens)" in sql, f"Missing SUM(completion_tokens): {sql}"
        assert "$__timeFilter" in sql, f"Missing $__timeFilter: {sql}"

    def test_top_models_query(self, db: dict):
        """Top Models should GROUP BY model, provider with aggregation."""
        p = _panel_by_id(db.get("panels", []), 8)
        assert p is not None
        t = p["targets"][0]
        assert t["rawSql"] is True, "Top models query should have rawSql=true"
        sql = t["expr"]
        assert "GROUP BY model, provider" in sql, f"Missing GROUP BY: {sql}"
        assert "ORDER BY call_count DESC" in sql, f"Missing ORDER BY: {sql}"
        assert "LIMIT 10" in sql, f"Missing LIMIT 10: {sql}"
        assert "COUNT(*)" in sql or "COUNT(" in sql, f"Missing COUNT: {sql}"

    def test_events_by_type_query(self, db: dict):
        """Events by Type should GROUP BY event_type."""
        p = _panel_by_id(db.get("panels", []), 12)
        assert p is not None
        t = p["targets"][0]
        assert t["rawSql"] is True, "Events by type should have rawSql=true"
        sql = t["expr"]
        assert "GROUP BY event_type" in sql, f"Missing GROUP BY event_type: {sql}"
        assert "ORDER BY count DESC" in sql, f"Missing ORDER BY count DESC: {sql}"

    def test_postgresql_target_format(self, db: dict):
        """All PostgreSQL panel targets must have format='table' and rawSql=true."""
        pg_panels = [
            p for p in db.get("panels", []) if p.get("datasource", {}).get("type") == "postgresql"
        ]
        for p in pg_panels:
            for t in p.get("targets", []):
                assert t.get("format") == "table", (
                    f"Panel {p['id']} PG target format should be 'table', got {t.get('format')!r}"
                )
                assert t.get("rawSql") is True, f"Panel {p['id']} PG target should have rawSql=true"

    def test_postgresql_select_only(self, db: dict):
        """PostgreSQL queries must be SELECT-only (no DML/DLL)."""
        forbidden = re.compile(
            r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE)\b",
            re.IGNORECASE,
        )
        pg_panels = [
            p for p in db.get("panels", []) if p.get("datasource", {}).get("type") == "postgresql"
        ]
        for p in pg_panels:
            for t in p.get("targets", []):
                sql = t.get("expr", "")
                match = forbidden.search(sql)
                if match:
                    pytest.fail(
                        f"Panel {p['id']} PG query contains forbidden '{match.group()}': {sql!r}"
                    )


# ═══════════════════════════════════════════════════════════════
# 7.  Templating & Time
# ═══════════════════════════════════════════════════════════════


class TestTemplating:
    """Template variable configuration."""

    def test_templating_exists(self, db: dict):
        """Dashboard must have a templating section."""
        assert "templating" in db
        assert "list" in db["templating"]

    def test_datasource_variable(self, db: dict):
        """Should have a datasource template variable."""
        tl = db.get("templating", {}).get("list", [])
        ds_vars = [v for v in tl if v.get("type") == "datasource"]
        assert len(ds_vars) >= 1, "Expected at least 1 datasource template var"
        v = ds_vars[0]
        assert v.get("query") == "prometheus", (
            f"Expected datasource query='prometheus', got {v.get('query')!r}"
        )


class TestTimeSettings:
    """Time range and timepicker configuration."""

    def test_time_range(self, db: dict):
        """Default time range should be now-6h to now."""
        t = db.get("time", {})
        assert t.get("from") == "now-6h", f"Expected time.from='now-6h', got {t.get('from')!r}"
        assert t.get("to") == "now", f"Expected time.to='now', got {t.get('to')!r}"

    def test_timepicker_refresh_intervals(self, db: dict):
        """Timepicker should define reasonable refresh intervals."""
        tp = db.get("timepicker", {})
        intervals = tp.get("refresh_intervals", [])
        assert "5s" in intervals, "Should support 5s refresh"
        assert "30s" in intervals, "Should support 30s refresh"
        assert "1m" in intervals, "Should support 1m refresh"
        assert "5m" in intervals, "Should support 5m refresh"
        assert "1h" in intervals, "Should support 1h refresh"

    def test_timepicker_time_options(self, db: dict):
        """Timepicker should define useful quick-range options."""
        tp = db.get("timepicker", {})
        options = tp.get("time_options", [])
        assert "5m" in options, "Missing 5m quick range"
        assert "1h" in options, "Missing 1h quick range"
        assert "6h" in options, "Missing 6h quick range"
        assert "24h" in options, "Missing 24h quick range"
        assert "7d" in options, "Missing 7d quick range"


# ═══════════════════════════════════════════════════════════════
# 8.  Edge Cases & Defensive
# ═══════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases and defensive validation."""

    def test_no_empty_panels(self, db: dict):
        """No panel should be empty or a bare shell."""
        for p in db.get("panels", []):
            assert p.get("targets"), f"Panel {p['id']} has no targets"

    def test_no_duplicate_refids(self, db: dict):
        """RefIds within a panel's targets must be unique."""
        for p in db.get("panels", []):
            refs = [t.get("refId", "") for t in p.get("targets", [])]
            assert len(refs) == len(set(refs)), f"Panel {p['id']} has duplicate refIds: {refs}"

    def test_id_within_range(self, db: dict):
        """All panel IDs must be between 1 and 200."""
        for p in db.get("panels", []):
            pid = p.get("id", 0)
            assert 1 <= pid <= 200, f"Panel '{p['title']}' has out-of-range id: {pid}"

    def test_annotations_exists(self, db: dict):
        """Dashboard must have annotations section."""
        assert "annotations" in db
        assert "list" in db["annotations"]

    def test_links_exists(self, db: dict):
        """Dashboard must have links section."""
        assert "links" in db

    def test_meta_version_match(self, dashboard: dict):
        """Dashboard version and meta version should match."""
        assert dashboard["dashboard"]["version"] == dashboard["meta"]["version"], (
            f"Version mismatch: db={dashboard['dashboard']['version']}, "
            f"meta={dashboard['meta']['version']}"
        )

    def test_meta_timestamps_parsable(self, meta: dict):
        """Meta timestamps should be valid ISO 8601."""
        from datetime import datetime

        for key in ("created", "updated"):
            val = meta.get(key, "")
            try:
                datetime.fromisoformat(val.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pytest.fail(f"Meta {key} is not valid ISO 8601: {val!r}")

    def test_no_duplicate_uids(self, db: dict):
        """Dashboard UID should only appear once (no duplicate entries)."""
        # This is a simple check — the file only has one dashboard
        assert db.get("uid") == EXPECTED_UID


# ═══════════════════════════════════════════════════════════════
# 9.  Cross-panel Consistency
# ═══════════════════════════════════════════════════════════════


class TestCrossPanelConsistency:
    """Consistency checks across all panels."""

    def test_no_min_max_zero(self, db: dict):
        """No fieldConfig should have min == max unless it's intentional."""
        for p in db.get("panels", []):
            fc = p.get("fieldConfig", {}).get("defaults", {})
            if fc.get("min") is not None and fc.get("max") is not None:
                assert fc["min"] < fc["max"], (
                    f"Panel {p['id']} has min={fc['min']} >= max={fc['max']}"
                )

    def test_gridpos_no_overlap(self, db: dict):
        """No two panels should share the exact same gridPos."""
        panels = db.get("panels", [])
        positions = [
            (p["gridPos"]["x"], p["gridPos"]["y"], p["gridPos"]["w"], p["gridPos"]["h"])
            for p in panels
        ]
        seen = {}
        for i, pos in enumerate(positions):
            x, y, _w, _h = pos
            # Check if any previous panel covers this start corner
            for j, (px, py, pw, ph) in enumerate(seen.values()):
                if px <= x < px + pw and py <= y < py + ph:
                    pytest.fail(f"Panel {panels[i]['id']} overlaps panel {panels[j]['id']}")
            seen[i] = pos

    def test_total_events_unit_short(self, db: dict):
        """Total Events stat should use 'short' unit."""
        p = _panel_by_id(db.get("panels", []), 5)
        assert p is not None
        fc = p.get("fieldConfig", {}).get("defaults", {})
        assert fc.get("unit") == "short", (
            f"Total Events expected unit='short', got {fc.get('unit')!r}"
        )

    def test_storage_unit_bytes(self, db: dict):
        """Storage Usage should use 'bytes' unit."""
        p = _panel_by_id(db.get("panels", []), 4)
        assert p is not None
        fc = p.get("fieldConfig", {}).get("defaults", {})
        assert fc.get("unit") == "bytes", (
            f"Storage Usage expected unit='bytes', got {fc.get('unit')!r}"
        )
