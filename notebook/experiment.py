"""
Define the data needed for an experiment.
"""
from typing import List, Optional


class Treatment:
    def __init__(
        self, protocol: str, label: str,
        network_options: List[str]=[],
        protocol_options: List[str]=[],
    ):
        self.protocol = protocol
        self._label = label
        self._network_options = network_options
        self._protocol_options = protocol_options

    def label(self) -> str:
        return self._label

    @property
    def network_options(self) -> List[str]:
        return self._network_options

    @property
    def protocol_options(self) -> List[str]:
        return self._protocol_options


class TCPTreatment(Treatment):
    def __init__(self, label: str, cca: str='cubic', pep: bool=False):
        protocol_options = ['-cca', cca]
        if pep:
            protocol_options.append('--pep')
        super().__init__(
            protocol='tcp', label=label, protocol_options=protocol_options)


class QUICTreatment(Treatment):
    def __init__(self, label: str, cca: str='cubic'):
        super().__init__(
            protocol='quic', label=label,
            protocol_options=['-cca', cca],
        )


class CloudflareQUICTreatment(Treatment):
    def __init__(self, label: str, cca: str='cubic'):
        super().__init__(
            protocol='quiche', label=label,
            protocol_options=['-cca', cca],
        )


class PicoQUICTreatment(Treatment):
    def __init__(self, label: str, cca: str='cubic'):
        super().__init__(
            protocol='picoquic', label=label,
            protocol_options=['-cca', cca],
        )


class TCPIperf3Treatment(Treatment):
    def __init__(self, label: str, cca: str='cubic', pep: bool=False):
        protocol_options = ['-cca', cca]
        if pep:
            protocol_options.append('--pep')
        super().__init__(
            protocol='iperf3', label=label, protocol_options=protocol_options)


class NetworkSetting:
    DEFAULTS = {
        'delay1': 1,
        'delay2': 25,
        'loss1': '1',
        'loss2': '0',
        'bw1': 100,
        'bw2': 10,
        'jitter1': None,
        'jitter2': None,
        'qdisc': None,
    }

    def __init__(self, delay1: Optional[int]=None, delay2: Optional[int]=None,
                 loss1: Optional[str]=None, loss2: Optional[str]=None,
                 bw1: Optional[int]=None, bw2: Optional[int]=None,
                 qdisc: Optional[str]=None,
                 jitter1: Optional[int]=None, jitter2: Optional[int]=None):
        """
        Labels is a list of setting names that are different from default.
        """
        self.settings = {
            'delay1': delay1,
            'delay2': delay2,
            'loss1': loss1,
            'loss2': loss2,
            'bw1': bw1,
            'bw2': bw2,
            'jitter1': jitter1,
            'jitter2': jitter2,
        }
        if qdisc is not None:
            self.settings['qdisc'] = qdisc
        self.labels = []
        for key, value in sorted(self.settings.items()):
            if value == NetworkSetting.DEFAULTS[key]:
                pass
            elif value is None:
                self.settings[key] = NetworkSetting.DEFAULTS[key]
            else:
                self.labels.append(key)
        self.labels.sort()

    def set(self, key: str, value):
        self.settings[key] = value
        if key not in self.labels:
            self.labels.append(key)
            self.labels.sort()

    def get(self, key):
        return self.settings.get(key)

    def mirror(self):
        return NetworkSetting(
            delay1=self.settings['delay2'],
            delay2=self.settings['delay1'],
            loss1=self.settings['loss2'],
            loss2=self.settings['loss1'],
            bw1=self.settings['bw2'],
            bw2=self.settings['bw1'],
            qdisc=self.settings.get('qdisc'),
            jitter1=self.settings['jitter2'],
            jitter2=self.settings['jitter1'],
        )

    def clone(self):
        network = NetworkSetting()
        for key, value in self.settings.items():
            network.settings[key] = value
        network.labels = list(self.labels)
        return network

    def label(self) -> str:
        value = 'network_'
        keys = list(sorted(self.settings.keys()))
        value += '_'.join([str(self.settings[key]) for key in keys])
        return value


class DirectNetworkSetting(NetworkSetting):
    def __init__(self, delay: Optional[int]=None, loss: Optional[str]=None,
                 bw: Optional[int]=None, qdisc: Optional[str]=None,
                 jitter: Optional[int]=None):
        super().__init__(delay1=delay, loss1=loss, bw1=bw, qdisc=qdisc,
                         jitter1=jitter)
        for key in ['delay2', 'loss2', 'bw2', 'jitter2']:
            del self.settings[key]
        self.settings['topology'] = 'direct'
        self.labels.append('topology')
        self.labels.sort()

    def mirror(self):
        raise NotImplementedError('cannot mirror a direct network')


class Experiment:
    def __init__(self,
                 num_trials: int,
                 treatments: List[Treatment],
                 network_settings: List[NetworkSetting],
                 data_sizes: List[int],
                 timeout: Optional[int]=None,
                 network_losses: List[str]=[],
                 network_delays: List[int]=[],
                 network_bws: List[int]=[],
                 cartesian: bool=True):
        """Parameters:
        - network_settings: List of network settings to test in the experiment.
          Typically used if varying data size as the test parameter. If empty,
          uses `network_losses`, `network_delays`, and `network_bws` to generate
          the space of (direct) network settings to test and uses data sizes
          that are 10x the bottleneck bandwidth for the network setting.
        - data_sizes: List of data sizes to test in the experiment. Ignored if
          `network_settings` is an empty list.
        - network_losses: Used if `network_settings` is an empty list to
          generate the space of (direct) network settings to test. Sorted order.
        - network_delays: Used if `network_settings` is an empty list to
          generate the space of (direct) network settings to test. Sorted order.
        - network_bws: Used if `network_settings` is an empty list to
          generate the space of (direct) network settings to test. Sorted order.
        - cartesian: If True, takes the Cartesian product of network settings
          and data sizes in the experiment. If False, zips the network settings
          and data sizes one-to-one.
        """
        self.num_trials = num_trials
        self.treatments = [x.label() for x in treatments]

        if len(network_settings) > 0:
            self._network_settings = { x.label(): x for x in network_settings }
            self.network_settings = [x.label() for x in network_settings]
            self.data_sizes = data_sizes
            self.network_losses = []
            self.network_delays = []
            self.network_bws = []
        else:
            self._network_settings = {}
            self.network_settings = []
            self.data_sizes = []
            self.network_losses = network_losses
            self.network_delays = network_delays
            self.network_bws = network_bws
            data_size = lambda bw: int(10*1000000*bw/8)  # 10x the bottleneck bandwidth
            for loss in network_losses:
                for delay in network_delays:
                    for bw in network_bws:
                        ns = DirectNetworkSetting(loss=loss, delay=delay, bw=bw)
                        ns_label = ns.label()
                        self._network_settings[ns_label] = ns
                        self.network_settings.append(ns_label)
                        self.data_sizes.append(data_size(bw))

        self._treatments = { x.label(): x for x in treatments }
        self.timeout = timeout
        self.cartesian = cartesian

    def get_treatment(self, label: str) -> Treatment:
        return self._treatments[label]

    def get_network_setting(self, label: str) -> NetworkSetting:
        return self._network_settings[label]

    def get_treatments(self) -> List[Treatment]:
        return [self._treatments[label] for label in self.treatments]

    def get_network_settings(self) -> List[NetworkSetting]:
        return [self._network_settings[label] for label in self.network_settings]
