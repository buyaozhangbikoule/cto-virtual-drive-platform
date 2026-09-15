from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(r"C:\Users\24739\Documents\Codex\2026-08-10\new-chat")
SOURCE = ROOT / "outputs" / "v2_self_consistent_rebuild" / "report_evidence_final" / "05_选频准则" / "stage3_window_step_aggregate.csv"
OUT = ROOT / "heatmap_regen_2026-08-26" / "output"
OUT.mkdir(parents=True, exist_ok=True)

mpl.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Microsoft YaHei", "DejaVu Sans", "sans-serif"],
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "font.size": 14,
        "axes.linewidth": 1.2,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
    }
)


def adaptive_text(ax, matrix, image, formatter):
    cmap = image.get_cmap()
    norm = image.norm
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            value = float(matrix[i, j])
            r, g, b, _ = cmap(norm(value))
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            color = "white" if luminance < 0.52 else "#111111"
            ax.text(
                j,
                i,
                formatter(value),
                ha="center",
                va="center",
                color=color,
                fontsize=15,
                fontweight="bold",
            )


df = pd.read_csv(SOURCE)
df = df[df["criterion"] == "max_power"].copy()

windows = [20.0, 50.0, 100.0]
steps = [0.1, 0.5, 1.0, 2.0]

err = (
    df.pivot(index="window_halfwidth_kHz", columns="step_kHz", values="max_total_error_vs_global_Hz")
    .reindex(index=windows, columns=steps)
    .to_numpy(dtype=float)
    / 1000.0
)
scan = (
    df.pivot(index="window_halfwidth_kHz", columns="step_kHz", values="scan_time_proxy_ms")
    .reindex(index=windows, columns=steps)
    .to_numpy(dtype=float)
)

if np.isnan(err).any() or np.isnan(scan).any():
    raise ValueError("The requested window/step grid is incomplete in the source CSV.")

fig, axes = plt.subplots(1, 2, figsize=(14.0, 4.8), constrained_layout=True)
fig.set_constrained_layout_pads(w_pad=0.08, h_pad=0.05, wspace=0.12, hspace=0.02)

cmap = mpl.colormaps["Blues"]
row_labels = ["±20", "±50", "±100"]
col_labels = ["0.1", "0.5", "1", "2"]

panels = [
    (
        axes[0],
        err,
        "Worst total frequency error (kHz)",
        0.0,
        float(np.nanmax(err)),
        lambda x: f"{x:.1f}",
        "Error (kHz)",
    ),
    (
        axes[1],
        scan,
        "Scan-time proxy (ms)",
        0.0,
        float(np.nanmax(scan)),
        lambda x: f"{x:.0f}",
        "Time (ms)",
    ),
]

for ax, matrix, title, vmin, vmax, formatter, cbar_label in panels:
    image = ax.imshow(matrix, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
    adaptive_text(ax, matrix, image, formatter)

    ax.set_title(title, fontsize=19, fontweight="bold", pad=14)
    ax.set_xlabel("Step size (kHz)", fontsize=16, labelpad=10)
    ax.set_ylabel("Window half-width (kHz)", fontsize=16, labelpad=12)
    ax.set_xticks(np.arange(len(col_labels)), labels=col_labels)
    ax.set_yticks(np.arange(len(row_labels)), labels=row_labels)
    ax.tick_params(axis="both", labelsize=14, length=0, pad=7)

    # Crisp white cell boundaries improve projection readability.
    ax.set_xticks(np.arange(-0.5, matrix.shape[1], 1), minor=True)
    ax.set_yticks(np.arange(-0.5, matrix.shape[0], 1), minor=True)
    ax.grid(which="minor", color="white", linestyle="-", linewidth=1.5)
    ax.tick_params(which="minor", bottom=False, left=False)

    cbar = fig.colorbar(image, ax=ax, fraction=0.046, pad=0.025)
    cbar.ax.tick_params(labelsize=12, width=1.0)
    cbar.set_label(cbar_label, fontsize=13, labelpad=8)
    cbar.outline.set_linewidth(1.0)

# Subtle emphasis around the recommended ±50 kHz / 1 kHz combination.
recommended = mpl.patches.Rectangle(
    (2 - 0.5, 1 - 0.5),
    1,
    1,
    fill=False,
    edgecolor="#E69F00",
    linewidth=2.6,
)
for ax in axes:
    ax.add_patch(recommended if ax is axes[0] else mpl.patches.Rectangle(
        (2 - 0.5, 1 - 0.5), 1, 1, fill=False, edgecolor="#E69F00", linewidth=2.6
    ))

stem = OUT / "window_step_tradeoff_heatmap_high_contrast"
fig.savefig(stem.with_suffix(".svg"), bbox_inches="tight")
fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
fig.savefig(stem.with_suffix(".png"), dpi=300, bbox_inches="tight")
plt.close(fig)

print(stem.with_suffix(".png"))
