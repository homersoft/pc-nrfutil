import logging
from enum import Enum
from typing import Callable, Optional

LOGGER = logging.getLogger()


class DFUFaultType(Enum):
    """
    Enumerator class representing all available types of fault.
    """
    CRC_VALIDATION = "CRC VALIDATION"


class DFUStage(Enum):
    """
    Enumerator class representing all available DFU Stages
    """
    INIT_PACKET = "INIT PACKET"
    FIRMWARE_UPDATE = "FIRMWARE UPDATE"
    AFTER_FIRMWARE_UPDATE = "AFTER FIRMWARE UPDATE"


class DFUFault:
    def __init__(self, fault_type: DFUFaultType, target_dfu_stage: DFUStage, call_number: Optional[int] = None,
                 callback_function: Callable = None):
        """
        Construct DFU fault object.

        :param fault_type: type of fault to generate
        :param target_dfu_stage: desired DFU stage during which the fault should be generated
        :param call_number: number of call (starting from 1) on which fault should be generated.
                            None to generate fault on every call
        :param callback_function: function that will be called when fault should occur

        """
        if call_number is not None:
            assert call_number > 0, "Number of calls must be higher than 0."

        self.fault_type = fault_type
        self.target_dfu_stage = target_dfu_stage
        self.call_number = call_number
        self._calls_counter = 0
        self.callback_function = callback_function

    def call_fault(self, current_dfu_stage: DFUStage):
        """
        Calls the fault if the fault conditions are met

        :param current_dfu_stage: current DFU Stage
        """
        if current_dfu_stage == self.target_dfu_stage:
            self._calls_counter += 1
            if self.call_number is None or self.call_number == self._calls_counter:
                if self.callback_function is not None:
                    self.callback_function()
                return self
        return None

    @classmethod
    def create_crc_validation_fault(cls, target_dfu_stage: DFUStage, call_number: Optional[int],
                                    callback_function: Optional[Callable] = None):
        """
        Create fault that simulates CRC Validation Error.

        :param target_dfu_stage: desired DFU stage during which the fault should be generated
        :param call_number: number of call (starting from 1) on which fault should be generated.
                            None to generate fault on every call
        :param callback_function: function that will be called when fault should occur
        """
        return cls(DFUFaultType.CRC_VALIDATION, target_dfu_stage, call_number, callback_function)


class DFUFaultManager:
    def __init__(self):
        self._crc_validation_fault = None

    def add_crc_validation_fault(self, fault: DFUFault):
        """
        Add CRC Validation fault to the DFU Fault manager

        :param fault: DFU fault object with CRC Validation fault details
        """
        self._crc_validation_fault = fault

    def on_crc_validation(self, current_dfu_stage: DFUStage):
        """
        Function that should be called on CRC Validation.

        :param current_dfu_stage: Current DFU Stage
        """
        if self._crc_validation_fault is not None:
            return self._crc_validation_fault.call_fault(current_dfu_stage)
        return None
