"""Transport boundaries between control logic and plant adapters."""

from .interface import CommunicationInterface
from .simulated import SimulatedCommunication

__all__ = ["CommunicationInterface", "SimulatedCommunication"]