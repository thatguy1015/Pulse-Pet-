"""
PulsePet Dobot Controller

Purpose:
- Lets PulsePet trigger optional Dobot movements from chat/voice events.
- Runs in simulation mode if the Dobot is not connected.
- Supports pydobotplus-style and pydobot-style APIs where possible.

PulsePet event mapping:
- memory_saved    -> Dobot wave
- memory_recalled -> Dobot thinking movement
- memory_cleared  -> Dobot rest/home
"""

import os
import threading
import importlib
from typing import Optional, Tuple


DOBOT_ENABLED = False
device = None
LIBRARY_KIND = None

ACTION_LOCK = threading.Lock()

# Do NOT hardcode home until you confirm a safe robot position.
# After connecting, call set_home_from_current_pose().
HOME_POSITION: Optional[Tuple[float, float, float, float]] = None


def find_dobot_port():
    """
    Attempts to find a likely Dobot serial port.

    Windows examples:
        COM3, COM4, COM5

    Mac examples:
        /dev/cu.usbserial-XXXX
        /dev/cu.SLAB_USBtoUART

    Linux examples:
        /dev/ttyUSB0
    """
    try:
        from serial.tools import list_ports

        ports = list_ports.comports()

        print("[DOBOT] Available serial ports:")

        for port in ports:
            print(
                f"  - device={port.device}, "
                f"desc={port.description}, "
                f"vid={port.vid}, "
                f"pid={port.pid}"
            )

        # Common USB serial VID values used in Dobot/pydobot examples.
        for port in ports:
            if port.vid in (4292, 6790):
                print(f"[DOBOT] Possible Dobot port found: {port.device}")
                return port.device

        return None

    except Exception as e:
        print("[DOBOT] Could not list serial ports:", e)
        return None


def connect_dobot(port=None):
    """
    Attempts to connect to Dobot.

    Test options:
        connect_dobot()
        connect_dobot("COM3")
        connect_dobot("COM4")
        connect_dobot("/dev/cu.usbserial-XXXX")

    You can also set:
        DOBOT_PORT=COM3
    """
    global DOBOT_ENABLED, device, LIBRARY_KIND

    selected_port = port or os.getenv("DOBOT_PORT")

    if selected_port:
        print(f"[DOBOT] Explicit port requested: {selected_port}")
    else:
        print("[DOBOT] No explicit port given. Trying auto-detection if supported.")

    # Attempt 1: pydobotplus
    try:
        try:
            pydobotplus_module = importlib.import_module("pydobotplus")
            DobotClass = getattr(pydobotplus_module, "Dobot")
        except Exception:
            pydobotplus_module = importlib.import_module("pydobotplus.dobot")
            DobotClass = getattr(pydobotplus_module, "Dobot")

        print("[DOBOT] Trying pydobotplus...")

        if selected_port:
            device = DobotClass(port=selected_port)
        else:
            device = DobotClass()

        LIBRARY_KIND = "pydobotplus"

        try:
            device.speed(velocity=50, acceleration=50)
            print("[DOBOT] Speed set to 50/50.")
        except Exception as speed_error:
            print("[DOBOT] Speed setup warning:", speed_error)

        DOBOT_ENABLED = True
        print("[DOBOT] Connected successfully using pydobotplus.")
        return True

    except Exception as e:
        print("[DOBOT] pydobotplus connection failed:", e)

    # Attempt 2: pydobot
    try:
        pydobot_module = importlib.import_module("pydobot")
        DobotClass = getattr(pydobot_module, "Dobot")

        print("[DOBOT] Trying pydobot...")

        if not selected_port:
            selected_port = find_dobot_port()

        if not selected_port:
            raise RuntimeError("No Dobot serial port found. Try passing COM3/COM4 explicitly.")

        try:
            device = DobotClass(port=selected_port, verbose=True)
        except TypeError:
            device = DobotClass(selected_port, verbose=True)

        LIBRARY_KIND = "pydobot"

        try:
            device.speed(velocity=50, acceleration=50)
            print("[DOBOT] Speed set to 50/50.")
        except Exception as speed_error:
            print("[DOBOT] Speed setup warning:", speed_error)

        DOBOT_ENABLED = True
        print("[DOBOT] Connected successfully using pydobot.")
        return True

    except Exception as e:
        print("[DOBOT] pydobot connection failed:", e)

    DOBOT_ENABLED = False
    device = None
    LIBRARY_KIND = None

    print("[DOBOT] Simulation mode active. No real Dobot connection.")
    return False


def get_safe_pose():
    """
    Returns current x, y, z, r.

    Supports:
    - pydobotplus-style: device.get_pose().position
    - pydobot-style: device.pose()

    Returns None if pose cannot be read.
    """
    if not DOBOT_ENABLED or not device:
        print("[DOBOT SIM] get_safe_pose called.")
        return None

    try:
        if hasattr(device, "get_pose"):
            pose = device.get_pose()
            position = pose.position
            return position.x, position.y, position.z, position.r

        if hasattr(device, "pose"):
            values = device.pose()
            x, y, z, r = values[0], values[1], values[2], values[3]
            return x, y, z, r

        print("[DOBOT] No supported pose method found.")
        return None

    except Exception as e:
        print("[DOBOT] Failed to read pose:", e)
        return None


def safe_move_to(x, y, z, r, wait=True):
    """
    Wrapper around Dobot movement.
    """
    if not DOBOT_ENABLED or not device:
        print(f"[DOBOT SIM] move_to x={x:.1f}, y={y:.1f}, z={z:.1f}, r={r:.1f}, wait={wait}")
        return

    try:
        try:
            return device.move_to(x=x, y=y, z=z, r=r, wait=wait)
        except TypeError:
            return device.move_to(x, y, z, r, wait=wait)

    except Exception as e:
        print("[DOBOT] Movement failed:", e)


def set_home_from_current_pose():
    """
    Saves current Dobot position as demo home.

    Use this after connecting and confirming the arm is in a safe visible pose.
    """
    global HOME_POSITION

    pose = get_safe_pose()

    if pose is None:
        print("[DOBOT] Cannot set home because pose could not be read.")
        return False

    HOME_POSITION = pose
    print(f"[DOBOT] Home position set to: {HOME_POSITION}")
    return True


def dobot_home():
    """
    Returns Dobot to saved demo home position.
    """
    if not DOBOT_ENABLED or not device:
        print("[DOBOT SIM] Home triggered.")
        return

    if HOME_POSITION is None:
        print("[DOBOT] Home position has not been set yet. Call set_home_from_current_pose() first.")
        return

    try:
        x, y, z, r = HOME_POSITION
        safe_move_to(x, y, z, r, wait=True)
        print("[DOBOT] Returned to home/demo position.")

    except Exception as e:
        print("[DOBOT] Home failed:", e)


def dobot_wave():
    """
    Triggered when PulsePet saves a new memory.
    Example: user says/types 'I like football'.
    """
    with ACTION_LOCK:
        if not DOBOT_ENABLED or not device:
            print("[DOBOT SIM] Wave triggered: memory_saved")
            return

        try:
            pose = get_safe_pose()

            if pose is None:
                print("[DOBOT] Wave cancelled because pose could not be read.")
                return

            x, y, z, r = pose

            # Clear readable wave: up, side, centre, side, centre, down.
            safe_move_to(x, y, z + 25, r, wait=True)
            safe_move_to(x, y + 30, z + 25, r, wait=True)
            safe_move_to(x, y, z + 25, r, wait=True)
            safe_move_to(x, y + 30, z + 25, r, wait=True)
            safe_move_to(x, y, z, r, wait=True)

            print("[DOBOT] Wave complete.")

        except Exception as e:
            print("[DOBOT] Wave failed:", e)


def dobot_think():
    """
    Triggered when PulsePet recalls memory.
    Example: user asks 'What do I like?'
    """
    with ACTION_LOCK:
        if not DOBOT_ENABLED or not device:
            print("[DOBOT SIM] Thinking movement triggered: memory_recalled")
            return

        try:
            pose = get_safe_pose()

            if pose is None:
                print("[DOBOT] Thinking cancelled because pose could not be read.")
                return

            x, y, z, r = pose

            # Small visible processing/attention movement.
            safe_move_to(x, y, z + 20, r, wait=True)
            safe_move_to(x, y + 15, z + 20, r, wait=True)
            safe_move_to(x, y, z + 20, r, wait=True)
            safe_move_to(x, y, z, r, wait=True)

            print("[DOBOT] Thinking movement complete.")

        except Exception as e:
            print("[DOBOT] Thinking movement failed:", e)


def dobot_rest():
    """
    Triggered when memory is cleared or the robot should return to neutral.
    """
    with ACTION_LOCK:
        if not DOBOT_ENABLED or not device:
            print("[DOBOT SIM] Rest triggered.")
            return

        try:
            if HOME_POSITION is not None:
                dobot_home()
                return

            pose = get_safe_pose()

            if pose is None:
                print("[DOBOT] Rest cancelled because pose could not be read.")
                return

            x, y, z, r = pose
            safe_move_to(x, y, z + 15, r, wait=True)

            print("[DOBOT] Rest complete.")

        except Exception as e:
            print("[DOBOT] Rest failed:", e)


def trigger_event(event_type):
    """
    Main function PulsePet calls.

    event_type comes from Flask:
    - memory_saved
    - memory_recalled
    - memory_cleared
    - general_reply
    """
    if event_type == "memory_saved":
        dobot_wave()

    elif event_type == "memory_recalled":
        dobot_think()

    elif event_type == "memory_cleared":
        dobot_rest()

    elif event_type == "dobot_home":
        dobot_home()

    else:
        print(f"[DOBOT] No movement for event: {event_type}")


def close_dobot():
    """
    Safely closes Dobot connection.
    """
    global DOBOT_ENABLED, device, LIBRARY_KIND

    if device:
        try:
            device.close()
        except Exception as e:
            print("[DOBOT] Close warning:", e)

    device = None
    LIBRARY_KIND = None
    DOBOT_ENABLED = False

    print("[DOBOT] Closed.")


def status():
    """
    Returns simple status info for Flask/debugging.
    """
    return {
        "dobot_enabled": DOBOT_ENABLED,
        "library_kind": LIBRARY_KIND,
        "home_position": HOME_POSITION,
        "pose": get_safe_pose()
    }


if __name__ == "__main__":
    print("PulsePet Dobot Controller Test")
    print("--------------------------------")

    port_input = input("Enter Dobot port, or press Enter for auto-detect/simulation: ").strip()
    port_input = port_input if port_input else None

    connected = connect_dobot(port_input)

    print("Connected:", connected)
    print("Status:", status())

    if connected:
        set_home_from_current_pose()

    while True:
        print("\nChoose action:")
        print("1 = wave / memory_saved")
        print("2 = think / memory_recalled")
        print("3 = rest")
        print("4 = home")
        print("5 = print pose/status")
        print("q = quit")

        choice = input("> ").strip().lower()

        if choice == "1":
            dobot_wave()

        elif choice == "2":
            dobot_think()

        elif choice == "3":
            dobot_rest()

        elif choice == "4":
            dobot_home()

        elif choice == "5":
            print("Status:", status())

        elif choice == "q":
            close_dobot()
            break

        else:
            print("Unknown option.")