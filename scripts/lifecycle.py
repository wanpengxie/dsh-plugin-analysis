#!/usr/bin/env python3
"""Deterministic repository lifecycle classification; no model judgment."""
from __future__ import annotations

import datetime as dt
import pathlib
import re

README_NAMES = ("README.md", "README.MD", "readme.md", "README.en.md", "README.zh-CN.md")
ARCHIVED_RE = re.compile(r"\barchived\b|已归档|项目归档|仓库归档", re.I)
DEPRECATED_RE = re.compile(r"\bdeprecated\b|已弃用|不推荐使用|废弃", re.I)
UNMAINTAINED_RE = re.compile(
    r"no longer maintained|not (?:actively )?maintained|停止维护|不再维护|停止更新|不再更新",
    re.I,
)


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def parse_time(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def readme_notices(root: pathlib.Path):
    signals = []
    flags = {"archived": False, "deprecated": False, "unmaintained": False}
    patterns = (("archived", ARCHIVED_RE), ("deprecated", DEPRECATED_RE), ("unmaintained", UNMAINTAINED_RE))
    for name in README_NAMES:
        path = root / name
        if not path.is_file():
            continue
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            compact = " ".join(line.split())
            for kind, pattern in patterns:
                if pattern.search(compact):
                    flags[kind] = True
                    signals.append(f"{name}:{number}:{kind}")
    return flags, list(dict.fromkeys(signals))


def derive_lifecycle(row: dict, root: pathlib.Path, checked_at: str, notice_texts=()):
    now = parse_time(checked_at) or dt.datetime.now(dt.timezone.utc)
    pushed_at = row.get("pushed_at") or ""
    pushed = parse_time(pushed_at)
    inactive_days = max(0, (now - pushed).days) if pushed else None
    try:
        commits = int(row.get("commits") or 0)
    except (TypeError, ValueError):
        commits = 0
    repository_archived = parse_bool(row.get("archived"))
    disabled = parse_bool(row.get("disabled"))
    notices, signals = readme_notices(root)
    for text in notice_texts:
        if ARCHIVED_RE.search(text or ""):
            notices["archived"] = True; signals.append("stored_analysis:archived")
        if DEPRECATED_RE.search(text or ""):
            notices["deprecated"] = True; signals.append("stored_analysis:deprecated")
        if UNMAINTAINED_RE.search(text or ""):
            notices["unmaintained"] = True; signals.append("stored_analysis:unmaintained")
    if repository_archived is not None:
        signals.insert(0, f"repository_metadata:archived={str(repository_archived).lower()}")
    if disabled is not None:
        signals.append(f"repository_metadata:disabled={str(disabled).lower()}")
    if pushed_at:
        signals.append(f"list:pushed_at={pushed_at}")
    signals.append(f"list:commits={commits}")

    if repository_archived is True or notices["archived"] or disabled is True:
        status = "archived"
    elif notices["deprecated"]:
        status = "deprecated"
    elif notices["unmaintained"] or (inactive_days is not None and inactive_days >= 365):
        status = "inactive"
    elif inactive_days is not None and (inactive_days >= 120 or (commits <= 1 and inactive_days >= 60)):
        status = "low_activity"
    elif inactive_days is not None:
        status = "active"
    else:
        status = "unknown"

    return {
        "status": status,
        "repository_archived": repository_archived,
        "repository_disabled": disabled,
        "deprecated_notice": notices["deprecated"],
        "maintenance_notice": notices["unmaintained"],
        "last_push_at": pushed_at,
        "inactive_days": inactive_days,
        "commit_count": commits,
        "checked_at": now.isoformat(),
        "signals": list(dict.fromkeys(signals)),
    }


def lifecycle_text(value: dict):
    labels = {"active": "活跃维护", "low_activity": "低活跃", "inactive": "长期未维护", "deprecated": "已弃用", "archived": "已归档", "unknown": "维护状态未知"}
    text = labels[value["status"]]
    if value.get("inactive_days") is not None:
        text += f"；距最后推送 {value['inactive_days']} 天"
    return text + f"；提交数 {value.get('commit_count', 0)}"


def _int(row, key):
    try:
        return int(float(row.get(key))) if row.get(key) not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _float(row, key):
    try:
        return float(row.get(key)) if row.get(key) not in (None, "") else None
    except (TypeError, ValueError):
        return None


def derive_repository_health(row: dict, root: pathlib.Path, checked_at: str, notice_texts=()):
    """Combine raw GitHub metadata and deterministic lifecycle/health metrics."""
    lifecycle = derive_lifecycle(row, root, checked_at, notice_texts)
    commits_30d = _int(row, "commits_30d")
    commits_90d = _int(row, "commits_90d")
    commits_365d = _int(row, "commits_365d")
    active_months = _int(row, "active_months_12m")
    median_interval = _float(row, "median_commit_interval_days")
    if commits_90d is None:
        frequency = "unknown"
    elif commits_90d >= 36:
        frequency = "weekly_or_more"
    elif commits_90d >= 12:
        frequency = "monthly_or_more"
    elif commits_365d and commits_365d >= 4:
        frequency = "occasional"
    else:
        frequency = "dormant"
    maintenance = {
        "frequency": frequency,
        "commits_30d": commits_30d,
        "commits_90d": commits_90d,
        "commits_365d": commits_365d,
        "active_months_12m": active_months,
        "median_commit_interval_days": median_interval,
    }
    sample_size = _int(row, "issue_sample_size")
    issues = {
        "enabled": parse_bool(row.get("has_issues")),
        "open_issue_count": _int(row, "open_issue_count"),
        "open_items_count": _int(row, "open_issues_count"),
        "sample_size": sample_size,
        "open_sample": _int(row, "issue_open_sample"),
        "closed_sample": _int(row, "issue_closed_sample"),
        "close_rate_sample": _float(row, "issue_close_rate_sample"),
        "median_close_days_sample": _float(row, "issue_median_close_days_sample"),
        "updated_90d_sample": _int(row, "issues_updated_90d_sample"),
        "latest_updated_at": row.get("latest_issue_updated_at") or "",
    }
    lifecycle_points = {"active": 40, "low_activity": 25, "inactive": 8, "deprecated": 3, "archived": 0, "unknown": 15}[lifecycle["status"]]
    if commits_90d is None:
        maintenance_points = 10
    elif commits_90d >= 12 and (active_months or 0) >= 6:
        maintenance_points = 40
    elif commits_90d >= 4:
        maintenance_points = 32
    elif commits_90d >= 1:
        maintenance_points = 24
    elif (lifecycle.get("inactive_days") or 10**9) < 120:
        maintenance_points = 16
    elif (lifecycle.get("inactive_days") or 10**9) < 365:
        maintenance_points = 8
    else:
        maintenance_points = 0
    close_rate = issues["close_rate_sample"]
    if issues["enabled"] is False:
        issue_points = 10
    elif not sample_size:
        issue_points = 12
    else:
        issue_points = round(4 + 12 * (close_rate if close_rate is not None else 0.5))
        median_close = issues["median_close_days_sample"]
        if median_close is not None:
            issue_points += 4 if median_close <= 14 else (2 if median_close <= 60 else 0)
        issue_points = min(20, issue_points)
    detailed_groups = sum((lifecycle["repository_archived"] is not None, commits_90d is not None, issues["enabled"] is not None and sample_size is not None))
    score_confidence = "high" if detailed_groups == 3 else ("medium" if detailed_groups >= 1 else "low")
    return {
        "lifecycle": lifecycle,
        "maintenance": maintenance,
        "issues": issues,
        "health_score": lifecycle_points + maintenance_points + issue_points,
        "score_confidence": score_confidence,
        "score_components": {"lifecycle": lifecycle_points, "maintenance": maintenance_points, "issues": issue_points},
        "method": "repository-health-v1",
    }


def repository_health_text(value: dict):
    lifecycle = lifecycle_text(value["lifecycle"])
    maintenance = value["maintenance"]
    issues = value["issues"]
    return (
        f"{lifecycle}；更新频次 {maintenance['frequency']}；"
        f"近 90 天提交 {maintenance['commits_90d'] if maintenance['commits_90d'] is not None else '未知'}；"
        f"开放 Issue {issues.get('open_issue_count') if issues.get('open_issue_count') is not None else (issues.get('open_items_count') if issues.get('open_items_count') is not None else '未知')}；"
        f"仓库健康分 {value['health_score']}/100（置信度 {value.get('score_confidence', 'low')}）"
    )
