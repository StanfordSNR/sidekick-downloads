import math

from common import *
from experiment import *
from data.http import HTTPExperiment
from treatments.picoquic import treatment_map, NETWORK_SETTING as ns
from datetime import date, datetime
today = date.today()
now = datetime.now()
now_str = now.strftime('%Y-%m-%d_%H-%M-%S')

def short_ge_name(ge_string: str) -> str:
    # ge_string format: "p,r,bad,good"
    p, r, bad, good = [x.strip() for x in ge_string.split(",")]
    return f"p={p}%|r={r}%\nloss_b={bad}%|loss_g={good}%"


# This file will only collect data for GE scenarios.
# And plot a bar chart of the data found in notebook/ge_benchmark.ipynb

def TREATMENTS():
    return [treatment_map(TREATMENT_NAME_TO_LABEL[name]) for name in TREATMENT_ORDER]


TREATMENT_NAME_TO_LABEL = {
    "End-to-End": "picoquic",
    "Tunnel (Ordered)": "picoquic_rtunnel_retx7_ordered32",
    "Tunnel (Unordered)": "picoquic_rtunnel_retx7",
    "Split Connection": "picoquic_split",
    "Packrat": "picoquic_iblt_30ms_hint",
}

TREATMENT_ORDER = [
    "End-to-End",
    "Tunnel (Ordered)",
    "Tunnel (Unordered)",
    "Split Connection",
    "Packrat",
]

# only 4 scenarios
GE_SCENARIOS = [
    {"name": "p=25%,r=100%,b_loss=80%,g_loss=2%", "ge": "25,100,80,2"},
    {"name": "p=66%,r=100%,b_loss=80%,g_loss=2%", "ge": "66,100,80,2"},
    {"name": "p=29%,r=78%,b_loss=80%,g_loss=2%", "ge": "29,78,80,2"},
    {"name": "p=43%,r=42%,b_loss=80%,g_loss=2%", "ge": "43,42,80,2"},
]

def NETWORK_SETTINGS_GE(
    scenarios=GE_SCENARIOS,
    bw1=ns.get('bw1'), bw2=ns.get('bw2'),
    delay1=ns.get('delay1'), delay2=ns.get('delay2')
):
    nets = []
    for sc in scenarios:
        nets.append(
            NetworkSetting(
                bw1=bw1, bw2=bw2,
                delay1=delay1, delay2=delay2,
                loss1='0', loss2='0',
                ge=sc["ge"],
                qdisc=ns.get('qdisc'),
                jitter1=ns.get('jitter1'),
                jitter2=ns.get('jitter2'),
            )
        )
    return nets

max_networks = {
    TREATMENT_NAME_TO_LABEL["End-to-End"]: 7,
    TREATMENT_NAME_TO_LABEL["Tunnel (Ordered)"]: 18,
    TREATMENT_NAME_TO_LABEL["Tunnel (Unordered)"]: 14,
    TREATMENT_NAME_TO_LABEL["Split Connection"]: 18,
    TREATMENT_NAME_TO_LABEL["Packrat"]: 18,
}

max_data_sizes = {
    TREATMENT_NAME_TO_LABEL["End-to-End"]: 10000000,
}

def collect_loss_vs_metric_data(treatments, network_settings, data_size, n=10, max_networks=max_networks, execute=False, min_i=1):
    if execute:
        num_trials_range = range(min_i, n+1)
    else:
        num_trials_range = [n]
    for i in num_trials_range:
        exp = HTTPExperiment(num_trials=i, treatments=treatments, network_settings=network_settings, data_sizes=[data_size])
        raw_data = exp.to_raw_data(execute=execute, max_networks=max_networks)
    return raw_data

def collect_data_size_vs_throughput_data(treatments, network_setting, data_sizes, n=10, max_data_sizes=max_data_sizes, execute=False, min_i=1):
    if execute:
        num_trials_range = range(min_i, n+1)
    else:
        num_trials_range = [n]
    for i in num_trials_range:
        exp = HTTPExperiment(num_trials=i, treatments=treatments, network_settings=[network_setting], data_sizes=data_sizes)
        raw_data = exp.to_raw_data(execute=execute, max_data_sizes=max_data_sizes)
    return raw_data

DATA_SIZE = 20*125000*10

def plot_loss_vs_metric_line(data, title, ylabel, ncol=3, ylim=0, delta=25, pdf=None, style=False):
    plt.figure(figsize=(6, 3))
    
    keys = data.treatments
    data_size = data.data_sizes[0]

    # Plot each label
    labels = []
    for key in keys:
        xs = []
        ys_raw = []

        for network in data.network_settings:
            if data_size not in data.data[key][network]:
                continue
            network_setting = data.exp.get_network_setting(network)
            xs.append(float(network_setting.settings['loss1']))
            ys_raw.append(data.data[key][network][data_size])

        ys = [y.p(50) for y in ys_raw]
        yerr_lower = [y.p(50) - y.p(50-delta) for y in ys_raw]
        yerr_upper = [y.p(50+delta) - y.p(50) for y in ys_raw]
        if style:
            label = LABEL_MAP[key]
            sty = STYLE[label]
            title = None
            ylim = None
            plt.errorbar(xs, ys, yerr=(yerr_lower, yerr_upper), marker=sty.marker, markersize=sty.markersize, capsize=5, label=label, color=sty.color, linestyle=sty.linestyle)
        else:
            label = key
            plt.errorbar(xs, ys, yerr=(yerr_lower, yerr_upper), marker='.', capsize=5, label=label)
        print(label, list(zip(xs, ys)))
        labels.append(label)

    plt.title(title)
    plt.xlabel('Loss % Near Data Receiver')
    plt.ylabel(ylabel)
    plt.grid()
    plt.xlim(0)
    plt.ylim(ylim)
    plot_title_and_legend(title, labels, base_height=1.2, row_height=0.07, title_height=0.08, ncol=ncol)
    if pdf:
        save_pdf(pdf)
    else:
        plt.show()

def plot_data_size_vs_throughput(raw_data, title=None, ncol=2, pdf=None, style=False):
    plottable_data = raw_data.to_plottable_data('throughput_mbps')
    if not title:
        title = f'{data_size_str(plottable_data.data_sizes[0])} ({plottable_data.network_settings[0]})'
    ylabel = 'Goodput (Mbit/s)'
    plot_loss_vs_metric_line(plottable_data, title, ncol=ncol, ylabel=ylabel, pdf=pdf, style=style)

# Consistent bar positions
def grouped_bar_positions(num_groups, num_series, bar_width=0.14, group_gap=0.28):
    """Return x positions for each series in each group and the group centers."""
    centers = np.arange(num_groups) * (num_series * bar_width + group_gap)
    series_offsets = ((np.arange(num_series) - (num_series - 1) / 2.0) * bar_width)
    xs = [centers + off for off in series_offsets]
    return xs, centers

def plot_ge_vs_throughput_bars(raw_data, title=None, pdf=None, style=False):
    data = raw_data.to_plottable_data('throughput_mbps')

    # Build x-axis (GE scenarios) in the same order as provided
    exp = raw_data.exp
    net_labels = data.network_settings  # verbose labels
    # Map them to our GE_SCENARIOS order by matching 'ge' string
    ge_to_name = { sc["ge"]: sc["name"] for sc in GE_SCENARIOS }

    # Prepare category order
    cat_order = []
    cat_order_verbose = []
    for net_label in net_labels:
        ns_obj = exp.get_network_setting(net_label)
        ge_string = ns_obj.get('ge')
        if ge_string in ge_to_name:
            cat_order.append(ge_to_name[ge_string])
            cat_order_verbose.append(net_label)
        else:
            # Fallback: keep unknowns but make a short name
            cat_order.append(short_ge_name(ge_string))
            cat_order_verbose.append(net_label)

    # Series order = treatments in TREATMENT_ORDER
    series_labels = TREATMENT_ORDER

    # Collect y values: median and IQR for each (series, category)
    med = { s: [] for s in series_labels }
    low = { s: [] for s in series_labels }
    high = { s: [] for s in series_labels }

    delta = 25  # IQR: 25th to 75th
    for idx, cat in enumerate(cat_order):
        net_label_verbose = cat_order_verbose[idx]
        for s in series_labels:
            label_key = TREATMENT_NAME_TO_LABEL[s]
            # If missing (e.g., run didn't complete), put NaN
            if net_label_verbose not in data.data[label_key]:
                med[s].append(np.nan)
                low[s].append(0.0)
                high[s].append(0.0)
                continue
            per_size = data.data[label_key][net_label_verbose]
            # There's only one data size here; get its PlotStats
            data_size = data.data_sizes[0]
            if data_size not in per_size:
                med[s].append(np.nan)
                low[s].append(0.0)
                high[s].append(0.0)
                continue

            stats = per_size[data_size]
            m = stats.p(50)
            l = m - stats.p(50 - delta)
            h = stats.p(50 + delta) - m
            med[s].append(m)
            low[s].append(l)
            high[s].append(h)

    # Plot grouped bars
    num_groups = len(cat_order)
    num_series = len(series_labels)
    bar_width = 0.14
    xs, centers = grouped_bar_positions(num_groups, num_series, bar_width=bar_width, group_gap=0.28)

    plt.figure(figsize=(10, 4.2))
    plotted_labels = []
    for si, s in enumerate(series_labels):
        vals = med[s]
        el = low[s]
        eh = high[s]
        # If you have STYLE/LABEL_MAP and want fancier styling, you can use it here.
        b = plt.bar(xs[si], vals, yerr=[el, eh], width=bar_width, label=s, capsize=5)
        plotted_labels.append(s)

    # Axis & legend
    plt.xticks(centers, [f"{short_ge_name(exp.get_network_setting(lbl).get('ge'))}"
                         for name, lbl in zip(cat_order, cat_order_verbose)])
    if title is None:
        title = f"Goodput vs GE Loss Model — {data_size_str(data.data_sizes[0])}"
    plt.title(title)
    plt.ylabel("Goodput (Mbit/s)")
    plt.xlabel("GE scenarios (p=enter bad, r=exit bad, bad/good loss)")
    plt.grid(axis='y')
    plt.ylim(0)  # start at zero
    plot_title_and_legend(title, plotted_labels, base_height=1.20, row_height=0.07, title_height=0.08, ncol=3)

    if pdf:
        save_pdf(pdf)
    else:
        plt.show()

def plot_ge_vs_throughput_bars_faceted(raw_data, title=None, pdf=None, style=False):
    data = raw_data.to_plottable_data('throughput_mbps')
    exp = raw_data.exp
    net_labels = data.network_settings

    # Map GE string -> pretty name; fall back to short name if unknown
    ge_to_name = {sc["ge"]: sc["name"] for sc in GE_SCENARIOS}
    categories = []
    cat_verbose = []
    for nl in net_labels:
        ns_obj = exp.get_network_setting(nl)
        ge_str = ns_obj.get('ge')
        categories.append(ge_to_name.get(ge_str, short_ge_name(ge_str)))
        cat_verbose.append(nl)

    series_labels = TREATMENT_ORDER
    data_size = data.data_sizes[0]
    delta = 25  # IQR

    # Precompute stats per (category, series)
    med_abs = {c: {s: np.nan for s in series_labels} for c in categories}
    low_abs = {c: {s: 0.0 for s in series_labels} for c in categories}
    high_abs = {c: {s: 0.0 for s in series_labels} for c in categories}

    for ci, c in enumerate(categories):
        nl = cat_verbose[ci]
        for s in series_labels:
            label_key = TREATMENT_NAME_TO_LABEL[s]
            if nl not in data.data[label_key]:
                continue
            per_size = data.data[label_key][nl]
            if data_size not in per_size:
                continue
            stats = per_size[data_size]
            m = stats.p(50)
            l = m - stats.p(50 - delta)
            h = stats.p(50 + delta) - m
            med_abs[c][s] = m
            low_abs[c][s] = l
            high_abs[c][s] = h

    # Colors consistent across subplots
    cmap = plt.get_cmap("tab10")
    color_map = {s: cmap(i % 10) for i, s in enumerate(series_labels)}

    # Create one subplot per GE category
    n = len(categories)
    fig, axes = plt.subplots(1, n, figsize=(4.2 * n, 4.2), squeeze=False)
    axes = axes[0]

    handles = []
    for i, c in enumerate(categories):
        ax = axes[i]
        x = np.arange(len(series_labels))
        vals = [med_abs[c][s] for s in series_labels]
        el = [low_abs[c][s] for s in series_labels]
        eh = [high_abs[c][s] for s in series_labels]

        bars = []
        for xi, s in enumerate(series_labels):
            b = ax.bar(
                x[xi],
                vals[xi],
                yerr=[[el[xi]], [eh[xi]]],
                capsize=5,
                width=0.7,
                color=color_map[s],
                label=s,
            )
            if i == 0:
                handles.append(b[0])

        ax.set_title(c)
        ax.set_xticks(x)
        ax.set_xticklabels(series_labels, rotation=20, ha='right')
        ax.grid(axis='y')
        ax.set_ylim(bottom=0)
        if i == 0:
            ax.set_ylabel("Goodput (Mbit/s)")

    if title is None:
        title = f"Goodput vs GE Loss Model — {data_size_str(data.data_sizes[0])}"
    fig.suptitle(title, y=0.98)

    # Single legend across all subplots
    fig.legend(handles, series_labels, loc='upper center', ncol=min(3, len(series_labels)), bbox_to_anchor=(0.5, 1.12))

    fig.tight_layout(rect=[0, 0, 1, 0.98])
    if pdf:
        save_pdf(pdf)
    else:
        plt.show()


# Run the experiment for each GE setting
NUM_TRIALS = 5

loss_vs_throughput_data_ge = collect_loss_vs_metric_data(TREATMENTS(), NETWORK_SETTINGS_GE(), DATA_SIZE, n=NUM_TRIALS, execute=True)

# Plot using bar charts
plot_ge_vs_throughput_bars(loss_vs_throughput_data_ge, title="Packrat vs Tunnels vs End-to-End under GE", pdf=f"figures_ge/http_benchmark_ge_bars_{now_str}.pdf")
plot_ge_vs_throughput_bars_faceted(loss_vs_throughput_data_ge, title="Packrat vs Tunnels vs End-to-End under GE (per-scenario scales)", pdf=f"figures_ge/http_benchmark_ge_faceted_{now_str}.pdf")
