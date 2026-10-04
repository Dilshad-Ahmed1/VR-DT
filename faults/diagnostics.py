"""Diagnostic API kept separate from physical fault injection profiles."""

from twin.fault_detector import FaultDetection, FaultDetector
from twin.fault_severity import estimate_fault_severity

__all__ = ["FaultDetection", "FaultDetector", "estimate_fault_severity"]