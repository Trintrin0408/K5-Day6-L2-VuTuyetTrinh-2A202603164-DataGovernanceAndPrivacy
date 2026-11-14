"""YOUR PoC PIPELINE — this is the file your group owns.

Lab contract = 5 automated steps, run by `python -m src.main ...`:
    01 load      input + provenance check (manifest.csv)
    02 process   your algorithm / model (the research part)
    03 rank      prioritise for a fixed review budget B
    04 review    human-in-the-loop: queue -> reviewer decisions -> overrides + audit log
    05 decide    GO / HOLD / REWORK (or track equivalent) with reason_code + owner, write outputs

Required output: out/<pred_file> with the columns listed for your track in
docs/tracks/TXX.md (also in src/metrics/tracks.py::TRACKS). Then evaluate with
    python -m src.evaluate --track tXX --pred out/<pred_file>

Rules: never read fixtures/*/gt/ here (the GT guard will stop you); seed everything via ctx.rng;
no network calls; fail loudly on missing models instead of downloading.
See src/examples/random_baseline.py for a minimal end-to-end wiring example.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .common.contact_sheet import render_contact_sheet
from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.image_ops import brightness_stats, laplacian_variance, load_rgb, to_gray
from .common.manifest import verify_manifest
from .common.review import load_review_decisions, make_review_queue, write_review_queue
from .metrics.tracks import get_track


# ---------------------------------------------------------------- 01 load
def load(ctx: RunContext) -> dict:
    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems:
        ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")
    images_path = ctx.input_dir / "images.csv"
    if not images_path.exists():
        raise FileNotFoundError(f"missing T02 input table: {images_path}")

    images = pd.read_csv(images_path)
    required = {"image_id", "path", "camera_id", "light", "split"}
    missing = sorted(required - set(images.columns))
    if missing:
        raise ValueError(f"images.csv missing columns: {missing}")
    if images["image_id"].duplicated().any():
        raise ValueError("images.csv contains duplicate image_id values")

    missing_images = [
        str(ctx.input_dir / str(p))
        for p in images["path"]
        if not (ctx.input_dir / str(p)).exists()
    ]
    if missing_images:
        raise FileNotFoundError(f"missing image files, first: {missing_images[:3]}")

    data = {
        "manifest": pd.read_csv(manifest) if manifest.exists() else None,
        "images": images,
    }
    return data


# ---------------------------------------------------------------- 02 process
def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def _compression_score(img: np.ndarray) -> float:
    """Small JPEG-blockiness proxy; it is a ranking feature, not a label."""
    gray = to_gray(img)
    if gray.shape[1] < 16:
        return 0.0

    horizontal = np.abs(np.diff(gray, axis=1))
    boundary_positions = np.arange(7, horizontal.shape[1], 8)
    boundary = float(horizontal[:, boundary_positions].mean()) if len(boundary_positions) else 0.0
    non_boundary = np.delete(horizontal, boundary_positions, axis=1)
    interior = float(non_boundary.mean()) if non_boundary.size else 0.0
    ratio = boundary / max(interior, 1.0)
    return _clip01((ratio - 1.0) / 1.5)


def _quality_features(img: np.ndarray) -> dict[str, float]:
    sharpness = laplacian_variance(img)
    brightness = brightness_stats(img)

    # Fixed, interpretable transforms. They do not use GT labels or eval labels.
    blur_score = _clip01(1.0 - sharpness / (sharpness + 75.0))
    dark_score = 0.7 * _clip01((55.0 - brightness["mean"]) / 55.0)
    dark_score += 0.3 * _clip01(brightness["frac_dark"] / 0.50)
    glare_score = 0.5 * _clip01((brightness["p95"] - 220.0) / 35.0)
    glare_score += 0.5 * _clip01(brightness["frac_saturated"] / 0.08)
    compression_score = _compression_score(img)

    score = (
        0.45 * blur_score
        + 0.25 * dark_score
        + 0.20 * glare_score
        + 0.10 * compression_score
    )
    reasons = []
    if blur_score >= 0.45:
        reasons.append("blur")
    if dark_score >= 0.45:
        reasons.append("dark")
    if glare_score >= 0.45:
        reasons.append("glare")
    if compression_score >= 0.45:
        reasons.append("compression")

    return {
        "sharpness": round(sharpness, 6),
        "brightness_mean": round(brightness["mean"], 6),
        "frac_dark": round(brightness["frac_dark"], 6),
        "frac_saturated": round(brightness["frac_saturated"], 6),
        "blur_score": round(blur_score, 6),
        "dark_score": round(dark_score, 6),
        "glare_score": round(glare_score, 6),
        "compression_score": round(compression_score, 6),
        "score": round(float(score), 6),
        "reason": "+".join(reasons) if reasons else "no_strong_signal",
    }


def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    if ctx.track != "t02":
        spec = get_track(ctx.track)
        raise NotImplementedError(f"This PoC pipeline implements T02, not {spec.track}")

    rows = []
    images = data["images"]
    for row in images.itertuples(index=False):
        image_path = ctx.input_dir / Path(str(row.path))
        features = _quality_features(load_rgb(image_path))
        rows.append(
            {
                "image_id": str(row.image_id),
                "path": str(row.path),
                "camera_id": str(row.camera_id),
                "light": str(row.light),
                "split": str(row.split),
                **features,
                "suggested_action": "RECAPTURE" if features["score"] >= 0.45 else "KEEP",
                "pred_action": "",
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 03 rank
def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    """Default: top-B by `score`. Adapt id/score/reason columns to your track."""
    budget = int(ctx.param("budget", 20))
    if "score" not in scored.columns:
        raise ValueError("rank(): process() output needs a numeric `score` column (higher = review first), "
                         "or adapt rank() to your track")
    q = make_review_queue(
        scored,
        id_col="image_id",
        score_col="score",
        budget=budget,
        reason_col="reason" if "reason" in scored.columns else None,
        action_col="suggested_action" if "suggested_action" in scored.columns else None,
        slice_col="light" if "light" in scored.columns else None,
        evidence_col="path" if "path" in scored.columns else None,
    )
    write_review_queue(q, ctx.out("review_queue.csv"))
    render_contact_sheet(q, ctx.out("contact_sheet.html"), image_root=ctx.input_dir, title="T02 raw QC review queue")
    return q


# ---------------------------------------------------------------- 04 review
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    """If a reviewed queue exists (out/review_queue_reviewed.csv), apply it. Otherwise pass through.

    TODO: decide what an `edit` / `reject` means for your track and apply it
    (e.g. via common.review.apply_overrides), logging every change to ctx.audit.
    """
    reviewed_path = ctx.output_dir / "review_queue_reviewed.csv"
    if reviewed_path.exists():
        reviewed = load_review_decisions(reviewed_path)
        ctx.stats["n_reviewed"] = len(reviewed)
        action_map = {"approve": "KEEP", "reject": "RECAPTURE", "escalate": "HOLD"}
        for row in reviewed.itertuples(index=False):
            action = action_map.get(str(row.reviewer_decision).lower())
            if not action:
                continue
            mask = scored["image_id"].astype(str) == str(row.item_id)
            scored.loc[mask, "pred_action"] = action
            ctx.audit.log(
                actor=row.reviewer,
                action=f"review:{row.reviewer_decision}",
                item_id=row.item_id,
                after=action,
                reason=row.review_note,
            )
    else:
        ctx.stats["n_reviewed"] = 0
    return scored


# ---------------------------------------------------------------- 05 decide
def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    owner = ctx.config.get("owner", "").strip()
    if not owner or owner.startswith("TODO"):
        owner = "T02 reviewer"

    reviewed = final[final["pred_action"].astype(str).isin({"KEEP", "RECAPTURE", "HOLD"})]
    if len(reviewed) == 0:
        return Decision(
            status="HOLD",
            reason_code="REVIEW_REQUIRED",
            reason="Top-20 queue has not been reviewed yet",
            owner=owner,
            scope=ctx.track,
            evidence=[str(ctx.out("review_queue.csv")), str(ctx.out("contact_sheet.html"))],
        )

    n_recap = int((reviewed["pred_action"] == "RECAPTURE").sum())
    if n_recap:
        status, code, reason = "REWORK", "RECAPTURE_REQUIRED", f"{n_recap} reviewed image(s) require recapture"
    else:
        status, code, reason = "GO", "REVIEWED_KEEP", "Reviewed queue contains no recapture decision"
    return Decision(
        status=status,
        reason_code=code,
        reason=reason,
        owner=owner,
        scope=ctx.track,
        evidence=[str(ctx.out("review_queue.csv")), str(ctx.out("audit_log.jsonl"))],
    )


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    final = final.sort_values("score", ascending=False, kind="mergesort").reset_index(drop=True)
    final[spec.pred_columns + [c for c in final.columns if c not in spec.pred_columns]].to_csv(ctx.out(spec.pred_file), index=False)
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))
