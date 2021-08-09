from enum import Enum


class Opt(int, Enum):
    IAC = 255  # "Interpret As Command"
    DONT = 254
    DO = 253
    WONT = 252
    WILL = 251
    NULL = 0

    SE = 240  # Subnegotiation End
    NOP = 241  # No Operation
    DM = 242  # Data Mark
    BRK = 243  # Break
    IP = 244  # Interrupt process
    AO = 245  # Abort output
    AYT = 246  # Are You There
    EC = 247  # Erase Character
    EL = 248  # Erase Line
    GA = 249  # Go Ahead
    SB = 250  # Subnegotiation Begin

    BINARY = 0  # 8-bit data path
    ECHO = 1  # echo
    RCP = 2  # prepare to reconnect
    SGA = 3  # suppress go ahead
    NAMS = 4  # approximate message size
    STATUS = 5  # give status

    LINEMODE = 34
