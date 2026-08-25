"""AI-selected, bounded browser download and learned-procedure installation."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import parse_qsl, unquote, urlparse

from . import browser
from . import game_content


MAX_LINK_HOPS = 3
MAX_LINK_ACTIVATIONS = 5


def _select_link(
    manifest,
    procedure,
    page_url,
    links,
    rejected_link_ids=None,
):
    import tools

    rejected = {
        str(value) for value in (rejected_link_ids or []) if str(value)
    }
    available_links = [
        item
        for item in links
        if isinstance(item, dict)
        and str(item.get("id") or "")
        and str(item.get("id") or "") not in rejected
    ]
    if not available_links:
        return ""
    payload = {
        "decision_task": (
            "Select one supplied opaque link ID that downloads the declared "
            "artifact or advances to its dedicated download page."
        ),
        "artifact": {
            "name": manifest.get("artifact_name"),
            "target_app": manifest.get("target_app"),
            "content_kind": manifest.get("content_kind"),
            "compatibility": manifest.get("compatibility"),
            "expected_file_types": procedure.get("expected_file_types", []),
        },
        "current_page_url": page_url,
        "structurally_rejected_link_ids": sorted(rejected),
        "untrusted_link_catalog": available_links,
    }
    valid_ids = {str(item.get("id")) for item in available_links}
    attempts = (
        ("prompts/casper_content_download_link.txt", 900),
        ("prompts/casper_content_download_link_retry.txt", 1400),
    )
    previous_invalid = None
    for prompt_path, output_budget in attempts:
        attempt_payload = dict(payload)
        if previous_invalid is not None:
            attempt_payload["previous_invalid_output"] = previous_invalid
        result = tools.run_ai_prompt(
            prompt_path,
            json.dumps(
                attempt_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            expect_json=True,
            num_ctx=8192,
            num_predict=output_budget,
            think=False,
            model_name="gemma3:12b",
        )
        selected_id = (
            str(result.get("link_id") or "")
            if isinstance(result, dict)
            else ""
        )
        if selected_id in valid_ids:
            return selected_id
        if (
            isinstance(result, dict)
            and "link_id" in result
            and result.get("link_id") is None
        ):
            return ""
        previous_invalid = result if isinstance(result, dict) else None
    return ""


def _recovery_source_id(url):
    return "source_" + hashlib.sha256(
        str(url).encode("utf-8", errors="ignore")
    ).hexdigest()[:16]


def _page_identity(url):
    parsed = urlparse(str(url).strip())
    host = parsed.netloc.casefold().removeprefix("www.")
    path = unquote(parsed.path or "/").rstrip("/") or "/"
    query = tuple(sorted(
        (key.casefold(), value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in {"gclid", "fbclid", "msclkid"}
    ))
    return host, path, query


def _generate_artifact_recovery_query(manifest, procedure, source_url):
    import tools

    payload = {
        "artifact": {
            "name": manifest.get("artifact_name"),
            "target_app": manifest.get("target_app"),
            "content_kind": manifest.get("content_kind"),
            "compatibility": manifest.get("compatibility"),
            "expected_file_types": procedure.get("expected_file_types", []),
        },
        "current_source_url": source_url,
    }
    attempts = (
        ("prompts/casper_content_artifact_recovery_query.txt", 500),
        ("prompts/casper_content_artifact_recovery_query_retry.txt", 700),
    )
    for prompt_path, output_budget in attempts:
        result = tools.run_ai_prompt(
            prompt_path,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=4096,
            num_predict=output_budget,
            think=False,
            model_name="llama3.2:latest",
        )
        query = (
            str(result.get("query") or "").strip()[:300]
            if isinstance(result, dict)
            else ""
        )
        if query:
            return query
    return ""


def _select_recovery_source(
    manifest,
    procedure,
    source_url,
    results,
    rejected_source_ids=None,
):
    import tools

    catalog = []
    by_id = {}
    rejected = {
        str(value) for value in (rejected_source_ids or []) if str(value)
    }
    for item in results[:12]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        source_id = _recovery_source_id(url)
        if source_id in rejected:
            continue
        by_id[source_id] = url
        catalog.append({
            "id": source_id,
            "title": str(item.get("title") or "")[:300],
            "description": str(item.get("description") or "")[:700],
            "domain": str(item.get("domain") or "")[:160],
        })
    if not catalog:
        return ""
    payload = {
        "artifact": {
            "name": manifest.get("artifact_name"),
            "target_app": manifest.get("target_app"),
            "content_kind": manifest.get("content_kind"),
            "compatibility": manifest.get("compatibility"),
            "expected_file_types": procedure.get("expected_file_types", []),
        },
        "previous_index_url": source_url,
        "structurally_rejected_source_ids": sorted(rejected),
        "untrusted_search_result_catalog": catalog,
    }
    attempts = (
        ("llama3.2:latest", 600),
        ("gemma3:12b", 1200),
    )
    for model_name, output_budget in attempts:
        result = tools.run_ai_prompt(
            "prompts/casper_content_artifact_recovery_source.txt",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=4096,
            num_predict=output_budget,
            think=False,
            model_name=model_name,
        )
        selected_id = (
            str(result.get("source_id") or "")
            if isinstance(result, dict)
            else ""
        )
        if selected_id in by_id:
            return {"id": selected_id, "url": by_id[selected_id]}
    return None


def _recover_artifact_source(manifest, procedure, source_url):
    query = _generate_artifact_recovery_query(
        manifest, procedure, source_url
    )
    if not query:
        return {"status": "NO_MATCH"}
    discovery = browser.discover_web(
        query,
        count=6,
        multi_engine=True,
    )
    if discovery.get("status") == "HUMAN_HANDOFF":
        return {
            "status": "HUMAN_HANDOFF",
            "event": discovery.get("event") or "access_block",
        }
    rejected_source_ids = []
    for _attempt in range(3):
        selected = _select_recovery_source(
            manifest,
            procedure,
            source_url,
            discovery.get("results", []),
            rejected_source_ids=rejected_source_ids,
        )
        if not selected:
            return {"status": "NO_MATCH"}
        selected_url = str(selected.get("url") or "")
        if not selected_url:
            return {"status": "NO_MATCH"}
        resolved = browser.list_page_links(selected_url, maximum=24)
        if resolved.get("status") == "HUMAN_HANDOFF":
            return {
                "status": "HUMAN_HANDOFF",
                "event": resolved.get("event") or "access_block",
            }
        final_url = str(resolved.get("page_url") or selected_url)
        if _page_identity(final_url) == _page_identity(source_url):
            rejected_source_ids.append(str(selected.get("id") or ""))
            continue
        return {"status": "OK", "url": final_url}
    return {"status": "NO_MATCH"}


def _validate_download(path, expected_file_types):
    candidate = Path(path)
    expected = {
        str(value).casefold().strip()
        for value in expected_file_types
        if str(value).strip().startswith(".")
    }
    if expected and candidate.suffix.casefold() not in expected:
        raise OSError("The downloaded file type does not match learned evidence.")
    if candidate.suffix.casefold() != ".fmf":
        raise OSError("The current local adapter accepts only .fmf tactics.")
    if not candidate.is_file() or candidate.is_symlink():
        raise OSError("The downloaded artifact is not a regular file.")
    size = candidate.stat().st_size
    if size <= 0 or size > game_content.MAX_TACTIC_BYTES:
        raise OSError("The downloaded tactic has an unsafe size.")
    with candidate.open("rb") as handle:
        if handle.read(2) == b"MZ":
            raise OSError("The downloaded tactic contains an executable header.")


def execute(manifest, procedure):
    if str(procedure.get("skill_scope") or "") != "INSTALL_CONTENT":
        return _clarify(
            "保存的技能范围不是内容安装，不能执行下载或复制操作。"
        )
    if str(procedure.get("local_adapter") or "") != "FM_TACTIC":
        return _clarify("保存的安装方法没有可执行的本地适配器。")
    source_url = str(manifest.get("source_url") or "").strip()
    if not source_url:
        return _clarify("所选内容没有可验证的浏览器来源地址。")
    temporary_root = tempfile.mkdtemp(prefix="Bekki-content-")
    current_url = source_url
    try:
        navigation_hops = 0
        activation_attempts = 0
        recovery_used = False
        rejected_by_page = {}
        while (
            activation_attempts < MAX_LINK_ACTIVATIONS
            and navigation_hops < MAX_LINK_HOPS
        ):
            catalog = browser.list_page_links(current_url, maximum=100)
            if catalog.get("status") == "HUMAN_HANDOFF":
                return {
                    "success": False,
                    "completed": False,
                    "needs_clarification": False,
                    "protected_event": catalog.get("event") or "access_block",
                    "resume_skill_id": str(procedure.get("id") or ""),
                    "reason": "The selected download page requires verification.",
                }
            resolved_page_url = str(catalog.get("page_url") or "").strip()
            if resolved_page_url:
                current_url = resolved_page_url
            links = catalog.get("links", [])
            page_key = _page_identity(current_url)
            rejected_link_ids = rejected_by_page.setdefault(page_key, set())
            link_id = _select_link(
                manifest,
                procedure,
                current_url,
                links,
                rejected_link_ids=rejected_link_ids,
            )
            if not link_id:
                if not recovery_used and navigation_hops == 0:
                    recovery_used = True
                    recovery = _recover_artifact_source(
                        manifest, procedure, current_url
                    )
                    if recovery.get("status") == "HUMAN_HANDOFF":
                        return {
                            "success": False,
                            "completed": False,
                            "needs_clarification": False,
                            "protected_event": (
                                recovery.get("event") or "access_block"
                            ),
                            "resume_skill_id": str(
                                procedure.get("id") or ""
                            ),
                            "reason": (
                                "Exact artifact-page search requires "
                                "verification."
                            ),
                        }
                    recovered_url = str(recovery.get("url") or "")
                    if recovery.get("status") == "OK" and recovered_url:
                        current_url = recovered_url
                        continue
                return _clarify("AI 没有在来源页面中找到可靠的战术下载链接。")
            action = browser.activate_page_link(
                current_url, link_id, temporary_root
            )
            activation_attempts += 1
            if action.get("status") == "HUMAN_HANDOFF":
                return {
                    "success": False,
                    "completed": False,
                    "needs_clarification": False,
                    "protected_event": action.get("event") or "access_block",
                    "resume_skill_id": str(procedure.get("id") or ""),
                    "reason": "The download action requires verification.",
                }
            if action.get("status") == "DOWNLOADED":
                downloaded = action.get("path")
                try:
                    _validate_download(
                        downloaded, procedure.get("expected_file_types", [])
                    )
                except OSError as error:
                    return _clarify(str(error))
                return game_content.install_verified_fm_tactic(
                    downloaded,
                    procedure.get("verified_destination_path", ""),
                )
            if action.get("status") == "NAVIGATED" and action.get("url"):
                navigation_hops += 1
                current_url = str(action["url"])
                continue
            if action.get("status") in {
                "STRUCTURAL_NOOP",
                "NO_DOWNLOAD",
                "LINK_NOT_FOUND",
                "CLICK_FAILED",
            }:
                rejected_link_ids.add(str(link_id))
                continue
            return _clarify("来源页面没有触发可验证的文件下载。")
        if navigation_hops >= MAX_LINK_HOPS:
            return _clarify("下载链接经过过多跳转，已安全停止。")
        return _clarify("下载链接尝试次数过多，已安全停止。")
    finally:
        try:
            for child in Path(temporary_root).iterdir():
                if child.is_file() and not child.is_symlink():
                    child.unlink()
            Path(temporary_root).rmdir()
        except OSError:
            pass


def _clarify(message):
    return {
        "success": False,
        "completed": False,
        "needs_clarification": True,
        "clarification": message,
        "reason": message,
    }
