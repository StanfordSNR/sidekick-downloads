from experiment import NetworkSetting

NETWORK_SETTING_WIFI = NetworkSetting(bw1=50, bw2=20, delay1=2, delay2=30, loss1=4, loss2=0)
NETWORK_SETTING_SAT = NetworkSetting(bw1=50, bw2=20, delay1=50, delay2=50, loss1=10, loss2=0)
NETWORK_SETTING_CELLULAR = NetworkSetting(bw1=20, bw2=50, delay1=30, delay2=10, loss1=10, loss2=0)
NS_LABELS = {"wifi": NETWORK_SETTING_WIFI, "sat": NETWORK_SETTING_SAT, "cellular": NETWORK_SETTING_CELLULAR}

ACK_DELAY_WIFI = 20
ACK_DELAY_SAT = 110
ACK_DELAY_CELL = 40

# TODO fix this later - args are flipped for the multicast case
NETWORK_SETTING_WIFI_MCAST = NetworkSetting(bw2=50, bw1=20, delay2=2, delay1=30, loss2=4, loss1=0)
NETWORK_SETTING_SAT_MCAST = NetworkSetting(bw2=50, bw1=20, delay2=50, delay1=100, loss2=10, loss1=0)
NETWORK_SETTING_CELLULAR_MCAST = NetworkSetting(bw2=20, bw1=50, delay2=30, delay1=10, loss2=10, loss1=0)

# Unicast network settings
def network_settings(loss_list):
    settings = {}
    for (label, ns) in NS_LABELS.items():
        settings[label] = []
        for loss in loss_list:
            settings[label].append(
                NetworkSetting(bw1=ns.get('bw1'), bw2=ns.get('bw2'), delay1=ns.get('delay1'),
                    delay2=ns.get('delay2'), loss1=loss, loss2=0))
    return settings

# Gilbert-Elliott Setup

import numpy as np
# overall_loss_pct will fix stationary/long-running
# probabilities for `good` and `bad` states
# define `p` and `r` as (scaling_factor * desired_stationary_probability)
# larger scaling factor = shorter bursts; smaller scaling factor = longer bursts
scale_by = np.linspace(0.95, 0.01, 10)
# Fix good and bad state quality
loss_good_pct = 2
loss_bad_pct = 80
loss_good = loss_good_pct / 100.0
loss_bad = loss_bad_pct / 100.0

# ge=p,r,loss_bad,loss_good
# overall loss should be passed in as a %
def ge_configs(overall_loss_pct):
    overall_loss = overall_loss_pct / 100.0
    settings = []

    # stationary probabilities per state
    # overall_loss = p_good * loss_good + p_bad * loss_bad
    p_bad = (overall_loss - loss_good) / (loss_bad - loss_good)
    p_good = 1 - p_bad

    # IID loss
    settings.append(f"1,0,{overall_loss_pct},{overall_loss_pct}")
    for scale in scale_by:
        # transition probabilities
        p_pct = round(p_bad * scale * 100, 2)
        r_pct = round(p_good * scale * 100, 2)
        settings.append(f"{p_pct},{r_pct},{loss_bad},{loss_good}")

    return settings

def network_settings_ge(loss):
    settings = {}
    for (label, ns) in NS_LABELS.items():
        settings[label] = []
        ge = ge_configs(loss)
        for ge_ in ge:
            settings[label].append(
                NetworkSetting(bw1=ns.get('bw1'), bw2=ns.get('bw2'), delay1=ns.get('delay1'),
                    delay2=ns.get('delay2'), ge=ge_))
    return settings

def ge_to_burst_size(ge_str):
    parts = ge_str.split(',')
    p = float(parts[0]) / 100.0
    r = float(parts[1]) / 100.0
    if p == 1.0:
        return 1.0  # IID loss
    avg_bad_length = 1.0 / r
    return (1.0 / r) * 100