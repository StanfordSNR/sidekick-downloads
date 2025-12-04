import re
from typing import Optional
from experiment import Treatment, NetworkSetting

DEFAULT_THRESHOLD = 10
IBLT_MULTIPLIER = 4
DEFAULT_FREQ_PKTS = 2
PROTOCOL = 'media'
# Default network setting (note: use `network_setting.py` instead)
NETWORK_SETTING = NetworkSetting(bw1=50, bw2=20, delay1=50, delay2=100, loss1=10, loss2=0)

def nos(iblt: bool=False, quack_hint: bool=False, quack_nack: bool=False, cache_capacity: Optional[int]=None):
    options = ['--proxy', 'sidekick', '--freq-ms', '0']
    if iblt:
        threshold = DEFAULT_THRESHOLD * IBLT_MULTIPLIER
        options += ['--threshold', str(threshold), '--riblt']
    else:
        options += ['--threshold', str(DEFAULT_THRESHOLD)]
    if quack_hint:
        options += ['--quack-hint']
    if quack_nack:
        options += ['--quack-nack', '--freq-pkts', '0']
    else:
        options += ['--freq-pkts', str(DEFAULT_FREQ_PKTS)]
    if cache_capacity:
        options += ['--cache-capacity', str(cache_capacity)]
    return options

def pos(ack_delay: Optional[int]=None):
    options = ['--client-quacker']
    if ack_delay is not None:
        options += ['--ack-delay', str(ack_delay)]
    return options

def generate_treatment(ty: str, delay: int, hint: bool, nack: bool, cache_capacity: Optional[int]=None):
    label = f'{ty}_delay{delay}'
    if hint:
        label += '_hint'
    if nack:
        label += '_nack'
    if cache_capacity:
        label += f'_cache{cache_capacity}'
    network_options = nos(iblt=ty =='iblt', quack_hint=hint, quack_nack=nack, cache_capacity=cache_capacity)
    protocol_options = pos(delay)
    treatment = Treatment(PROTOCOL, label=label,
        network_options=network_options, protocol_options=protocol_options)
    return treatment

def generate_rtunnel_treatment(max_num_retx: int, ordered: Optional[int]=None, delay: Optional[int]=None):
    label = f'baseline_rtunnel_retx{max_num_retx}'
    network_options = ['--proxy', 'rtunnel', '--max-num-retx', str(max_num_retx)]
    protocol_options = []
    if ordered:
        label += f'_ordered{ordered}'
        network_options += ['--ordered', str(ordered)]
    if delay:
        label += f'_delay{delay}'
        protocol_options += ['--ack-delay', str(delay)]
    treatment = Treatment(PROTOCOL, label=label,
        network_options=network_options, protocol_options=protocol_options)
    return treatment

def generate_treatments():
    # Baseline and cache policy treatments
    treatments = [
        Treatment(PROTOCOL, label='baseline', network_options=[], protocol_options=[]),
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
        r'^baseline_rtunnel_retx(?P<max_num_retx>\d+)'
        r'(?:_ordered(?P<ordered>\d+))?'
        r'(?:_delay(?P<delay>\d+))?'
    )
    match = pattern.fullmatch(label)
    if match:
        match = match.groupdict()
        return generate_rtunnel_treatment(match['max_num_retx'], match['ordered'], match['delay'])

    # Generate a different treatment on the fly
    pattern = re.compile(
        r'^(?P<ty>(iblt|psum))_'
        r'delay(?P<delay>\d+)'
        r'(?:_hint)?'
        r'(?:_nack)?'
        r'(?:_cache(?P<cache_capacity>\d+))?'
    )
    match = pattern.fullmatch(label)
    if match:
        match = match.groupdict()
        return generate_treatment(
            match['ty'], match['delay'], 'hint' in label, 'nack' in label,
            cache_capacity=match['cache_capacity'],
        )
    raise Exception(label)
