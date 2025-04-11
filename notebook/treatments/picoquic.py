from typing import Optional
from experiment import Treatment

DEFAULT_THRESHOLD = 20
IBLT_MULTIPLIER = 4
PROTOCOL = 'picoquic'

def nos(iblt: bool=False, hint: bool=False, cache_capacity: Optional[int]=None):
    options = ['--proxy', 'sidekick']
    options += ['--freq-ms', '25', '--freq-pkts', '8']
    if iblt:
        threshold = DEFAULT_THRESHOLD * IBLT_MULTIPLIER
        options += ['--threshold', str(threshold), '--riblt']
    else:
        options += ['--threshold', str(DEFAULT_THRESHOLD)]
    if hint:
        options += ['--quack-hint']
    if cache_capacity:
        options += ['--cache-capacity', str(cache_capacity)]
    return options

def pos(ack_delay: Optional[int]=None):
    options = ['--client-quacker']
    if ack_delay is not None:
        options += ['--ack-delay', str(ack_delay)]
    return options

def generate_treatment(ty: str, delay: int, hint: bool, cache_capacity: Optional[int]=None):
    label = f'picoquic_{ty}_{delay}ms'
    if hint:
        label += '_hint'
    if cache_capacity:
        label += f'_cache{cache_capacity}'
    network_options = nos(iblt=ty =='iblt', hint=hint, cache_capacity=cache_capacity)
    protocol_options = pos(delay)
    treatment = Treatment(PROTOCOL, label=label,
        network_options=network_options, protocol_options=protocol_options)
    return treatment


def generate_treatments():
    treatments = [
        Treatment(PROTOCOL, label=f'picoquic', network_options=[], protocol_options=[]),
        Treatment(PROTOCOL, label=f'picoquic_30ms', network_options=[], protocol_options=pos(30)),
        Treatment(PROTOCOL, label=f'picoquic_split', network_options=['--proxy', 'picoquic'], protocol_options=[]),
    ]
    for ty in ['sidekick', 'iblt']:
        for delay in [0, 10, 20, 30, 60]:
            treatments.append(generate_treatment(ty, delay, False))
            treatments.append(generate_treatment(ty, delay, True))
    labels = [treatment.label() for treatment in treatments]
    treatment_map = {}
    for label, treatment in zip(labels, treatments):
        treatment_map[label] = treatment
    return labels, treatment_map

labels, treatment_map = generate_treatments()
