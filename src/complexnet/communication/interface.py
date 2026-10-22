"""Interfaz abstracta de la capa de comunicación (ICapaComunicacion del UML).

Los servicios distribuidos solo dependen de esta interfaz, de modo que el
transporte (UDP, TCP, ZeroMQ, ...) se puede cambiar sin tocar la lógica.
"""

from abc import ABC, abstractmethod


class ICommunicationLayer(ABC):

    @abstractmethod
    def start(self, handler):
        """Empieza a recibir. handler(message, address) se invoca por mensaje."""

    @abstractmethod
    def stop(self):
        """Detiene la recepción y libera el transporte."""

    @abstractmethod
    def send(self, message, address):
        """Envía un mensaje punto a punto (unicast) a address = (host, port)."""

    @abstractmethod
    def broadcast(self, message, address):
        """Envía un mensaje de difusión a address = (host, port)."""
