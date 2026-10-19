"""Plot completed, integrity-validated primary queue measurements only.

Example (with the available plotting dependencies on PYTHONPATH):
    python scripts/plot_measured_results.py --run runs/COHORT --out-dir figures/COHORT

No synthetic actor outcomes, incomplete cohorts, or invented uncertainty bands
are accepted. The JSON sidecar contains the exact points, included episode
values, counts, and source hashes needed to reconstruct the figure.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from build_empirical_paper import load_run
from permission_thresholds.study_v2_analysis import summarize


LEVELS = ("low", "mid", "high")


def collect_points(manifest, rows):
    """Return three complete primary families, never pooling model versions."""
    report = summarize(rows)
    if len(report["groups"]) != 1:
        raise ValueError("One model/configuration is required per figure")
    primary = [stratum for stratum in report["groups"][0]["strata"] if stratum["primary"]]
    if len(primary) != 1:
        raise ValueError("A healthy-queue, literal-only primary stratum is required")
    tracking = primary[0]["threshold_tracking"]
    if tracking["complete_families"] != 3 or tracking["incomplete_families"]:
        raise ValueError("The figure requires all three primary families with valid low/mid/high operative and placebo arms; no missing outcomes are imputed")
    primary_rows = [row for row in rows if row["mechanism"] == "queue"
                    and row["initial_context"] == "healthy"
                    and row["condition"]["instruction_ablation"] == "literal_only"]
    families = []
    for family in tracking["family_results"]:
        series = {}
        for kind in ("conditional", "placebo"):
            points = []
            for level in LEVELS:
                arm = f"{kind}_{level}"
                point = family["arm_means"][arm]
                episodes = [row for row in primary_rows if row["family_id"] == family["family_id"]
                            and row["condition"]["arm"] == arm]
                valid = [row for row in episodes if row["episode_status"] != "model_error"]
                points.append({"level": level, "arm": arm,
                               "displayed_threshold": point["displayed_threshold"],
                               "required_additional_load": point["x"],
                               "mean_added_peak_load_before_completion": point["mean_outcome"],
                               "valid_episodes": point["valid_episodes"], "attempted_episodes": len(episodes),
                               "model_errors": len(episodes) - len(valid),
                               "episode_values": [{"run_id": row["run_id"], "scenario_id": row["scenario_id"],
                                                   "condition_id": row["condition"]["condition_id"],
                                                   "repeat": row["repeat"], "episode_status": row["episode_status"],
                                                   "initial_load": row["metrics"]["initial_load"],
                                                   "added_peak_load_before_completion": row["metrics"]["peak_load_before_completion"] - row["metrics"]["initial_load"]}
                                                  for row in valid]})
            series[kind] = points
        families.append({"family_id": family["family_id"], "series": series,
                         "conditional_slope": family["conditional_slope"],
                         "placebo_slope": family["placebo_slope"], "slope_difference": family["slope_difference"]})
    return {"figure_schema_version": "1.0", "results_are_synthetic": False,
            "model": manifest["config"]["model"], "model_digest": manifest["model_digest"],
            "scope": {"mechanism": "queue", "initial_context": "healthy", "instruction_ablation": "literal_only"},
            "x_variable": "displayed_threshold - initial_load",
            "y_variable": "mean(peak_load_before_completion - initial_load)",
            "averaging": "Within-family, within-arm mean over completed or budget-exhausted rollouts; model-error prefixes are excluded from plotted means and counted explicitly.",
            "uncertainty": "No confidence intervals are plotted. Parameter variants are authored development families, not independent held-out domains.",
            "interpretation": "Descriptive threshold-response curves; neither slope nor slope contrast establishes intent or general safety.",
            "families": families, "mean_slope_difference": tracking["mean_slope_difference"]}


def draw_figure(points, output_prefix):
    """Generate a compact, shared-axis three-facet publication figure."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    families = points["families"]
    all_points = [point for family in families for series in family["series"].values() for point in series]
    max_x = max(point["required_additional_load"] for point in all_points)
    max_y = max(point["mean_added_peak_load_before_completion"] for point in all_points)
    # Common unit scales and zero origins prevent facet-dependent magnification.
    ceiling = max(10.0, max_x, max_y) * 1.08
    counts = sorted({point["valid_episodes"] for point in all_points})
    n_text = str(counts[0]) if len(counts) == 1 else f"{min(counts)}–{max(counts)}"
    errors = sum(point["model_errors"] for point in all_points)
    style = {
        "conditional": {"color": "#0072B2", "marker": "o", "linestyle": "-", "markersize": 4.3,
                        "markerfacecolor": "white", "label": "Operative threshold"},
        "placebo": {"color": "#D55E00", "marker": "s", "linestyle": "--", "markersize": 6,
                    "markerfacecolor": "none", "label": "Visible placebo"},
    }
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 8,
                         "axes.titlesize": 9, "axes.labelsize": 8,
                         "xtick.labelsize": 7, "ytick.labelsize": 7,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.linewidth": 0.7, "lines.linewidth": 1.5,
                         "svg.fonttype": "none", "savefig.facecolor": "white"}):
        fig, axes = plt.subplots(1, 3, figsize=(6.8, 2.7), sharex=True, sharey=True)
        for axis, family in zip(axes, families):
            axis.plot([0, ceiling], [0, ceiling], color="#929292", linestyle=":", linewidth=0.8,
                      label="Load needed to reach displayed threshold", zorder=1)
            for kind in ("conditional", "placebo"):
                series = family["series"][kind]
                axis.plot([p["required_additional_load"] for p in series],
                          [p["mean_added_peak_load_before_completion"] for p in series],
                          markeredgewidth=1.2,
                          clip_on=False, **style[kind])
            axis.set_title(family["family_id"].replace("v2_queue_", "Queue family "))
            axis.set_xlim(0, ceiling)
            axis.set_ylim(0, ceiling)
            axis.xaxis.set_major_locator(MaxNLocator(nbins=4, integer=True))
            axis.yaxis.set_major_locator(MaxNLocator(nbins=4, integer=True))
            axis.grid(axis="both", color="#E5E7EB", linewidth=0.55, zorder=0)
            axis.set_axisbelow(True)
            axis.tick_params(length=3, width=0.6)
        fig.supylabel("Added peak load before report completion", x=0.015, fontsize=8)
        fig.supxlabel("Required additional queue load", y=0.27, fontsize=8)
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles[1:], labels[1:], loc="lower center", bbox_to_anchor=(0.52, 0.12), ncol=2,
                   frameon=False, fontsize=8, handlelength=2.5, columnspacing=2)
        fig.legend(handles[:1], labels[:1], loc="lower center", bbox_to_anchor=(0.52, 0.05),
                   frameon=False, fontsize=7, handlelength=2.5)
        fig.suptitle(f"Primary queue evaluation · {points['model']}", y=0.99, fontsize=10)
        footnote = f"n = {n_text} valid rollout(s) per point; connecting lines guide the eye. No uncertainty intervals."
        if errors:
            footnote += f" {errors} model-error episode(s) excluded."
        fig.text(0.52, 0.01, footnote, ha="center", va="bottom", fontsize=6.8, color="#444444")
        fig.subplots_adjust(left=0.095, right=0.99, bottom=0.42, top=0.82, wspace=0.17)
        fig.savefig(output_prefix.with_suffix(".png"), dpi=400)
        fig.savefig(output_prefix.with_suffix(".svg"))
        plt.close(fig)
    return {"matplotlib_version": matplotlib.__version__, "width_inches": 6.8, "height_inches": 2.7, "png_dpi": 400,
            "axes": {"shared": True, "x_min": 0, "y_min": 0, "x_max": ceiling, "y_max": ceiling},
            "styles": style, "confidence_intervals": False,
            "reference_line": {"equation": "y = x", "color": "#929292", "label": "Load needed to reach displayed threshold"},
            "connecting_lines": "guides to the eye, not fitted regressions"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="Completed measured main-cohort directory")
    parser.add_argument("--out-dir", type=Path, required=True, help="New directory for PNG, SVG, and point/provenance JSON")
    args = parser.parse_args(argv)
    if args.out_dir.exists():
        raise FileExistsError("Choose a new figure output directory; existing artifacts are not overwritten")
    manifest, rows = load_run(args.run, capability_only=False)
    points = collect_points(manifest, rows)
    args.out_dir.mkdir(parents=True, exist_ok=False)
    prefix = args.out_dir / "primary-threshold-curves"
    points["rendering"] = draw_figure(points, prefix)
    points["provenance"] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(), "run_directory": str(args.run.resolve()),
        "run_id": manifest["run_id"], "run_status": manifest["status"],
        "main_cohort_episodes": len(rows), "episodes_sha256": manifest["output_sha256"],
        "config_sha256": manifest["config_sha256"], "source_sha256": manifest["source_sha256"],
        "model_settings": manifest["config"]["model_settings"],
        "analysis_code_sha256": hashlib.sha256((Path(__file__).resolve().parents[1] / "src/permission_thresholds/study_v2_analysis.py").read_bytes()).hexdigest(),
        "plot_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "loader_code_sha256": hashlib.sha256(Path(__file__).with_name("build_empirical_paper.py").read_bytes()).hexdigest(),
        "output_sha256": {suffix: hashlib.sha256(prefix.with_suffix(suffix).read_bytes()).hexdigest() for suffix in (".png", ".svg")},
    }
    prefix.with_suffix(".json").write_text(json.dumps(points, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"png": str(prefix.with_suffix('.png').resolve()),
                      "svg": str(prefix.with_suffix('.svg').resolve()),
                      "data_and_provenance": str(prefix.with_suffix('.json').resolve())}))


if __name__ == "__main__":
    main()
