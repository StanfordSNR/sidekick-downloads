import os
import math

import numpy as np
import matplotlib.pyplot as plt

SIDEKICK_HOME = f'{os.environ["HOME"]}/sidekick-downloads'
DATA_HOME = f'{SIDEKICK_HOME}/data'

plt_label = {
    'tcp_cubic': 'TCP CUBIC',
    'tcp_bbr1': 'TCP BBRv1',
    'tcp_bbr2': 'TCP BBRv2',
    'tcp_bbr3': 'TCP BBRv3',
    'tcp_reno': 'TCP Reno',
    'quic_cubic': 'Chromium QUIC CUBIC',
    'quic_bbr1': 'Chromium QUIC BBRv1',
    'quic_bbr3': 'Chromium QUIC BBRv3',
    'quic_reno': 'Chromium QUIC Reno',
    'quiche_cubic': 'Cloudflare QUIC CUBIC',
    'quiche_bbr1': 'Cloudflare QUIC BBRv1',
    'quiche_bbr2': 'Cloudflare QUIC BBRv2',
    'quiche_reno': 'Cloudflare QUIC Reno',
    'picoquic_cubic': 'Picoquic QUIC CUBIC',
    'picoquic_bbr1': 'Picoquic QUIC BBRv1',
    'picoquic_bbr3': 'Picoquic QUIC BBRv3',
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
