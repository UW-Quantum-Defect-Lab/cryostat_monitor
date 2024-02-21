"""
This module contains utility methods for supporting message-based devices
and extending the functionality of the pyvisa package.
"""

import threading
import time
import warnings
from typing import TypeVar, Type

import tracemalloc
import pyvisa
import pyvisa.constants
from pyvisa import ResourceManager, VisaIOError
from pyvisa.attributes import Attribute
from pyvisa.resources import Resource, SerialInstrument, USBInstrument, GPIBInstrument, MessageBasedResource

# TODO: This types may not work great with type hinting. Find solution.
ResourceType = TypeVar('ResourceType', Resource, MessageBasedResource, SerialInstrument, USBInstrument, GPIBInstrument)
MessageBasedResourceType = TypeVar(
    'MessageBasedResourceType', MessageBasedResource, SerialInstrument, USBInstrument, GPIBInstrument)

tracemalloc.start()


def _str_is_float(string: str) -> bool:
    """
    Check if a string is a float.

    Parameters
    ----------
    string : str
        The string to check.

    Returns
    -------
    bool
        True if the string is a float, False otherwise.
    """
    try:
        float(string)
        return True
    except ValueError:
        return False


def _convert_str(string: str) -> int | float | str:
    """
    Convert a string to an int, or float if applicable. Defaults to string.

    Parameters
    ----------
    string : str
        The string to convert.

    Returns
    -------
    int | float | str
        The converted string.
    """
    if string.isdigit():
        return int(string)
    elif _str_is_float(string):
        return float(string)
    else:
        return string


def _suppress_resource_warning(method):
    """
    A wrapper method used to suppress `ResourceWarning` when opening a resource.

    Parameters
    ----------
    method : callable
        The method to wrap.

    Returns
    -------
    callable
        The wrapped method.
    """
    def wrapper(*args, **kwargs):
        previous_filters = warnings.filters[:]
        warnings.filterwarnings("ignore", category=ResourceWarning)
        results = method(*args, **kwargs)
        warnings.filters = previous_filters
        return results
    return wrapper


@_suppress_resource_warning
def find_available_resources_by_visa_attribute(
        rm: ResourceManager,
        visa_attribute: Type[Attribute],
        desired_attr_value: str,
        is_partial: bool = False,
        connection_time_delay: float = 0,
        correct_read_termination: bool = False,
        **rm_kwargs,
) -> list[ResourceType]:
    """
    A method to find all resources with a given visa attribute value, or part of.

    For example, for a given USB resource, you want all resources with attribute AttrVI_ATTR_MODEL_NAME == 'Matisse TS',
    or 'Matisse TS' in AttrVI_ATTR_MODEL_NAME. If the `is_partial` argument is true, it will find all resources
    that contain the desired value.

    Note
    ----
    This method attempts to connect to every resource available on your device, so it is quite time-consuming.
    Best used during the development part of an application for easy device identification, especially on a new system.

    Parameters
    ----------
    rm : ResourceManager
        The resource manager object.
    visa_attribute : Type[Attribute]
        The visa attribute to check.
    desired_attr_value : str
        The desired value of the visa attribute.
    is_partial : bool, optional
        If True, it will find all resources that contain the desired value, instead of looking for an exact match.
        Defaults to False.
    connection_time_delay : float, optional
        The time delay to wait after connecting to a resource. Defaults to 0.
    correct_read_termination : bool, optional
        If True, it will attempt to automatically identify the read termination of the resource. Defaults to False.
    **rm_kwargs : dict, optional
        Additional keyword arguments to pass to the resource manager.

    Returns
    -------
    list[ResourceType]
        A list of resources with the desired visa attribute value.
    """
    connected_resources_names = rm.list_resources()
    matching_attr_resource_list: list[ResourceType] = []

    for resource_name in connected_resources_names:
        try:
            resource = rm.open_resource(resource_name, **rm_kwargs)
            if connection_time_delay > 0:  # For arduino initialization
                time.sleep(connection_time_delay)

            try:
                resource.clear()
            except VisaIOError as e:  # the device does not properly implement clear
                pass

            if isinstance(resource, MessageBasedResource) and correct_read_termination:
                resource.read_termination = auto_detect_read_termination(resource)

            resource_attr_value = resource.get_visa_attribute(visa_attribute.attribute_id)
            resource.close()

            match_condition = (desired_attr_value in resource_attr_value) \
                if is_partial else (resource_attr_value == desired_attr_value)

            if match_condition:
                matching_attr_resource_list.append(resource)

        except VisaIOError as e:
            pass  # resource is probably used by another application, so we ignore it.

    return matching_attr_resource_list


@_suppress_resource_warning
def find_available_resources_by_idn(
        rm: ResourceManager,
        desired_idn: str,
        is_partial: bool = False,
        connection_time_delay: float = 0,
        correct_read_termination: bool = False,
        **rm_kwargs,
) -> list[MessageBasedResourceType]:
    """
    A method to find all message-based resources with a given IDN value, or part of.

    For example, for a given USB resource, you want all resources with IDN == 'Matisse TS', or 'Matisse TS' in IDN.
    If the `is_partial` argument is true, it will find all resources that contain the desired value.

    Note
    ----
    This method attempts to connect to every resource available on your device, so it is quite time-consuming.
    Best used during the development part of an application for easy device identification, especially on a new system.

    Parameters
    ----------
    rm : ResourceManager
        The resource manager object.
    desired_idn : str
        The desired value of the IDN.
    is_partial : bool, optional
        If True, it will find all resources that contain the desired value, instead of looking for an exact match.
        Defaults to False.
    connection_time_delay : float, optional
        The time delay to wait after connecting to a resource. Defaults to 0.
    correct_read_termination : bool, optional
            If True, it will attempt to automatically identify the read termination of the resource. Defaults to False.
    **rm_kwargs : dict, optional
        Additional keyword arguments to pass to the resource manager.

    Returns
    -------
    list[MessageBasedResourceType]
        A list of message-based resources with the desired IDN value.
    """
    connected_resources_names = rm.list_resources()
    matching_idn_resource_list: list[MessageBasedResourceType] = []

    for resource_name in connected_resources_names:
        try:
            resource = rm.open_resource(resource_name, **rm_kwargs)
        except VisaIOError:
            continue  # resource is probably used by another application, so we ignore it.
        try:
            if connection_time_delay > 0:  # For arduino initialization
                time.sleep(connection_time_delay)
            if isinstance(resource, MessageBasedResource):
                try:
                    resource.clear()
                except VisaIOError as e:  # the device does not properly implement clear
                    force_clear_message_based_resource(resource)

                idn = resource.query(r'*IDN?')

                if hasattr(resource, 'bytes_in_buffer'):
                    time.sleep(resource.query_delay)
                    # In case read value doesn't end in proper read termination
                    previous_filters = warnings.filters[:]
                    warnings.filterwarnings("ignore", category=UserWarning)
                    while resource.bytes_in_buffer > 0:
                        idn += resource.read()

                    warnings.filters = previous_filters

                if correct_read_termination:
                    resource.read_termination, idn = auto_detect_read_termination(resource, idn, True)
                resource.close()

                match_condition = (desired_idn in idn) if is_partial else (idn == desired_idn)
                if match_condition:
                    matching_idn_resource_list.append(resource)
        except VisaIOError as e:
            resource.close()
            pass  # resource/code has another issue

    return matching_idn_resource_list


def force_clear_message_based_resource(
        resource: MessageBasedResourceType,
        quick_read_timeout: float = 10,
        lock: threading.Lock = None
):
    """
    Attempt various methods to force-clear a message-based resource.

    Parameters
    ----------
    resource : MessageBasedResource
        The target message-based resource to be cleared.
    quick_read_timeout : float, optional
        The timeout for quick read operations. Defaults to 10 seconds.
    lock : threading.Lock, optional
        The threading lock to use for acquiring sole access to the resource. Defaults to None.
    """
    if lock is not None:
        lock.acquire()

    resource.flush(pyvisa.constants.BufferOperation.discard_write_buffer)
    resource.flush(pyvisa.constants.BufferOperation.discard_read_buffer)

    original_timeout = resource.timeout
    resource.timeout = quick_read_timeout  # ms

    if hasattr(resource, 'bytes_in_buffer'):
        time.sleep(resource.query_delay)
        # In case read value doesn't end in proper read termination
        previous_filters = warnings.filters[:]
        warnings.filterwarnings("ignore", category=UserWarning)
        while resource.bytes_in_buffer > 0:
            resource.read()
        warnings.filters = previous_filters
    else:
        cleared = False
        while not cleared:
            try:
                resource.read()
            except pyvisa.errors.VisaIOError:
                cleared = True

    resource.timeout = original_timeout

    if lock is not None:
        lock.release()


def auto_detect_read_termination(
        resource: MessageBasedResourceType,
        read_value: str = None,
        return_processed_read_value: bool = False
) -> str | tuple[str, str]:
    """
    This method attempts to automatically detect the read
    termination character(s) of a message-based resource.

    Parameters
    ----------
    resource : MessageBasedResource
        The target message-based resource.
    read_value : str, optional
        Find termination of a specific read value. If None, it queries the IDN of the device.
    return_processed_read_value : bool, optional
        If True, it will return the read value after attempting to strip the correct termination. Defaults to False.

    Returns
    -------
    str | tuple[str, str]
        The read termination character(s) of the resource.
        If `return_processed_read_value` is True, it will also return the processed read value.
        If the read termination detection fails, it will return an empty string.
        If the read termination succeeds, it will return the read termination character(s).
    """
    if read_value is None:
        read_value = resource.query(r'*IDN?')
        if hasattr(resource, 'bytes_in_buffer'):
            time.sleep(resource.query_delay)
            # In case read value doesn't end in proper read termination
            previous_filters = warnings.filters[:]
            warnings.filterwarnings("ignore", category=UserWarning)
            while resource.bytes_in_buffer > 0:
                read_value += resource.read()
            warnings.filters = previous_filters

    original_read_value = read_value
    read_termination = resource.read_termination
    if read_value.endswith('\n'):
        read_value = read_value[:-1]
        read_termination = '\n' if read_termination is None else '\n' + read_termination
    if read_value.endswith('\r'):
        read_value = read_value[:-1]
        read_termination = '\r' if read_termination is None else '\r' + read_termination

    def all_chars_unique(string: str) -> bool:
        return len(set(string)) == len(string)

    def found_valid_termination(term: str, value: str):
        cleaned_value = value.replace(term, '')
        return not any([char in cleaned_value for char in ['\r', '\n']])

    if not all_chars_unique(read_termination) or not found_valid_termination(read_termination, read_value):
        read_value = original_read_value
        read_termination = ''  # then the termination found is invalid!

    if return_processed_read_value:
        return read_termination, read_value
    else:
        return read_termination
