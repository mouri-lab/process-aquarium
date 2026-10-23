import pytest

from src.telemetry import SimulatedTransfer, ProtocolError, snapshot_from_dict
from test_telemetry import sample
from tools.demo_multiverse import demo_transfers


def test_simulated_transfer_roundtrip_and_real_collector_rejection():
    from dataclasses import replace
    snapshot = replace(sample(), source='fixture', simulated_transfers=(
        SimulatedTransfer('host-b', 'boot-b', 1, 100, 200),))
    assert snapshot_from_dict(snapshot.to_dict()) == snapshot
    with pytest.raises(ProtocolError):
        snapshot_from_dict(replace(snapshot, source='psutil').to_dict())


@pytest.mark.parametrize('change', [{'host_id':'host-a'}, {'host_id':''}, {'boot_id':''},
    {'interval_seconds':0}, {'interval_seconds':float('inf')}, {'sent_bytes':-1},
    {'received_bytes':True}, {'sent_bytes':2**53}])
def test_invalid_simulated_transfers_are_rejected(change):
    from dataclasses import replace
    data = replace(sample(), source='fixture', simulated_transfers=(
        SimulatedTransfer('host-b', 'boot-b', 1, 100, 200),)).to_dict()
    data['simulated_transfers'][0].update(change)
    with pytest.raises(ProtocolError):
        snapshot_from_dict(data)


def test_demo_has_matching_host_totals_and_varies_volume_and_direction():
    for sequence in [1, 17, 33, 49, 65]:
        peers, activity = demo_transfers(3, sequence)
        totals = [[0,0] for _ in activity]
        for owner, group in enumerate(peers):
            for p in group:
                target = int(p.host_id.split('-')[1])
                totals[owner][0] += p.sent_bytes
                totals[owner][1] += p.received_bytes
                totals[target][0] += p.received_bytes
                totals[target][1] += p.sent_bytes
        assert totals == [[a.sent_bytes,a.received_bytes] for a in activity]
    assert demo_transfers(3,17)[1][0].sent_bytes > demo_transfers(3,1)[1][0].sent_bytes
    assert demo_transfers(3,33)[1][0].received_bytes > 0
    assert all(a.sent_bytes == a.received_bytes == 0 for a in demo_transfers(3,65)[1])
