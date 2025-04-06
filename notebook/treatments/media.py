from typing import Optional
from experiment import Treatment

DEFAULT_THRESHOLD = 8
IBLT_MULTIPLIER = 4
DEFAULT_FREQ_PKTS = 2
PROTOCOL = 'media'

def nos(iblt: bool=False, quack_hint: bool=False, quack_nack: bool=False):
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
    return options

def pos(ack_delay: Optional[int]=None):
    options = ['--client-quacker']
    if ack_delay is not None:
        options += ['--ack-delay', str(ack_delay)]
    return options

def generate_treatments():
    treatments = [
	    Treatment(PROTOCOL, label='baseline', network_options=[], protocol_options=[]),
	    Treatment(PROTOCOL, label='psum_delay0', network_options=nos(), protocol_options=pos(0)),
	    Treatment(PROTOCOL, label='psum_delay45', network_options=nos(), protocol_options=pos(45)),
	    Treatment(PROTOCOL, label='psum_delay90', network_options=nos(), protocol_options=pos(90)),
	    Treatment(PROTOCOL, label='psum_delay45_hint', network_options=nos(quack_hint=True), protocol_options=pos(45)),
	    Treatment(PROTOCOL, label='psum_delay45_nack', network_options=nos(quack_nack=True), protocol_options=pos(45)),
	    Treatment(PROTOCOL, label='psum_delay45_hint_nack', network_options=nos(quack_hint=True, quack_nack=True), protocol_options=pos(45)),
	    Treatment(PROTOCOL, label='iblt_delay0', network_options=nos(iblt=True), protocol_options=pos(0)),
	    Treatment(PROTOCOL, label='iblt_delay45', network_options=nos(iblt=True), protocol_options=pos(45)),
	    Treatment(PROTOCOL, label='iblt_delay90', network_options=nos(iblt=True), protocol_options=pos(90)),
	    Treatment(PROTOCOL, label='iblt_delay45_hint', network_options=nos(iblt=True, quack_hint=True), protocol_options=pos(45)),
	    Treatment(PROTOCOL, label='iblt_delay45_nack', network_options=nos(iblt=True, quack_nack=True), protocol_options=pos(45)),
	    Treatment(PROTOCOL, label='iblt_delay45_hint_nack', network_options=nos(iblt=True, quack_hint=True, quack_nack=True), protocol_options=pos(45)),
	]
    labels = [treatment.label() for treatment in treatments]
    treatment_map = {}
    for label, treatment in zip(labels, treatments):
        treatment_map[label] = treatment
    return labels, treatment_map

labels, treatment_map = generate_treatments()
