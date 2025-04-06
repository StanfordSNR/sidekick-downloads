from typing import Optional
from experiment import Treatment

DEFAULT_THRESHOLD = 20
IBLT_MULTIPLIER = 4
PROTOCOL = 'picoquic'

def nos(iblt: bool=False, hint: bool=False):
    options = ['--proxy', 'sidekick']
    options += ['--freq-ms', '25', '--freq-pkts', '8']
    if iblt:
        threshold = DEFAULT_THRESHOLD * IBLT_MULTIPLIER
        options += ['--threshold', str(threshold), '--riblt']
    else:
        options += ['--threshold', str(DEFAULT_THRESHOLD)]
    if hint:
        options += ['--quack-hint']
    return options

def pos(ack_delay: Optional[int]=None):
    options = ['--client-quacker']
    if ack_delay is not None:
        options += ['--ack-delay', str(ack_delay)]
    return options

def generate_treatments():
    treatments = [
        Treatment(PROTOCOL, label=f'picoquic', network_options=[], protocol_options=[]),
        Treatment(PROTOCOL, label=f'picoquic_split', network_options=['--proxy', 'picoquic'], protocol_options=[]),
        Treatment(PROTOCOL, label=f'picoquic_sidekick_0ms', network_options=nos(), protocol_options=pos(0)),
        Treatment(PROTOCOL, label=f'picoquic_sidekick_30ms', network_options=nos(), protocol_options=pos(30)),
        Treatment(PROTOCOL, label=f'picoquic_sidekick_60ms', network_options=nos(), protocol_options=pos(60)),
        Treatment(PROTOCOL, label=f'picoquic_sidekick_60ms_hint', network_options=nos(hint=True), protocol_options=pos(60)),
        Treatment(PROTOCOL, label=f'picoquic_iblt_0ms', network_options=nos(iblt=True), protocol_options=pos(0)),
        Treatment(PROTOCOL, label=f'picoquic_iblt_30ms', network_options=nos(iblt=True), protocol_options=pos(30)),
        Treatment(PROTOCOL, label=f'picoquic_iblt_60ms', network_options=nos(iblt=True), protocol_options=pos(60)),
        Treatment(PROTOCOL, label=f'picoquic_iblt_60ms_hint', network_options=nos(iblt=True, hint=True), protocol_options=pos(60)),
    ]
    labels = [treatment.label() for treatment in treatments]
    treatment_map = {}
    for label, treatment in zip(labels, treatments):
        treatment_map[label] = treatment
    return labels, treatment_map

labels, treatment_map = generate_treatments()
