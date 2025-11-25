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
    return f"P{p}/R{r}\nBad{bad}%|Good{good}%"


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

def TREATMENTS():
    return [treatment_map(TREATMENT_NAME_TO_LABEL[name]) for name in TREATMENT_ORDER]


LOSS1_VALUES = [0, 4, 8, 12, 16, 20, 24]

GE_SCENARIOS = [
    {"name": "p=0%,r=100%,b_loss=0%,g_loss=0%", "ge": "0,100,0,0"},
    {"name": "p=0%,r=100%,b_loss=4%,g_loss=4%", "ge": "0,100,4,4"},
    {"name": "p=0%,r=100%,b_loss=8%,g_loss=8%", "ge": "0,100,8,8"},
    {"name": "p=0%,r=100%,b_loss=12%,g_loss=12%", "ge": "0,100,12,12"},
    {"name": "p=0%,r=100%,b_loss=16%,g_loss=16%", "ge": "0,100,16,16"},
    {"name": "p=0%,r=100%,b_loss=20%,g_loss=20%", "ge": "0,100,20,20"},
]

def NETWORK_SETTINGS_GE(
    scenarios=GE_SCENARIOS,
    bw1=ns.get('bw1'), bw2=ns.get('bw2'),
    delay1=ns.get('delay1'), delay2=ns.get('delay2')
):
    # We pass ge=..., and neutralize IID fields (loss1/loss2 not used when ge is set)
    nets = []
    for sc in scenarios:
        nets.append(
            NetworkSetting(
                bw1=bw1, bw2=bw2,
                delay1=delay1, delay2=delay2,
                loss2='0',
                ge=sc["ge"],
                qdisc=ns.get('qdisc'),
                jitter1=ns.get('jitter1'),
                jitter2=ns.get('jitter2'),
            )
        )
    return nets

def NETWORK_SETTINGS_IID(
    loss1_values=LOSS1_VALUES,
    bw1=ns.get('bw1'), bw2=ns.get('bw2'),
    delay1=ns.get('delay1'), delay2=ns.get('delay2')
):
    nets = []
    for loss1 in loss1_values:
        nets.append(
            NetworkSetting(
                bw1=bw1, bw2=bw2,
                delay1=delay1, delay2=delay2,
                loss1=str(loss1), loss2='0',
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
            # For GE scenarios, extract bad_loss from ge parameter; otherwise use loss1
            ge_value = network_setting.settings.get('ge')
            if ge_value is not None:
                # Parse ge string "p,r,bad_loss,good_loss" and use bad_loss as x-axis
                ge_params = [p.strip() for p in ge_value.split(',')]
                if len(ge_params) >= 3:
                    xs.append(float(ge_params[3]))  # bad_loss is the 3rd parameter
                else:
                    xs.append(0.0)
            else:
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

def plot_loss_vs_throughput(raw_data, title=None, ncol=2, pdf=None, style=False):
    plottable_data = raw_data.to_plottable_data('throughput_mbps')
    if not title:
        title = f'{data_size_str(plottable_data.data_sizes[0])} ({plottable_data.network_settings[0]})'
    ylabel = 'Goodput (Mbit/s)'
    plot_loss_vs_metric_line(plottable_data, title, ncol=ncol, ylabel=ylabel, pdf=pdf, style=style)


# Run the experiment for each GE setting, and each IID setting

NUM_TRIALS = 3

# loss_vs_throughput_data_iid = collect_loss_vs_metric_data(TREATMENTS(), NETWORK_SETTINGS_IID(), DATA_SIZE, n=NUM_TRIALS, execute=True)
loss_vs_throughput_data_ge = collect_loss_vs_metric_data(TREATMENTS(), NETWORK_SETTINGS_GE(), DATA_SIZE, n=NUM_TRIALS, execute=True)


# plot_loss_vs_throughput(loss_vs_throughput_data_iid, ncol=3, style=True, pdf=f"figures/http_benchmark_iid_{now_str}.pdf")
plot_loss_vs_throughput(loss_vs_throughput_data_ge, ncol=3, style=True, pdf=f"figures/http_benchmark_ge_{now_str}.pdf")

# loss_vs_throughput_ge = collect_loss_vs_metric_data(TREATMENTS(), NETWORK_SETTINGS_GE(), DATA_SIZE//10, n=1, execute=True)
# plot_loss_vs_throughput(loss_vs_throughput_ge, ncol=3, style=True, pdf="figures/http_benchmark_ge_1.pdf")