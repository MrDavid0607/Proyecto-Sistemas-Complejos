import json
import threading

import pytest

from complexnet.communication import (
    InvalidMessage,
    Message,
    UDPCommunication,
    deserialize,
    serialize,
    RESOURCE_BEACON,
)
from complexnet.discovery import OFFLINE, ONLINE, PeerTable
from complexnet.failure_detection import FailureDetector
from complexnet.monitoring import EventLogger, Metrics
from complexnet.synchronization import LamportClock
from complexnet.tasks import executors


class FakeTime:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


BEACON = {
    "port": 9999,
    "cpu_free_pct": 80.0,
    "ram_free_mb": 2048.0,
    "bandwidth_mbps": 100,
    "active_tasks": 1,
}


# ---------------------------------------------------------------- mensajes

def test_mensaje_ida_y_vuelta_json():
    original = Message(RESOURCE_BEACON, "nodo-01", {"port": 1}, lamport=5)
    copy = deserialize(serialize(original))
    assert copy.type == RESOURCE_BEACON
    assert copy.sender_id == "nodo-01"
    assert copy.payload == {"port": 1}
    assert copy.lamport == 5
    assert copy.message_id == original.message_id


def test_formato_header_payload():
    data = json.loads(serialize(Message("PING", "a", {})))
    assert set(data) == {"header", "payload"}
    assert {"message_id", "sender_id", "type", "timestamp"} <= set(data["header"])


@pytest.mark.parametrize(
    "raw", [b"no es json", b"[1, 2]", b'{"payload": {}}', b"\xff\xfe"]
)
def test_mensajes_invalidos_se_rechazan(raw):
    with pytest.raises(InvalidMessage):
        deserialize(raw)


def test_los_message_id_son_unicos():
    assert Message("PING", "a").message_id != Message("PING", "a").message_id


def test_udp_entrega_y_descarta_duplicados():
    received = []
    done = threading.Event()

    def handler(message, address):
        received.append(message)
        done.set()

    rx = UDPCommunication(0)
    port = rx._sock.getsockname()[1]
    rx.start(handler)
    tx = UDPCommunication(0)
    tx._running = True
    try:
        message = Message("PING", "tx", {})
        tx.send(message, ("127.0.0.1", port))
        tx.send(message, ("127.0.0.1", port))  # mismo message_id
        assert done.wait(2)
        threading.Event().wait(0.3)
        assert len(received) == 1
    finally:
        rx.stop()
        tx.stop()


# ----------------------------------------------------------------- lamport

def test_lamport_tick_y_update():
    clock = LamportClock()
    assert clock.tick() == 1
    assert clock.tick() == 2
    assert clock.update(10) == 11
    assert clock.update(3) == 12  # un valor menor no retrocede el reloj


def test_lamport_preserva_causalidad():
    a, b = LamportClock(), LamportClock()
    sent = a.tick()
    received = b.update(sent)
    assert received > sent


# --------------------------------------------------------------- peer table

def test_peer_table_nuevo_actualiza_y_recupera():
    clock = FakeTime()
    table = PeerTable(clock=clock)
    peer, event = table.update_from_beacon("n2", "10.0.0.2", BEACON)
    assert event == "new" and peer.status == ONLINE
    _, event = table.update_from_beacon("n2", "10.0.0.2", BEACON)
    assert event == "update"
    table.mark_offline("n2")
    assert table.get("n2").status == OFFLINE
    assert table.active() == []
    _, event = table.update_from_beacon("n2", "10.0.0.2", BEACON)
    assert event == "recovered" and table.get("n2").status == ONLINE


def test_peer_table_expira_por_timeout():
    clock = FakeTime()
    table = PeerTable(clock=clock)
    table.update_from_beacon("n2", "10.0.0.2", BEACON)
    clock.now += 4.9
    assert table.expired(5) == []
    clock.now += 0.2
    assert [p.node_id for p in table.expired(5)] == ["n2"]


def test_latencia_con_media_movil_y_reputacion_acotada():
    table = PeerTable()
    table.update_from_beacon("n2", "10.0.0.2", BEACON)
    assert table.update_latency("n2", 10.0) == 10.0
    assert table.update_latency("n2", 20.0) == pytest.approx(13.0)
    assert table.adjust_reputation("n2", +5) == 1.0
    assert table.adjust_reputation("n2", -5) == 0.0
    assert table.update_latency("desconocido", 1.0) is None


# ------------------------------------------------------- detector de fallos

def test_detector_marca_offline_y_notifica_una_sola_vez():
    clock = FakeTime()
    table = PeerTable(clock=clock)
    table.update_from_beacon("n2", "10.0.0.2", BEACON)
    detector = FailureDetector(table, timeout=5.0)
    notified = []
    detector.subscribe(notified.append)

    assert detector.check_once() == []
    clock.now += 6
    assert detector.check_once() == ["n2"]
    assert detector.check_once() == []  # ya está OFFLINE
    assert notified == ["n2"]
    assert table.get("n2").status == OFFLINE


def test_detector_respeta_el_timeout_de_5_segundos():
    clock = FakeTime()
    table = PeerTable(clock=clock)
    table.update_from_beacon("n2", "10.0.0.2", BEACON)
    detector = FailureDetector(table, timeout=5.0)
    clock.now += 5.0
    assert detector.check_once() == []  # exactamente 5 s todavía no es > 5 s
    clock.now += 0.01
    assert detector.check_once() == ["n2"]


# ---------------------------------------------------------------- ejecutores

def test_regresion_lineal_recupera_los_parametros():
    result = executors.execute(
        "regresion_lineal",
        {"n_samples": 5000, "seed": 1, "true_slope": 2.35,
         "true_intercept": 0.81, "noise": 0.2},
    )
    assert result["slope"] == pytest.approx(2.35, abs=0.05)
    assert result["intercept"] == pytest.approx(0.81, abs=0.1)
    assert result["r2"] > 0.99


def test_regresion_es_reproducible_por_semilla():
    a = executors.execute("regresion_lineal", {"seed": 3})
    b = executors.execute("regresion_lineal", {"seed": 3})
    assert a == b


def test_descenso_de_gradiente_converge():
    result = executors.execute(
        "regresion_lineal",
        {"n_samples": 500, "seed": 2, "epochs": 3000, "learning_rate": 0.01,
         "noise": 0.1},
    )
    assert result["method"] == "gradient_descent"
    assert result["slope"] == pytest.approx(2.35, abs=0.1)


def test_tarea_desconocida_lanza_error():
    with pytest.raises(ValueError):
        executors.execute("no-existe", {})


# ------------------------------------------------------- logger y métricas

def test_logger_escribe_jsonl_con_lamport(tmp_path):
    clock = LamportClock()
    clock.tick()
    log = EventLogger("n1", clock, log_dir=str(tmp_path), console=False)
    log.event("TASK_CREATED", task="t1")
    log.close()
    line = json.loads((tmp_path / "n1.jsonl").read_text().splitlines()[0])
    assert line["event"] == "TASK_CREATED"
    assert line["node"] == "n1" and line["lamport"] == 1 and line["task"] == "t1"


def test_metricas_snapshot():
    metrics = Metrics()
    metrics.incr("tasks_submitted", 4)
    metrics.incr("tasks_failed")
    metrics.record("latencies", 10.0)
    metrics.record("latencies", 20.0)
    snap = metrics.snapshot()
    assert snap["failure_rate"] == 0.25
    assert snap["avg_latency_ms"] == 15.0
    assert snap["avg_recovery_time_sec"] is None
