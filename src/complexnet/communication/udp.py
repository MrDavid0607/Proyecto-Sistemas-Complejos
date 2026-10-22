"""Implementación UDP + JSON de la capa de comunicación.

Se usa un único socket para enviar y recibir: el puerto de origen de cada
datagrama es el puerto de escucha del nodo, por lo que cualquier nodo puede
responder directamente a la dirección de origen.
"""

import collections
import socket
import threading

from .interface import ICommunicationLayer
from .messages import InvalidMessage, deserialize, serialize

MAX_DATAGRAM = 65535
SEEN_CACHE_SIZE = 2048


class UDPCommunication(ICommunicationLayer):

    def __init__(self, port, on_error=None, on_send=None):
        self.port = port
        self.on_error = on_error or (lambda text: None)
        self.on_send = on_send
        self._handler = None
        self._running = False
        self._thread = None
        self._seen = collections.OrderedDict()
        self._seen_lock = threading.Lock()

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.bind(("", port))
        self._sock.settimeout(0.5)
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            # Windows: evita que un ICMP "puerto inalcanzable" rompa recvfrom.
            self._sock.ioctl(socket.SIO_UDP_CONNRESET, False)

    # ------------------------------------------------------------------

    def start(self, handler):
        self._handler = handler
        self._running = True
        self._thread = threading.Thread(
            target=self._receive_loop, daemon=True, name=f"udp-rx-{self.port}"
        )
        self._thread.start()

    def stop(self):
        self._running = False
        try:
            self._sock.close()
        except OSError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2)

    def send(self, message, address):
        self._send(message, address)

    def broadcast(self, message, address):
        self._send(message, address)

    # ------------------------------------------------------------------

    def _send(self, message, address):
        if not self._running:
            return
        try:
            self._sock.sendto(serialize(message), address)
        except OSError as error:
            if self._running:
                self.on_error(f"no se pudo enviar a {address}: {error}")
            return
        if self.on_send is not None:
            self.on_send(message, address)

    def _is_duplicate(self, message_id):
        with self._seen_lock:
            if message_id in self._seen:
                return True
            self._seen[message_id] = True
            if len(self._seen) > SEEN_CACHE_SIZE:
                self._seen.popitem(last=False)
            return False

    def _receive_loop(self):
        while self._running:
            try:
                data, address = self._sock.recvfrom(MAX_DATAGRAM)
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    continue
                return
            try:
                message = deserialize(data)
            except InvalidMessage as error:
                self.on_error(f"mensaje descartado desde {address}: {error}")
                continue
            if self._is_duplicate(message.message_id):
                continue
            try:
                self._handler(message, address)
            except Exception as error:  # un handler roto no debe matar la recepción
                self.on_error(f"error procesando {message.type}: {error!r}")
