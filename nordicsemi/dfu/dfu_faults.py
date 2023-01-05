from __future__ import annotations  # enabling support for defining typing for self inside the DFUFault class
from enum import Enum
from time import time
from typing import Callable, Optional


class DFUFaultType(Enum):
    """ Enumerator class representing all available types of fault """
    CRC_VALIDATION = "CRC VALIDATION"
    POWER_OFF = "POWER OFF"
    ABORT = "ABORT"


class DFUStage(Enum):
    """ Enumerator class representing all available DFU Stages """
    INIT_PACKET = "INIT PACKET"
    FIRMWARE_UPDATE = "FIRMWARE UPDATE"
    AFTER_FIRMWARE_UPDATE = "AFTER FIRMWARE UPDATE"


class DFUFault:
    """ DFU Fault class that contains all the details about the fault that is to be simulated """
    def __init__(self, fault_type: DFUFaultType, target_dfu_stage: DFUStage, delay_s: Optional[float] = 0,
                 callback_function: Optional[Callable] = None):
        """
        Construct DFU fault object.

        :param fault_type: type of fault to generate
        :param target_dfu_stage: desired DFU stage during which the fault should be generated
        :param delay_s: delay in seconds (counted from first possible fault call in the target DFU stage) after which
                        fault should be generated. None to generate fault on every possible call (permanent fault).
                        NOTE: Delay parameter assumes that the call_fault method is called repeatedly during the
                              dfu procedure (e.g. after sending each data chunk). This is needed to calculate the
                              elapsed DFU stage time. When the time is higher or equal to the delay the the fault is
                              generated.
        :param callback_function: optional function that will be called when fault should occur
        """
        if delay_s is not None:
            assert delay_s >= 0, "Delay must be higher or equal to 0."

        self.fault_type = fault_type
        self.target_dfu_stage = target_dfu_stage
        self.delay_s = delay_s
        self.callback_function = callback_function
        self._elapsed_time = 0
        self._first_call_time = None
        self.called = False

    def call_fault(self, current_dfu_stage: DFUStage) -> Optional[DFUFault]:
        """
        Calls the fault if the fault conditions are met

        :param current_dfu_stage: current DFU Stage
        :return DFUFault object if the fault was called else None
        """
        if current_dfu_stage == self.target_dfu_stage:
            if self._first_call_time is None:
                self._first_call_time = time()
            self._elapsed_time += time() - self._first_call_time
            if self.delay_s is None or (self._elapsed_time >= self.delay_s and not self.called):
                if self.callback_function is not None:
                    self.callback_function()
                self.called = True
                return self
        return None


class DFUFaultsFactory:
    """ Factory class used to create specific DFU Faults """

    @staticmethod
    def create_crc_validation_fault(target_dfu_stage: DFUStage, delay_s: Optional[float] = 0,
                                    callback_function: Optional[Callable] = None) -> DFUFault:
        """
        Create fault that simulates CRC Validation Error.

        :param target_dfu_stage: desired DFU stage during which the fault should be generated
        :param delay_s: delay in seconds (counted from first possible fault call in the target DFU stage) after which
                        fault should be generated. None to generate fault on every possible call (permanent fault).
        :param callback_function: function that will be called when fault should occur
        :return DFUFault object with defined CRC_VALIDATION fault details
        """
        return DFUFault(DFUFaultType.CRC_VALIDATION, target_dfu_stage, delay_s, callback_function)

    @staticmethod
    def create_power_off_fault(target_dfu_stage: DFUStage, delay_s: float, power_cycle_callback: Callable) -> DFUFault:
        """
        Create fault that simulates Power Off Error.

        :param target_dfu_stage: desired DFU stage during which the fault should be generated
        :param delay_s: delay in seconds (counted from first possible fault call in the target DFU stage) after which
                        fault should be generated. None to generate fault on every possible call (permanent fault).
        :param power_cycle_callback: power cycle function callback that will be called when fault should occur
        :return DFUFault object with defined POWER_OFF fault details
        """
        return DFUFault(DFUFaultType.POWER_OFF, target_dfu_stage, delay_s, power_cycle_callback)

    @staticmethod
    def create_abort_fault(target_dfu_stage: DFUStage, delay_s: Optional[float] = 0,
                           callback_function: Optional[Callable] = None) -> DFUFault:
        """
        Create fault that simulates aborting the DFU.

        :param target_dfu_stage: desired DFU stage during which the fault should be generated
        :param delay_s: delay in seconds (counted from first possible fault call in the target DFU stage) after which
                        fault should be generated. None to generate fault on every possible call (permanent fault).
        :param callback_function: function that will be called when fault should occur
        :return DFUFault object with defined ABORT fault details
        """
        return DFUFault(DFUFaultType.ABORT, target_dfu_stage, delay_s, callback_function)


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
        :param current_dfu_stage: Current DFU Stage
        :return DFUFault object if the fault was called else None
        """
        fault = self._get_fault(fault_type)
        if fault is not None:
            return fault.call_fault(current_dfu_stage)
        return None
