from typing import Optional
from experiment import Treatment

DEFAULT_FREQ_MS = 10
DEFAULT_FREQ_PKTS = 16
DEFAULT_THRESHOLD = lambda freq_pkts: freq_pkts * 5 // 2
IBLT_MULTIPLIER = 4
PROTOCOL = 'picoquic'

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

def generate_rtunnel_treatment(max_num_retx: int, delay: Optional[int]=None):
    label = f'picoquic_rtunnel_retx{max_num_retx}'
    network_options = ['--proxy', 'rtunnel', '--max-num-retx', str(max_num_retx)]
    protocol_options = []
    if delay:
        label += f'_delay{delay}'
        protocol_options += ['--ack-delay', str(delay)]
    treatment = Treatment(PROTOCOL, label=label,
        network_options=network_options, protocol_options=protocol_options)
    return treatment

def generate_treatments():
    treatments = [
        Treatment(PROTOCOL, label=f'picoquic', network_options=[], protocol_options=[]),
        Treatment(PROTOCOL, label=f'picoquic_30ms', network_options=[], protocol_options=pos(30)),
        Treatment(PROTOCOL, label=f'picoquic_split', network_options=['--proxy', 'picoquic'], protocol_options=[]),
        generate_rtunnel_treatment(0),
        generate_rtunnel_treatment(1),
        generate_rtunnel_treatment(7),
        generate_rtunnel_treatment(0, 30),
        generate_rtunnel_treatment(1, 30),
        generate_rtunnel_treatment(7, 30),
        generate_treatment('iblt', 30, True, reset=True),
        generate_treatment('iblt', 30, True, cache_capacity=48000, reset=True),
        generate_treatment('iblt', 30, True, cache_capacity=16000, reset=True),
        generate_treatment('iblt', 30, True, cache_capacity=48000),
        generate_treatment('iblt', 30, True, cache_capacity=16000),
    ]
    for ty in ['sidekick', 'iblt']:
        for delay in [0, 5, 10, 20, 30, 60]:
            for freq in [None, 8, 10, 16, 32]:
                treatments.append(generate_treatment(ty, delay, False, freq_pkts=freq))
                treatments.append(generate_treatment(ty, delay, True, freq_pkts=freq))
    labels = [treatment.label() for treatment in treatments]
    treatment_map = {}
    for label, treatment in zip(labels, treatments):
        treatment_map[label] = treatment
    return labels, treatment_map

labels, treatment_map = generate_treatments()
