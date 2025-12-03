import os
import math

import numpy as np
import matplotlib.pyplot as plt
from dataclasses import dataclass

SIDEKICK_HOME = f'{os.environ["HOME"]}/sidekick-downloads'
DATA_HOME = f'{SIDEKICK_HOME}/data'

@dataclass(frozen=True)
class PlotStyle:
    color: str
    linestyle: str
    marker: str = '.'
    markersize: int = None

colors = [
    "#AEC6CF",  # pastel blue
    "#FFB347",  # pastel orange
    "#77DD77",  # pastel green
    "#FF6961",  # pastel red
    "#CBAACB",  # pastel purple
    "#FDFD96",  # pastel yellow
    "#B39EB5",  # dusty lavender
    "#D3D3D3",  # light gray
]
linestyles = ['-', '--', '-.', ':', '-']

LABEL_MAP = {
    # HTTP
    'picoquic': 'End-to-End',
    'picoquic_split': 'Split Connection',
    'picoquic_iblt_0ms_hint': 'Packrat (no delay)',
    'picoquic_iblt_30ms': 'Packrat (no rateless)',
    'picoquic_iblt_30ms_hint': 'Packrat',
    'picoquic_iblt_50ms_hint': 'Packrat',
    'picoquic_iblt_110ms_hint': 'Packrat',
    'picoquic_iblt_30ms_hint_cache48000': 'Packrat',
    'picoquic_rtunnel_retx7': 'Tunnel (Unordered)',
    'picoquic_rtunnel_retx7_ordered32': 'Tunnel (Ordered)',
    # Media
    'baseline': 'End-to-End',
    'baseline_rtunnel_retx7': 'Tunnel (Unordered)',
    'baseline_rtunnel_retx7_ordered32': 'Tunnel (Ordered)',
    'iblt_delay0_hint_nack_cache4000': 'Packrat (no delay)',
    'iblt_delay110': 'Packrat (no nack+rateless)',
    'iblt_delay110_hint': 'Packrat (no nack)',
    'iblt_delay110_hint_nack': 'Packrat',
    'iblt_delay110_hint_nack_cache4000': 'Packrat',
    # Multicast
    'iblt_delay30_hint_nack': 'Packrat',
}
STYLE = {
    'End-to-End': PlotStyle(colors[0], linestyles[0]),
    'Packrat': PlotStyle(colors[1], linestyles[1], '*', markersize=10),
    'Split Connection': PlotStyle(colors[2], linestyles[2]),
    'Tunnel (Ordered)': PlotStyle(colors[3], linestyles[3]),
    'Tunnel (Unordered)': PlotStyle(colors[4], linestyles[4]),
    'Packrat (no delay)': PlotStyle(colors[5], linestyles[0]),
    'Packrat (no nack)': PlotStyle(colors[6], linestyles[0]),
    'Packrat (no nack+rateless)': PlotStyle(colors[7], linestyles[0]),
    'Packrat (no rateless)': PlotStyle(colors[7], linestyles[0]),
}

def get_data_size(bottleneck_bw):
    return int(10*1000000*bottleneck_bw/8)  # 10s at the bottleneck bandwidth

def data_size_str(data_size):
    if data_size < 1e3:
        return f'{data_size}B'
    elif data_size < 1e6:
        return f'{int(data_size/1e3)}K'
    elif data_size < 1e9:
        return f'{int(data_size/1e6)}M'
    elif data_size < 1e12:
        return f'{int(data_size/1e6)}G'

def plot_title_and_legend(title, labels, ncol=3, base_height=1.15,
                          row_height=0.1, title_height=0.12):
    legend_height = base_height
    legend_height += row_height * (math.ceil(len(labels) / ncol) - 1)
    if title:
        plt.title(title)
        legend_height += title_height
    plt.legend(loc='upper center', bbox_to_anchor=(0.5, legend_height), ncol=ncol)

def save_pdf(output_filename, bbox_inches='tight'):
    from matplotlib.backends.backend_pdf import PdfPages
    if output_filename is not None:
        with PdfPages(output_filename) as pdf:
            pdf.savefig(bbox_inches=bbox_inches)
    print(output_filename)
