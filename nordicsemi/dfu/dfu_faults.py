from __future__ import annotations  # enabling support for defining typing for self inside the DFUFault class
from enum import Enum
from time import time
from typing import Callable, Optional


class DFUFaultType(Enum):
    """ Enumerator class representing all available types of fault """
    CRC_VALIDATION = "CRC VALIDATION"


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
        :param delay_s: delay in seconds (starting from the target DFU stage) after which fault should be generated.
                        None to generate fault on every call (permanent fault)
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

    @classmethod
    def create_crc_validation_fault(cls, target_dfu_stage: DFUStage, delay_s: Optional[float] = 0,
                                    callback_function: Optional[Callable] = None) -> DFUFault:
        """
        Create fault that simulates CRC Validation Error.

        :param target_dfu_stage: desired DFU stage during which the fault should be generated
        :param delay_s: delay in seconds (starting from the target DFU stage) after which fault should be generated.
                        None to generate fault on every call (permanent fault)
        :param callback_function: function that will be called when fault should occur
        :return DFUFault object with defined CRC_VALIDATION fault details
        """
        return cls(DFUFaultType.CRC_VALIDATION, target_dfu_stage, delay_s, callback_function)


class DFUFaultManager:
    """ DFU Fault Manager class for handling simulation of all possible faults during DFU procedure """
    def __init__(self):
        self.crc_validation_fault = None

    def add_crc_validation_fault(self, fault: DFUFault):
        """
        Add CRC Validation fault to the DFU Fault manager

        :param fault: DFUFault object with CRC Validation fault details
        """
        self.crc_validation_fault = fault

    def on_crc_validation(self, current_dfu_stage: DFUStage) -> Optional[DFUFault]:
        """
        Function that should be called on CRC Validation.

        :param current_dfu_stage: Current DFU Stage
        :return DFUFault object if the fault was called else None
        """
        if self.crc_validation_fault is not None:
            return self.crc_validation_fault.call_fault(current_dfu_stage)
        return None
