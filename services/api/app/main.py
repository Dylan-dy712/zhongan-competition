"""FastAPI 服务：读取离线运行产物，提供案件/事实/痛点/报告/推荐/反馈接口。

原型阶段：运行产物来自 scripts/run_offline.py（文件存储），服务只读 + 反馈写入；
触发新运行走同步执行（spec §4.1 第一版单服务 + 任务表的简化形态，文件即任务产物）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import get_settings

app = FastAPI(title="众安·暖愈智护 原型 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def _runs_dir() -> Path:
    s = get_settings()
    d = Path(s.work_dir or "./work") / "runs"
    if not d.is_dir():
        raise HTTPException(503, "runs 目录未配置")
    return d


def _profiles_path() -> Path:
    s = get_settings()
    return Path(s.work_dir or "./work") / "profiles.json"


def _load_run(case_id: str) -> dict:
    p = _runs_dir() / f"{case_id}.json"
    if not p.is_file():
        raise HTTPException(404, f"case {case_id} not found")
    return json.loads(p.read_text(encoding="utf-8"))


def _safe_case(case_id: str) -> str:
    if not case_id or not all(c.isalnum() for c in case_id):
        raise HTTPException(422, "invalid case id")
    return case_id


class FeedbackIn(BaseModel):
    case_id: str
    report_version: int = 1
    action_index: int | None = None
    type: str  # understood | unclear | verify_fact | action_done | action_deferred | need_help
    text: str | None = None


@app.get("/v1/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/v1/cases")
def list_cases() -> dict:
    out = []
    for f in sorted(_runs_dir().glob("*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        facts = r.get("facts", {})
        enc = (facts.get("encounters") or [{}])[0]
        out.append(
            {
                "case_id": r["case_id"],
                "status": r.get("status"),
                "guidance_mode": r.get("stages", {}).get("guidance", {}).get("mode"),
                "hospital": (enc.get("hospital") or {}).get("value"),
                "admission_date": (enc.get("admission_date") or {}).get("value"),
                "discharge_date": (enc.get("discharge_date") or {}).get("value"),
                "n_diagnoses": len(facts.get("diagnoses", [])),
                "n_pages": len(r.get("facts", {}).get("evidences", [])) and None,
                "insight_labels": sorted({i["label_code"] for i in r.get("insights", [])}),
                "finished_at": r.get("finished_at"),
            }
        )
    return {"items": out, "count": len(out)}


@app.get("/v1/cases/{case_id}")
def get_case(case_id: str) -> dict:
    r = _load_run(_safe_case(case_id))
    return {
        "case_id": r["case_id"],
        "run_id": r["run_id"],
        "status": r["status"],
        "execution_mode": r["execution_mode"],
        "stages": r["stages"],
        "llm_usage": r.get("llm_usage"),
    }


@app.get("/v1/cases/{case_id}/facts")
def get_facts(case_id: str) -> dict:
    return _load_run(_safe_case(case_id))["facts"]


@app.get("/v1/cases/{case_id}/insights")
def get_insights(case_id: str) -> dict:
    return {"items": _load_run(_safe_case(case_id))["insights"]}


@app.get("/v1/cases/{case_id}/reports/{version}")
def get_report(case_id: str, version: int) -> dict:
    r = _load_run(_safe_case(case_id))
    rep = r.get("report", {})
    if int(rep.get("report_version", 1)) != version:
        raise HTTPException(404, "report version not found")
    return rep


@app.get("/v1/cases/{case_id}/recommendations")
def get_recs(case_id: str) -> dict:
    return {"items": _load_run(_safe_case(case_id)).get("recommendations", [])}


@app.get("/v1/profiles")
def get_profiles() -> dict:
    p = _profiles_path()
    if not p.is_file():
        raise HTTPException(404, "profiles not built")
    return json.loads(p.read_text(encoding="utf-8"))


_FEEDBACK_FILE = "feedback.jsonl"


@app.post("/v1/feedback")
def post_feedback(fb: FeedbackIn) -> dict:
    _safe_case(fb.case_id)
    if fb.type not in {"understood", "unclear", "verify_fact", "action_done", "action_deferred", "need_help"}:
        raise HTTPException(422, "invalid feedback type")
    rec = {
        "feedback_id": str(uuid.uuid4()),
        "case_id": fb.case_id,
        "report_version": fb.report_version,
        "action_index": fb.action_index,
        "type": fb.type,
        "text": fb.text,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = _runs_dir().parent / _FEEDBACK_FILE
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"status": "accepted", "feedback_id": rec["feedback_id"]}


# 演示前端（静态页）
_web_dir = Path(__file__).resolve().parents[2] / "web" / "dist"
if _web_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_web_dir), html=True), name="web")
