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

