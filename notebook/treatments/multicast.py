from typing import Optional
from experiment import Treatment, NetworkSetting

DEFAULT_THRESHOLD = 8
IBLT_MULTIPLIER = 4
DEFAULT_FREQ_PKTS = 2
PROTOCOL = 'multicast'
NETWORK_SETTING = NetworkSetting(bw1=20, bw2=50, delay1=30, delay2=10, loss1=0, loss2=10)

def nos(iblt: bool=False, quack_hint: bool=False, quack_nack: bool=False, cache_capacity: Optional[int]=None):
    options = ['--proxy', 'sidekick-multicast', '--freq-ms', '0']
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
    options = []
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

def generate_treatments():
    # Baseline and cache policy treatments
    treatments = [
        Treatment(PROTOCOL, label='baseline', network_options=[], protocol_options=[]),
        generate_treatment('psum', 45, True, True, 10000),
        generate_treatment('iblt', 45, True, True, 10000),
        generate_treatment('iblt', 45, True, True, 2000),
    ]
    # Various delays, hint, nack
    for ty in ['psum', 'iblt']:
        for delay in [0, 5, 10, 15, 30, 45, 90]:
            treatments.append(generate_treatment(ty, delay, False, False))
            treatments.append(generate_treatment(ty, delay, True, False))
            treatments.append(generate_treatment(ty, delay, False, True))
            treatments.append(generate_treatment(ty, delay, True, True))
    labels = [treatment.label() for treatment in treatments]
    treatment_map = {}
    for label, treatment in zip(labels, treatments):
        treatment_map[label] = treatment
    return labels, treatment_map

labels, treatment_map = generate_treatments()
