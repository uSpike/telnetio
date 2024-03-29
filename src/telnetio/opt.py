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
TM = 6  # timing mark
RCTE = 7  # remote controlled transmission and echo
NAOL = 8  # negotiate about output line width
NAOP = 9  # negotiate about output page size
NAOCRD = 10  # negotiate about CR disposition
NAOHTS = 11  # negotiate about horizontal tabstops
NAOHTD = 12  # negotiate about horizontal tab disposition
NAOFFD = 13  # negotiate about formfeed disposition
NAOVTS = 14  # negotiate about vertical tab stops
NAOVTD = 15  # negotiate about vertical tab disposition
NAOLFD = 16  # negotiate about output LF disposition
XASCII = 17  # extended ascii character set
LOGOUT = 18  # force logout
BM = 19  # byte macro
DET = 20  # data entry terminal
SUPDUP = 21  # supdup protocol
SUPDUPOUTPUT = 22  # supdup output
SNDLOC = 23  # send location
TTYPE = 24  # terminal type
EOR = 25  # end or record
TUID = 26  # TACACS user identification
OUTMRK = 27  # output marking
TTYLOC = 28  # terminal location number
VT3270REGIME = 29  # 3270 regime
X3PAD = 30  # X.3 PAD
NAWS = 31  # window size
TSPEED = 32  # terminal speed
LFLOW = 33  # remote flow control
LINEMODE = 34  # Linemode option
XDISPLOC = 35  # X Display Location
OLD_ENVIRON = 36  # Old - Environment variables
AUTHENTICATION = 37  # Authenticate
ENCRYPT = 38  # Encryption option
NEW_ENVIRON = 39  # New - Environment variables
# the following ones come from
# http://www.iana.org/assignments/telnet-options
# Unfortunately, that document does not assign identifiers
# to all of them, so we are making them up
TN3270E = 40  # TN3270E
XAUTH = 41  # XAUTH
CHARSET = 42  # CHARSET
RSP = 43  # Telnet Remote Serial Port
COM_PORT_OPTION = 44  # Com Port Control Option
SUPPRESS_LOCAL_ECHO = 45  # Telnet Suppress Local Echo
TLS = 46  # Telnet Start TLS
KERMIT = 47  # KERMIT
SEND_URL = 48  # SEND-URL
FORWARD_X = 49  # FORWARD_X
PRAGMA_LOGON = 138  # TELOPT PRAGMA LOGON
SSPI_LOGON = 139  # TELOPT SSPI LOGON
PRAGMA_HEARTBEAT = 140  # TELOPT PRAGMA HEARTBEAT
