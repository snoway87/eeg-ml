class Bits():
    def __init__(self, data):
        self.data = data
        self.barray = bytearray(self.data)

    def get_ubits(self, offset, size):
        result = 0
        for i in range(size):
            result |= self.get_bit(offset + i) << i
        return result

    def get_sbits(self, offset, size):
        result = 0
        for i in range(size):
            result |= self.get_bit(offset + i) << i
        if result & ( 1 << (size - 1)) != 0:
            result = result - (1 << size)
        return result

    def get_bit(self, offset: int):
        byte_offset: int = offset // 8
        bit_offset: int = offset % 8
        result: int = self.barray[byte_offset] & (1 << bit_offset)
        return 1 if result > 0 else 0

    def set_bits(self, offset, value, size):
        for i in range(size):
            new_value = value & (1 << i)
            new_value = 1 if new_value > 0 else 0
            self.set_bit(offset + i, new_value)

    def set_bit(self, offset: int, value):
        byte_offset: int = offset // 8
        bit_offset: int = offset % 8
        if value == 0:
            self.barray[byte_offset] &= ~(1 << bit_offset)
        else:
            self.barray[byte_offset] |= (1 << bit_offset)
        self.data = bytes(self.barray)

    def get_bytes(self):
        return self.data

    def get_barray(self):
        return self.barray

    @staticmethod
    def crc16_update(data: bytearray, length):
        crc = 0xFFFF
        for i in range(0, length):
            crc ^= data[i]
            for j in range(0,8):
                if (crc & 1) > 0:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc = (crc >> 1)
        return crc & 0xFFFF

    @staticmethod
    def crc8_update(data: bytearray, length):
        crc = 0xFF
        for i in range(0, length):
            crc ^= data[i]
            for j in range(0,8):
                if(crc & 0x80) > 0:
                    crc = (crc << 1) ^ 0x31
                else:
                    crc = (crc << 1)
        return crc & 0xFF