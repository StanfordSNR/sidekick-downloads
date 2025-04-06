"""
Define the data needed for an experiment.
"""
from typing import List, Optional, Dict


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


class Experiment:
    def __init__(self,
                 treatments: List[Treatment],
                 network_settings: List[NetworkSetting]):
        self.treatments = [x.label() for x in treatments]
        self.network_settings = [x.label() for x in network_settings]
        self._treatments = { x.label(): x for x in treatments }
        self._network_settings = { x.label(): x for x in network_settings }

    def get_treatment(self, label: str) -> Treatment:
        return self._treatments[label]

    def get_network_setting(self, label: str) -> NetworkSetting:
        return self._network_settings[label]

    def get_treatments(self) -> List[Treatment]:
        return [self._treatments[label] for label in self.treatments]

    def get_network_settings(self) -> List[NetworkSetting]:
        return [self._network_settings[label] for label in self.network_settings]
