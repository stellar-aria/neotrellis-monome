from queue import Queue
from typing import Optional
from usb_cdc import Serial, data


class MonomeGridEvent:
    def __init__(self, x: int, y: int, pressed: bool):
        self.x = x
        self.y = y
        self.pressed = pressed


class MonomeArcTurnEvent:
    def __init__(self, index: int, delta: int):
        self.index = index
        self.delta = delta


class MonomeArcPressEvent:
    def __init__(self, index: int, pressed: bool):
        self.index = index
        self.pressed = pressed


class MonomeEventQueue:
    """Originally implemented as a circular buffer, here an idiomatic FIFO queue"""

    def __init__(self):
        self._grid_events = Queue()
        self._arc_events = Queue()

    def add_grid_event(self, x: int, y: int, pressed: bool):
        self._grid_events.put(MonomeGridEvent(x, y, pressed))

    def grid_event_available(self) -> bool:
        return not self._grid_events.empty()

    def read_grid_event(self) -> Optional[MonomeGridEvent]:
        if self._grid_events.empty():
            return None
        return self._grid_events.get()

    def add_arc_turn_event(self, index: int, delta: int):
        self._arc_events.put(MonomeArcTurnEvent(index, delta))

    def add_arc_press_event(self, index: int, pressed: bool):
        self._arc_events.put(MonomeArcPressEvent(index, pressed))

    def arc_event_available(self) -> bool:
        return not self._arc_events.empty()

    def read_arc_event(self) -> Optional[MonomeArcPressEvent | MonomeArcTurnEvent]:
        if self._arc_events.empty():
            return None
        return self._arc_events.get()

    def send_arc_delta(self, index: int, delta: int):
        Serial.write(data, [0x50, index, delta])

    def send_arc_key(self, index: int, pressed: bool):
        Serial.write(data, [0x52 if pressed else 0x51, index])

    def send_grid_key(self, x: int, y: int, pressed: bool):
        Serial.write(data, [0x21 if pressed else 0x20, x, y])


class MonomeSerialDevice(MonomeEventQueue):
    vari_mono_thresh = 0

    def __init__(
        self,
        active: bool = False,
        is_monome: bool = False,
        is_grid: bool = False,
        rows: int = 0,
        cols: int = 0,
        encoders: int = 0,
    ):
        super().__init__()
        self.active = active
        self.is_monome = is_monome
        self.is_grid = is_grid
        self._rows = rows
        self._cols = cols
        self._encoders = encoders
        self.set_all_grid_leds(0)
        self._arc_dirty = False
        self._grid_dirty = False

        self.leds = []
        self.device_id = ""
        self.brightness = 15

    @classmethod
    def as_grid(cls, rows: int, cols: int):
        self = cls(True, True, True, rows, cols)
        self._grid_dirty = True
        return self

    def get_device_info(self):
        """pattern: /sys/query
        desc: request device information"""
        Serial.write(data, b"\x00")

    def poll(self):
        if Serial.connected:
            self.process_serial()

    def set_all_grid_leds(self, value: int):
        for y in range(self._rows):
            for x in range(self._cols):
                self.leds[y][x] = value

    def set_grid_led(self, x: int, y: int, level: int):
        self.leds[y][x] = level

    def clear_grid_led(self, x: int, y: int):
        self.set_grid_led(x, y, 0)

    def set_arc_led(self, ring: int, led: int, level: int):
        self.leds[ring][led] = level

    def clear_arc_led(self, ring: int, led: int):
        self.set_arc_led(ring, led, 0)

    def clear_arc_ring(self, ring: int):
        self.leds[ring] = [0 for led in self.leds[ring]]

    def set_all_arc_leds(self, ring: int, value: int):
        for n in range(64):
            self.leds[ring][n] = 0

    def refresh_grid(self):
        self._grid_dirty = True

    def refresh_arc(self):
        self._arc_dirty = True

    def process_serial(self):
        identifierSent: bytes  # command byte sent from controller to matrix
        intensity: int = 15
        gridKeyX: int = 0
        gridKeyY: int = 0
        delta: int = 0
        gridX: int = self._cols  # Will be either 8 or 16
        gridY: int = self._rows
        num_quads: int = int(self._cols / self._rows)

        # get command identifier: first byte of packet is identifier in the form: [(a << 4) + b]
        # a = section (ie. system, key-grid, digital, encoder, led grid, tilt)
        # b = command (ie. query, enable, led, key, frame)

        identifierSent = Serial.read(data)
        match identifierSent:
            case b"\x00":  # /sys/query s n
                # serial: [0x00, s, n]
                output = bytes(
                    [0x00, 0x01, num_quads, 0x00, 0x02, num_quads]  # led-grid
                )  # key-grid
                Serial.write(data, output)

            case b"\x01":  # sys/id s[64]
                # serial: [0x01, s[64]]
                output = bytes([0x01])
                bytestring = bytes(self.device_id, "utf-8")
                # TODO: double check the 32 requirement, monome serial docs say 64
                bytestring += b"\0" * (32 - len(bytestring))  # has to be 32
                Serial.write(data, output + bytestring)

            case b"\x02":  # system / write ID
                self.device_id = Serial.read(data, 32).decode("utf-8")

            case b"\x03":  # system / request grid offset
                # system / report grid offset
                # serial: [0x02, n, x, y]
                Serial.write(data, bytes([0x02, 0x01, 0, 0]))

            case b"\x04":  # system / set grid offset
                # serial: [0x04, n, x, y] (read)
                [grid_num, read_x, read_y] = Serial.read(data, 3)

            case b"\x05":  # system / request grid size
                # system / report grid size
                # serial: [0x03, x, y]
                Serial.write(data, bytes([0x03, gridX, gridY]))

            case b"\x06":  # system / set grid size
                # serial: [0x06, x, y] (read)
                [read_x, read_y] = Serial.read(data, 2)

            # case b'\x07': # system / get ADDRs (scan)

            case b"\x08":  # system / set ADDR
                # serial: [0x08, a, b]
                old_address = Serial.read(data)
                new_address = Serial.read(data)
                # TODO: figure out how to actually do this?

            case b"\x0F":  # system / query firmware version
                # serial: [0x0F, v[8]]
                version_string = ""
                bytestring = bytes(version_string, "utf-8")
                bytestring += b"\0" * (8 - len(bytestring))  # has to be 8
                Serial.write(data, bytestring)

            case b"\x10":  # led-grid / led off
                [read_x, read_y] = Serial.read(data, 2)
                self.clear_grid_led(read_x, read_y)

            case b"\x11":  # led-grid / led on
                [read_x, read_y] = Serial.read(data, 2)
                self.set_grid_led(read_x, read_y, self.brightness)

            case b"\x12":  # led-grid / all off
                self.set_all_grid_leds(0)

            case b"\x13":  # led-grid / all on
                self.set_all_grid_leds(self.brightness)

            case b"\x14":  # led-grid / map (frame)
                [read_x, read_y] = Serial.read(data, 2)
                # TODO: Deal with negative numbers
                read_x &= 0xF8
                read_y &= 0xF8
                for y in range(8):
                    intensity = int(Serial.read(data))
                    for x in range(8):
                        if (intensity >> x) & 0x01:
                            self.set_grid_led(read_x + x, read_y + y, self.brightness)
                        else:
                            self.clear_grid_led(read_x + x, read_y + y)

            case b"\x15":  # led-grid / row
                [read_x, read_y, intensity] = Serial.read(data, 3)
                # TODO: Deal with negative numbers
                read_x &= 0xF8
                for x in range(8):
                    if (int(intensity) >> x) & 0x1:
                        self.set_grid_led(read_x + x, read_y, 15)
                    else:
                        self.clear_grid_led(read_x + x, read_y)

            case b"\x16":  # led-grid / col
                [read_x, read_y, intensity] = Serial.read(data, 3)
                # TODO: Deal with negative numbers
                read_y &= 0xF8
                for y in range(8):
                    if (int(intensity) >> y) & 0x1:
                        self.set_grid_led(read_x, read_y + y, 15)
                    else:
                        self.clear_grid_led(read_x, read_y + y)

            case b"\x17":  # led-grid / intensity
                self.brightness = int(Serial.read(data))

            case b"\x18":
                [read_x, read_y, intensity] = Serial.read(data, 3)
                self.set_grid_led(read_x, read_y, intensity)

            case b"\x19":
                intensity = int(Serial.read(data))
                self.set_all_grid_leds(intensity)

            case b"\x1A":
                [read_x, read_y] = Serial.read(data, 3)
                # TODO: Deal with negative numbers
                read_x &= 0xF8
                read_y &= 0xF8

                z = 0
                for y in range(8):
                    for x in range(8):
                        if z % 2 == 0:
                            intensity = int(Serial.read(data))
                            value = (intensity >> 4) & 0x0F
                            self.set_grid_led(
                                read_x + x,
                                read_y + y,
                                value if value > self.vari_mono_thresh else 0,
                            )
                        else:
                            value = intensity & 0x0F
                            self.set_grid_led(
                                read_x + x,
                                read_y + y,
                                value if value > self.vari_mono_thresh else 0,
                            )
                        z += 1

            case b"\x1B":
                [read_x, read_y] = Serial.read(data, 3)
                # TODO: Deal with negative numbers
                read_x &= 0xF8
                read_y &= 0xF8

                for x in range(8):
                    if x % 2 == 0:
                        intensity = int(Serial.read(data))
                        value = (intensity >> 4) & 0x0F
                        self.set_grid_led(
                            read_x + x,
                            read_y,
                            value if value > self.vari_mono_thresh else 0,
                        )
                    else:
                        value = intensity & 0x0F
                        self.set_grid_led(
                            read_x + x,
                            read_y,
                            value if value > self.vari_mono_thresh else 0,
                        )

            case b"\x1C":
                [read_x, read_y] = Serial.read(data, 3)
                # TODO: Deal with negative numbers
                read_x &= 0xF8
                read_y &= 0xF8

                for y in range(8):
                    if y % 2 == 0:
                        intensity = int(Serial.read(data))
                        value = (intensity >> 4) & 0x0F
                        self.set_grid_led(
                            read_x,
                            read_y + y,
                            value if value > self.vari_mono_thresh else 0,
                        )
                    else:
                        value = intensity & 0x0F
                        self.set_grid_led(
                            read_x,
                            read_y + y,
                            value if value > self.vari_mono_thresh else 0,
                        )

            case b"\x20":
                [grid_key_x, grid_key_y] = Serial.read(data, 2)
                self.add_grid_event(grid_key_x, grid_key_y, False)

            case b"\x21":
                [grid_key_x, grid_key_y] = Serial.read(data, 2)
                self.add_grid_event(grid_key_x, grid_key_y, True)

            case b"\x50":
                [index, delta] = Serial.read(data, 2)
                self.add_arc_turn_event(index, delta)

            case b"\x51":
                [index] = Serial.read(data)
                self.add_arc_press_event(index, False)

            case b"\x52":
                [index] = Serial.read(data)
                self.add_arc_press_event(index, True)

            case b"\x80":
                """tilt - active response [0x01, d]"""

            case b"\x81":
                """tilt - 8 bytes [0x80, n, xh, xl, yh, yl, zh, zl]"""

            case b"\x90":
                [read_n, read_x, read_a] = Serial.read(data, 3)
                self.set_arc_led(read_n, read_x, read_a)

            case b"\x91":
                [read_n, read_a] = Serial.read(data, 2)
                self.set_all_arc_leds(read_n, read_a)

            case b"\x92":
                read_n = int(Serial.read(data))
                for y in range(64):
                    if y % 2 == 0:
                        intensity = int(Serial.read(data))
                        value = intensity >> 4 & 0x0F
                        self.set_arc_led(
                            read_n, y, value if value > self.vari_mono_thresh else 0
                        )
                    else:
                        value = intensity & 0x0F
                        self.set_arc_led(
                            read_n, y, value if value > self.vari_mono_thresh else 0
                        )

            case b"\x93":
                [read_n, read_x, read_y, read_a] = Serial.read(data, 4)
                if read_x < read_y:
                    for y in range(read_x, read_y):
                        self.set_arc_led(read_n, y, read_a)
                else:
                    for y in range(read_x, 64):
                        self.set_arc_led(read_n, y, read_a)
                    for x in range(0, read_y):
                        self.set_arc_led(read_n, x, read_a)
