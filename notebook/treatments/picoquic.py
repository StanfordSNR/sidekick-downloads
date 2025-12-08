import re
from typing import Optional
from experiment import Treatment, NetworkSetting
from treatments.network_settings import *

DEFAULT_FREQ_MS = 2
DEFAULT_FREQ_PKTS = 16
E2E_ACK_DELAYS = [ACK_DELAY_WIFI, ACK_DELAY_SAT, ACK_DELAY_CELL]
DEFAULT_THRESHOLD = lambda freq_pkts: freq_pkts * 5 // 2
IBLT_MULTIPLIER = 4
PROTOCOL = 'picoquic'
# Default network setting (note: use `network_setting.py` instead)
NETWORK_SETTING = NetworkSetting(bw1=50, bw2=20, delay1=2, delay2=30, loss1=4, loss2=0)

'''
Configure Packrat proxy options.
TODO rename `sidekick` to `packrat`
'''
def nos(iblt: bool=False,
        hint: bool=False,
        cache_capacity: Optional[int]=None,
        reset: bool=False,
        freq_pkts: Optional[int]=None,
        freq_ms: Optional[int]=None):
    options = ['--proxy', 'sidekick']
    if not freq_pkts:
        freq_pkts = DEFAULT_FREQ_PKTS
    if not freq_ms:
        freq_ms = DEFAULT_FREQ_MS
    threshold = DEFAULT_THRESHOLD(freq_pkts)
    options += ['--freq-pkts', str(freq_pkts), '--freq-ms', str(freq_ms)]
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

'''
Configure picoquic protocol options.
'''
def pos(ack_delay: Optional[int]=None, cca: Optional[str]=None, quacking: Optional[bool]=True):
    options = []
    if quacking:
        options += ['--client-quacker']
    if ack_delay is not None:
        options += ['--ack-delay', str(ack_delay)]
    if cca is not None:
        options += ['--congestion-control', cca]
    return options

'''
Generate a treatment with a label and options.
'''
def generate_treatment(ty: str,
    delay: int,
    hint: bool,
    freq_pkts: Optional[int]=None,
    cache_capacity: Optional[int]=None,
    reset: bool=False,
    cca: Optional[str]=None):
    label = f'picoquic_{ty}_{delay}ms'
    if hint:
        label += '_hint'
    if freq_pkts:
        label += f'_freq{freq_pkts}'
    if cache_capacity:
        label += f'_cache{cache_capacity}'
    if reset:
        label += f'_reset'
    if cca:
        label +=f'_{cca}'
    network_options = nos(iblt=ty =='iblt', hint=hint, cache_capacity=cache_capacity, reset=reset, freq_pkts=freq_pkts)
    protocol_options = pos(ack_delay=delay, cca=cca)
    treatment = Treatment(PROTOCOL, label=label,
        network_options=network_options, protocol_options=protocol_options)
    return treatment

'''
Special config function for the reliable tunnel (ordered or unordered)
'''
def generate_rtunnel_treatment(max_num_retx: int, ordered: Optional[int]=None, delay: Optional[int]=None, cca: Optional[str]=None):
    label = f'picoquic_rtunnel_retx{max_num_retx}'
    network_options = ['--proxy', 'rtunnel', '--max-num-retx', str(max_num_retx)]
    protocol_options = []
    if ordered:
        label += f'_ordered{ordered}'
        network_options += ['--ordered', str(ordered)]
    if delay:
        label += f'_{delay}ms'
        protocol_options += ['--ack-delay', str(delay)]
    if cca:
        label += f'_{cca}'
        protocol_options += ['--congestion-control', cca]
    treatment = Treatment(PROTOCOL, label=label,
        network_options=network_options, protocol_options=protocol_options)
    return treatment

'''
Initialize default treatments
'''
def generate_treatments():
    ccas = [None, 'bbr', 'bbr1'] # Cubic, BBRv3, BBRv1
    treatments = []
    for c in ccas:
        suf = f'_{c}' if c else ''
        treatments.extend([
            Treatment(PROTOCOL, label=f'picoquic{suf}', network_options=[], protocol_options=pos(cca=c)),
            Treatment(PROTOCOL, label=f'picoquic_split{suf}', network_options=['--proxy', 'picoquic'], protocol_options=pos(quacking=False, cca=c)),
        ])
        for e2e_ack_delay in E2E_ACK_DELAYS:
            treatments.append(
                Treatment(PROTOCOL, label=f'picoquic_{e2e_ack_delay}ms{suf}',
                          network_options=[],
                          protocol_options=pos(ack_delay=e2e_ack_delay, cca=c)),
            )
    labels = [treatment.label() for treatment in treatments]
    treatment_map = {}
    for label, treatment in zip(labels, treatments):
        treatment_map[label] = treatment
    return labels, treatment_map

labels, _treatment_map = generate_treatments()

'''
Initialize new experiment treatment (excluding network settings)
with new `label`. Determine settings based on patterns in label.
'''
def treatment_map(label, treatments=_treatment_map):
    if label in treatments:
        return treatments[label]

    # Extract the CCA
    cca = None
    label, bbr1 = re.subn(r'_bbr1$', '', label)
    if bbr1:
        cca = 'bbr1'
    label, bbr3 = re.subn(r'_bbr$', '', label)
    if bbr3:
        cca = 'bbr'

    # Case 1 - rtunnel.
    pattern = re.compile(
        r'^picoquic_rtunnel_retx(?P<max_num_retx>\d+)'
        r'(?:_ordered(?P<ordered>\d+))?'
        r'(?:_(?P<delay>\d+)ms)?'
    )
    match = pattern.fullmatch(label)
    if match:
        match = match.groupdict()
        return generate_rtunnel_treatment(match['max_num_retx'], match['ordered'], match['delay'], cca=cca)

    # Case 2 - other.
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
            cache_capacity=match['cache_capacity'],
            reset='reset' in label,
            cca=cca
        )
    # Unknown treatment
    raise Exception(label)
