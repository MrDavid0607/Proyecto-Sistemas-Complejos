"""Formato de mensajes de ComplexNet (header + payload, serializados en JSON)."""

import json
import time
import uuid
from dataclasses import dataclass, field

RESOURCE_BEACON = "RESOURCE_BEACON"
TASK_SUBMIT = "TASK_SUBMIT"
TASK_ACK = "TASK_ACK"
TASK_RESULT = "TASK_RESULT"
PING = "PING"
PONG = "PONG"

MESSAGE_TYPES = (
    RESOURCE_BEACON,
    TASK_SUBMIT,
    TASK_ACK,
    TASK_RESULT,
    PING,
    PONG,
)


class InvalidMessage(ValueError):
    """El datagrama recibido no cumple el formato de mensaje."""


@dataclass
class Message:
    type: str
    sender_id: str
    payload: dict = field(default_factory=dict)
    lamport: int = 0
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self):
        return {
            "header": {
                "message_id": self.message_id,
                "sender_id": self.sender_id,
                "type": self.type,
                "timestamp": self.timestamp,
                "lamport": self.lamport,
            },
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data):
        try:
            header = data["header"]
            return cls(
                type=header["type"],
                sender_id=header["sender_id"],
                payload=data.get("payload", {}),
                lamport=int(header.get("lamport", 0)),
                message_id=header["message_id"],
                timestamp=int(header["timestamp"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidMessage(f"mensaje mal formado: {error}") from error


def serialize(message):
    return json.dumps(message.to_dict()).encode("utf-8")


def deserialize(data):
    try:
        decoded = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidMessage(f"JSON inválido: {error}") from error
    if not isinstance(decoded, dict):
        raise InvalidMessage("el mensaje no es un objeto JSON")
    return Message.from_dict(decoded)
