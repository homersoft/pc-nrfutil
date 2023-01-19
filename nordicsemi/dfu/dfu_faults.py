from __future__ import annotations  # enabling support for defining typing for self inside the DFUFault class

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class DFUFaultType(Enum):
    """ Enumerator class representing all available types of fault """
    CRC_VALIDATION = "CRC VALIDATION"
    ABORT = "ABORT"


@dataclass
class DFUStage:
    """
    Class for keeping DFU Stage details:
    - name: name of the DFU stage. E.g. DFUStageName.INIT_PACKET
    - progress: DFU stage progress given as a percentage value in range 0-100 %
    """
    name: Optional[DFUStageName] = None
    progress: float = 0


class DFUStageName(Enum):
    """ Enumerator class representing all available DFU Stage Names"""
    INIT_PACKET = "INIT PACKET"
    FIRMWARE_UPDATE = "FIRMWARE UPDATE"


class DFUFault:
    """ DFU Fault class that contains all the details about the fault that is to be simulated """
    def __init__(self, fault_type: DFUFaultType, target_dfu_stage: DFUStage,
                 callback_function: Optional[Callable] = None):
        """
        Construct DFU fault object.

        :param fault_type: type of fault to generate
        :param target_dfu_stage: desired DFU stage (name and progress) during which the fault should be generated
        :param callback_function: optional function that will be called when fault should occur
        """
        self.fault_type = fault_type
        self.target_dfu_stage = target_dfu_stage
        self.callback_function = callback_function
        self.called = False

    def call_fault(self, current_dfu_stage: DFUStage) -> Optional[DFUFault]:
        """
        Calls the fault if the fault conditions are met

        :param current_dfu_stage: current DFU Stage
        :return DFUFault object if the fault was called else None
        """
        if current_dfu_stage.name == self.target_dfu_stage.name:
            if current_dfu_stage.progress >= self.target_dfu_stage.progress and not self.called:
                if self.callback_function is not None:
                    self.callback_function()
                self.called = True
                return self
        return None


class DFUFaultsFactory:
    """ Factory class used to create specific DFU Faults """

    @staticmethod
    def create_crc_validation_fault(target_dfu_stage: DFUStage,
                                    callback_function: Optional[Callable] = None) -> DFUFault:
        """
        Create fault that simulates CRC Validation Error.

        :param target_dfu_stage: desired DFU stage (name and progress) during which the fault should be generated
        :param callback_function: function that will be called when fault should occur
        :return DFUFault object with defined CRC_VALIDATION fault details
        """
        return DFUFault(DFUFaultType.CRC_VALIDATION, target_dfu_stage, callback_function)

    @staticmethod
    def create_abort_fault(target_dfu_stage: DFUStage,
                           callback_function: Optional[Callable] = None) -> DFUFault:
        """
        Create fault that simulates aborting the DFU.

        :param target_dfu_stage: desired DFU stage (name and progress) during which the fault should be generated
        :param callback_function: function that will be called when fault should occur
        :return DFUFault object with defined ABORT fault details
        """
        return DFUFault(DFUFaultType.ABORT, target_dfu_stage, callback_function)


class DFUFaultManager:
    """ DFU Fault Manager class for handling simulation of all possible faults during DFU procedure """
    def __init__(self):
        self.dfu_faults = {}

    def add_fault(self, fault: DFUFault):
        """
        Add fault to the DFU Fault manager.
        NOTE: Only one item of given fault can be stored in the dfu faults container

        :param fault: DFUFault object with the fault details
        """
        self.dfu_faults[fault.fault_type] = fault

    def _get_fault(self, fault_type: DFUFaultType) -> Optional[DFUFault]:
        """
        Gets the fault of given type from the dfu faults container.

        :param fault_type: type of the dfu fault
        """
        return self.dfu_faults.get(fault_type, None)

    def on_fault(self, fault_type: DFUFaultType, current_dfu_stage: DFUStage):
        """
        Function that should be called on fault conditions.
        NOTE: This function does not simulate the exact fault but only provides the information if the fault should
        be called on the DFU controller side. This means that if the fault conditions are met then the fault details
        are returned and the DFU controller should raise an error.

        :param fault_type: fault type that should be called. E.g. DfuFaultType.CRC_VALIDATION
        :param current_dfu_stage: Current DFU Stage (name and progress)
        :return DFUFault object if the fault was called else None
        """
        fault = self._get_fault(fault_type)
        if fault is not None:
            return fault.call_fault(current_dfu_stage)
        return None
