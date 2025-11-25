import re
from typing import Optional
from experiment import Treatment, NetworkSetting

DEFAULT_FREQ_MS = 10
DEFAULT_FREQ_PKTS = 16
DEFAULT_THRESHOLD = lambda freq_pkts: freq_pkts * 5 // 2
IBLT_MULTIPLIER = 4
PROTOCOL = 'picoquic'
NETWORK_SETTING = NetworkSetting(bw1=50, bw2=20, delay1=2, delay2=30, loss1=4, loss2=0)

def nos(iblt: bool=False, hint: bool=False, cache_capacity: Optional[int]=None, reset: bool=False, freq_pkts: Optional[int]=None):
    options = ['--proxy', 'sidekick']
    if not freq_pkts:
        freq_pkts = DEFAULT_FREQ_PKTS
    threshold = DEFAULT_THRESHOLD(freq_pkts)
    options += ['--freq-pkts', str(freq_pkts), '--freq-ms', str(DEFAULT_FREQ_MS)]
    if iblt:
        options += ['--threshold', str(threshold * IBLT_MULTIPLIER), '--riblt']
    else:
        options += ['--threshold', str(threshold)]
    if hint:
        options += ['--quack-hint']
    if cache_capacity:
        options += ['--cache-capacity', str(cache_capacity)]
    if reset:
        options += ['--cache-policy', 'reset']
    return options

def pos(ack_delay: Optional[int]=None):
    options = ['--client-quacker']
    if ack_delay is not None:
        options += ['--ack-delay', str(ack_delay)]
    return options

def generate_treatment(ty: str, delay: int, hint: bool, freq_pkts: Optional[int]=None, cache_capacity: Optional[int]=None, reset: bool=False):
    label = f'picoquic_{ty}_{delay}ms'
    if hint:
        label += '_hint'
    if freq_pkts:
        label += f'_freq{freq_pkts}'
    if cache_capacity:
        label += f'_cache{cache_capacity}'
    if reset:
        label += f'_reset'
    network_options = nos(iblt=ty =='iblt', hint=hint, cache_capacity=cache_capacity, reset=reset, freq_pkts=freq_pkts)
    protocol_options = pos(delay)
    treatment = Treatment(PROTOCOL, label=label,
        network_options=network_options, protocol_options=protocol_options)
    return treatment

def generate_rtunnel_treatment(max_num_retx: int, ordered: Optional[int]=None, delay: Optional[int]=None):
    label = f'picoquic_rtunnel_retx{max_num_retx}'
    network_options = ['--proxy', 'rtunnel', '--max-num-retx', str(max_num_retx)]
    protocol_options = []
    if ordered:
        label += f'_ordered{ordered}'
        network_options += ['--ordered', str(ordered)]
    if delay:
        label += f'_{delay}ms'
        protocol_options += ['--ack-delay', str(delay)]
    treatment = Treatment(PROTOCOL, label=label,
        network_options=network_options, protocol_options=protocol_options)
    return treatment

def generate_treatments():
    treatments = [
        Treatment(PROTOCOL, label=f'picoquic', network_options=[], protocol_options=[]),
        Treatment(PROTOCOL, label=f'picoquic_30ms', network_options=[], protocol_options=pos(30)),
        Treatment(PROTOCOL, label=f'picoquic_split', network_options=['--proxy', 'picoquic'], protocol_options=[]),
    ]
    labels = [treatment.label() for treatment in treatments]
    treatment_map = {}
    for label, treatment in zip(labels, treatments):
        treatment_map[label] = treatment
    return labels, treatment_map

labels, _treatment_map = generate_treatments()

def treatment_map(label, treatments=_treatment_map):
    if label in treatments:
        return treatments[label]

    # Generate an rtunnel treatment on the fly
    pattern = re.compile(
        r'^picoquic_rtunnel_retx(?P<max_num_retx>\d+)'
        r'(?:_ordered(?P<ordered>\d+))?'
        r'(?:_(?P<delay>\d+)ms)?'
    )
    match = pattern.fullmatch(label)
    if match:
        match = match.groupdict()
        return generate_rtunnel_treatment(match['max_num_retx'], match['ordered'], match['delay'])

    # Generate a different treatment on the fly
    pattern = re.compile(
        r'^picoquic_'
        r'(?P<ty>(iblt|sidekick))_'
        r'(?P<delay>\d+)ms'
        r'(?:_hint)?'
        r'(?:_freq(?P<freq_pkts>\d+))?'
        r'(?:_cache(?P<cache_capacity>\d+))?'
        r'(?:_reset)?$'
    )
    match = pattern.fullmatch(label)
    if match:
        match = match.groupdict()
        return generate_treatment(
            match['ty'], match['delay'], 'hint' in label,
            freq_pkts=match['freq_pkts'],
            cache_capacity=match['cache_capacity'], reset='reset' in label
        )
    raise Exception(label)
