#!/usr/bin/env python

import sys

if sys.version_info[0] < 3 :
    from Tkinter import *
else :
    from tkinter import *

import collections
import time
import bluetooth
import subprocess
import os

import RPi.GPIO as GPIO
import smtplib
from email.mime.multipart import MIMEMultipart
from datetime import date

import AlphaNum4


_traceyNewDay = 0
_markNewDay = 0
_triggerTimeout = 0
_blnStartWeighing = False

# ============================================================================
# Define some constants and a means to access them
# ============================================================================
def constant(f):
    def fset(self, value):
        raise TypeError
    def fget(self):
        return f()
    return property(fget, fset)


class _Const(object):

    @constant
    def RELAY_WII():
        return 17

    @constant
    def RELAY_WII_PWR():
        return 12

    @constant
    def RELAY_SPKR():
        return 26

    @constant
    def BUTTON_MARK():
        return 13

    @constant
    def BUTTON_TRACEY():
        return 6

    @constant
    def USER_NONE():
        return 0

    @constant
    def USER_TRACEY():
        return 1

    @constant
    def USER_MARK():
        return 2

CONST = _Const()

_user = CONST.USER_NONE


def buttonMARK(channel) :

    global _user
    global _triggerTimeout

    if _user == CONST.USER_NONE :
        _user = CONST.USER_MARK
        print("Mark")
        # 1/2 sec increments
        _triggerTimeout = 120


def buttonTRACEY(channel) :

    global _user
    global _triggerTimeout

    if _user == CONST.USER_NONE :
        _user = CONST.USER_TRACEY
        print("Tracey")
        # 1/2 sec increments
        _triggerTimeout = 120


# ============================================================================
# Center the current window on the screen
# ============================================================================
def center(win) :
    """
    centers a tkinter window
    :param win: the root or Toplevel window to center
    """
    win.update_idletasks()
    width = win.winfo_width()
    frm_width = win.winfo_rootx() - win.winfo_x()
    win_width = width + 2 * frm_width
    height = win.winfo_height()
    titlebar_height = win.winfo_rooty() - win.winfo_y()
    win_height = height + titlebar_height + frm_width
    x = win.winfo_screenwidth() // 2 - win_width // 2
    y = win.winfo_screenheight() // 2 - win_height // 2
    win.geometry('{}x{}+{}+{}'.format(width, height, x, y))
    win.deiconify()


# ============================================================================
# Show the current weight on the backpack i2c 4 digit alphanumeric display
# ============================================================================
def displayWeight(weight, inKg):

    if inKg == True :
        deci = int(weight)
        frac = int((weight % 1) * 100)
    else :
        deci = int(weight / 14)
        frac = int(weight % 14)

    str1 = str(deci)
    str2 = str(frac)
    if len(str1) == 1 :
        str1 = "0" + str1
    if len(str2) == 1 :
        str2 = "0" + str2
    str3 = str1 + str2

    display.clear()
    display.print_str(str3)
    # Fixed decimal point position
    display.set_decimal(1, True)
    display.write_display()


# ============================================================================
# Display a string on the backp[ack i2c display
# ============================================================================
def displayString(strV) :

    display.clear()
    display.print_str(strV)
    # Make sure decimal point is off
    display.set_decimal(1, False)
    display.write_display()


# ============================================================================
# Display a moving decimal point on the display while obtaining readings
# ============================================================================
def displayWorking() :

    display.clear()
    display.set_decimal(displayWorking.Count, True)
    display.write_display()
    displayWorking.Count += 1
    if displayWorking.Count == 4 :
       displayWorking.Count = 0

# ============================================================================
# Display a flashing dp to show we are still working
# ============================================================================
def displaySleepMode() :

    displaySleepMode.Count += 1
    if displaySleepMode.Count >= 10 :
        displaySleepMode.Count = 0
        display.clear()
        display.set_decimal(0, True)
        display.write_display()
        time.sleep(.05)
        display.set_decimal(0, False)
        display.write_display()


# ============================================================================
# Check if we have rolled over midnight
# ============================================================================
def checkForNewDay() :

    global _traceyNewDay
    global _markNewDay

    # 'today' will be 0 Mon to 6 Sun
    today = date.today()
    if today.weekday() != checkForNewDay.thisDay :	
        checkForNewDay.thisDay = today.weekday()
        _markNewDay = 0
        _traceyNewDay = 0
    root.after(600000, checkForNewDay)


# ============================================================================
# Send an email with the latest weight
# ============================================================================
def sendEmail(strMessage):
    
    global _user

    # NOTE: email doesn't like /r in the subject field...

    try :

        server=smtplib.SMTP('smtp.office365.com', 587)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login("sendfromemail", "sendfrompwd")
        msg = MIMEMultipart()
        msg['Subject'] = "WEIGHT : " + strMessage
        msg['From'] = "sendfromemail"
        msg.preamble = "WEIGHT : " + strMessage

        if _user == CONST.USER_TRACEY :
            msg['To'] = "sendtoemail"
            server.sendmail("sendfromemail", "sendtoemail", msg.as_string())
        else :
            msg['To'] = "sendtoemail"
            server.sendmail("sendfromemail", "sendtoemail", msg.as_string())
        server.quit()

    except :

        pass


# --------- User Settings ---------
WEIGHT_SAMPLES = 150
# ---------------------------------

_events = range(WEIGHT_SAMPLES)

# Wiiboard Parameters
CONTINUOUS_REPORTING = "04"  # Easier as string with leading zero
COMMAND_LIGHT = 11
COMMAND_REPORTING = 12
COMMAND_REQUEST_STATUS = 15
COMMAND_REGISTER = 16
COMMAND_READ_REGISTER = 17
INPUT_STATUS = 20
INPUT_READ_DATA = 21
EXTENSION_8BYTES = 32
BUTTON_DOWN_MASK = 8
TOP_RIGHT = 0
BOTTOM_RIGHT = 1
TOP_LEFT = 2
BOTTOM_LEFT = 3
BLUETOOTH_NAME = "Nintendo RVL-WBC-01"

class EventProcessor:
    
    def __init__(self):

        self.done = False
        self._measureCnt = 0
        self._working = False
        self._myCount = 0

    def resetw(self) :

        self.done = False
        self._measureCnt = 0
        self._working = False
        self._myCount = 0

    def mass(self, event):
        global _traceyNewDay
        global _markNewDay
        global _user
        global _triggerTimeout
        global _blnStartWeighing

        if event.totalWeight > 20.0 :

            # Someone has stepped on...
            _triggerTimeout = 0

            if _blnStartWeighing == True :
                _blnStartWeighing = False
                labelS.configure(text="WORKING")
                root.update()
                speakMe("working", 1)
                self._myCount = 0
                self._working = True
                self._measureCnt = 0
                for x in range(0, WEIGHT_SAMPLES - 1):
                    _events[x] = 0.0

                print("==================New======================")

            self._myCount += 1
            if self._working == True :
                if self._myCount % 4 == 0 :
                    displayWorking()

            print("{:3d}".format(self._measureCnt) + "    {:3d}".format(self._myCount) + "    {:2.2f}".format(event.totalWeight))

            if self._working == True :
                # Ignore first 50 readings as they may be unstable
                if self._myCount > 50 :
                    if self._measureCnt < WEIGHT_SAMPLES :
                        _events[self._measureCnt] = event.totalWeight #Kg
                        self._measureCnt += 1

            if self._working == True and self._measureCnt == WEIGHT_SAMPLES:
                # Stop us reading any further messages from the Wii board
                self._working = False
 
                self._sum = 0
                for x in range(0, WEIGHT_SAMPLES-1):
                    self._sum += _events[x]
                self._weight = self._sum/WEIGHT_SAMPLES

                # There appears to be a fixed offset on my Wii Fit board (of 7.3Kg)
                self._weight -= 7.3

                s_lb = self._weight * 2.20462
                # Set a duff value so we know if there is no user...
                bmi = 0
                if _user == CONST.USER_TRACEY :
                    bmi = (s_lb / (64 * 64) ) * 703 
                if _user == CONST.USER_MARK :
                    bmi = (s_lb / (71 * 71) ) * 703 

                #print str(s_lb) + " lb"
                #print str(self._weight) + " kg"
                #print str(int(s_lb / 14)) + " st " + str(int(s_lb % 14)) + " lb"
                
                oz = (s_lb % 1) * 16
                w = str(int(s_lb / 14)) + "st " + str(int(s_lb % 14)) + "lb " + "{:2.0f}".format(oz) + "oz\r" + "{:2.2f}".format(self._weight) + "kg\r" + "BMI = {:2.1f}".format(bmi)
                w_email = str(int(s_lb / 14)) + "st " + str(int(s_lb % 14)) + "lb " + "{:2.0f}".format(oz) + "oz " + "{:2.2f}".format(self._weight) + "kg " + "BMI = {:2.1f}".format(bmi)
                w_speak = str(int(s_lb / 14)) + " stones " + str(int(s_lb % 14)) + " pounds and " + "{:2.0f}".format(oz) + " ounces "
                if bmi >= 25 :
                    w += " (overweight) "
                    w_email += " (overweight)"
                    w_speak += " (overweight)"
                elif bmi < 19 :
                    w += " (underweight) "
                    w_email += " (underweight)"
                    w_speak += " (underweight)"
                else :
                    w += " (normal)     "
                    w_email += " (normal)"
                    w_speak += " (normal)"

                labelW.configure(text = w)
                root.update()
                displayWeight(self._weight, True)
                speakMe(w_speak, 10)

                if _traceyNewDay == 0 and _user == CONST.USER_TRACEY :
                    _traceyNewDay = 1
                    sendEmail(w_email)
                    fileobj = open("WiiDataTracey.txt", 'a')
                    d = date.today()
                    fileobj.write(d.isoformat() + "," + str(self._weight) + "," + str(s_lb) + "," + str(bmi) + "\r")               
                    fileobj.close()        

                if _markNewDay == 0 and _user == CONST.USER_MARK :
                    _markNewDay = 1
                    sendEmail(w_email)
                    fileobj = open("WiiDataMark.txt", 'a')
                    d = date.today()
                    fileobj.write(d.isoformat() + "," + str(self._weight) + "," + str(s_lb) + "," + str(bmi) + "\r")               
                    fileobj.close()        

                labelS.configure(text="WEIGHING COMPLETE")
                root.update()
                _user = CONST.USER_NONE
                self._myCount = 0
                self._measureCnt = 0


    @property
    def weight(self):
        if not _events:
            return 0
        histogram = collections.Counter(round(num, 1) for num in _events)
        return histogram.most_common(1)[0][0]


class BoardEvent:
    def __init__(self, topLeft, topRight, bottomLeft, bottomRight, buttonPressed, buttonReleased):

        self.topLeft = topLeft
        self.topRight = topRight
        self.bottomLeft = bottomLeft
        self.bottomRight = bottomRight
        self.buttonPressed = buttonPressed
        self.buttonReleased = buttonReleased
        #convenience value
        self.totalWeight = topLeft + topRight + bottomLeft + bottomRight
        #if self.totalWeight > 10 :
            #print str(topLeft) + "  " + str(topRight) + "  " + str(bottomLeft) + "  " + str(bottomRight)

class Wiiboard:
    def __init__(self, _processor):
        # Sockets and status
        self.receivesocket = None
        self.controlsocket = None

        self.processor = _processor
        self.calibration = []
        self.calibrationRequested = False
        self.LED = False
        self.address = None
        self.buttonDown = False

        for i in range(3):
            self.calibration.append([])
            for j in range(4):
                self.calibration[i].append(10000)  # high dummy value so events with it don't register

        self.status = "Disconnected"
        self.lastEvent = BoardEvent(0, 0, 0, 0, False, False)

        try:
            self.receivesocket = bluetooth.BluetoothSocket(bluetooth.L2CAP)
            self.controlsocket = bluetooth.BluetoothSocket(bluetooth.L2CAP)
        except ValueError:
            raise Exception("Error: Bluetooth not found")

    def isConnected(self):
        return self.status == "Connected"

    # Connect to the Wiiboard at bluetooth address <address>
    def connect(self, address):

        if address is None:
            print ("Non existent address")
            return 0 
        self.receivesocket.connect((address, 0x13))
        self.controlsocket.connect((address, 0x11))
        if self.receivesocket and self.controlsocket:
            print ("Connected to Wiiboard at address {0}".format(address))
            self.status = "Connected"
            self.address = address
            self.calibrate()
            useExt = ["00", COMMAND_REGISTER, "04", "A4", "00", "40", "00"]
            self.send(useExt)
            self.setReportingType()
            #print "Wiiboard connected"
            return 1
        else:
            print ("Could not connect to Wiiboard at address {0}".format(address))
            return 0

    def receive(self):
        if self.status == "Connected": #and not self.processor.done:
            data = self.receivesocket.recv(25)
            intype = int(data.encode("hex")[2:4])
            if intype == INPUT_STATUS:
                # TODO: Status input received. It just tells us battery life really
                self.setReportingType()
                print ("Battery Life?")
            elif intype == INPUT_READ_DATA:
                if self.calibrationRequested:
                    print ("Self cal requested")
                    packetLength = (int(str(data[4]).encode("hex"), 16) / 16 + 1)
                    self.parseCalibrationResponse(data[7:(7 + packetLength)])

                    if packetLength < 16:
                        print ("Self cal false")
                        self.calibrationRequested = False
            elif intype == EXTENSION_8BYTES:
                #print "Extension 8 bytes"
                self.processor.mass(self.createBoardEvent(data[2:12]))
            else:
                print ("ACK to data write received")

    def disconnect(self):
        if self.status == "Connected":
            self.status = "Disconnecting"
            #while self.status == "Disconnecting":
                #self.wait(100)
        try:
            self.receivesocket.close()
        except:
            print ("Unable to close rx socket")
            pass
        try:
            self.controlsocket.close()
        except:
            print ("Unable to close control socket")
            pass
        print ("WiiBoard disconnected")

    # Try to discover a Wiiboard
    def discover(self):
        print ("Press the red sync button on the board now")

        GPIO.output(CONST.RELAY_WII, 0)
        time.sleep(0.25)
        GPIO.output(CONST.RELAY_WII, 1)

        address = None
        bluetoothdevices = bluetooth.discover_devices(duration=6, lookup_names=True)
        for bluetoothdevice in bluetoothdevices:
            if bluetoothdevice[1] == BLUETOOTH_NAME:
                address = bluetoothdevice[0]
                print ("Found Wiiboard at address {0}".format(address))
        if address is None:
            print ("No Wiiboards discovered.")
        return address

    def createBoardEvent(self, bytes):
        buttonBytes = bytes[0:2]
        bytes = bytes[2:12]
        buttonPressed = False
        buttonReleased = False

        state = (int(buttonBytes[0].encode("hex"), 16) << 8) | int(buttonBytes[1].encode("hex"), 16)
        if state == BUTTON_DOWN_MASK:
            buttonPressed = True
            if not self.buttonDown:
                print ("Button pressed")
                self.buttonDown = True

        if not buttonPressed:
            if self.lastEvent.buttonPressed:
                buttonReleased = True
                self.buttonDown = False
                print ("Button released")

        rawTR = (int(bytes[0].encode("hex"), 16) << 8) + int(bytes[1].encode("hex"), 16)
        rawBR = (int(bytes[2].encode("hex"), 16) << 8) + int(bytes[3].encode("hex"), 16)
        rawTL = (int(bytes[4].encode("hex"), 16) << 8) + int(bytes[5].encode("hex"), 16)
        rawBL = (int(bytes[6].encode("hex"), 16) << 8) + int(bytes[7].encode("hex"), 16)

        #print str(rawTR) + "  " + str(rawBR) + "  " + str(rawTL) + "  " + str(rawBL)

        topLeft = self.calcMass(rawTL, TOP_LEFT)
        topRight = self.calcMass(rawTR, TOP_RIGHT)
        bottomLeft = self.calcMass(rawBL, BOTTOM_LEFT)
        bottomRight = self.calcMass(rawBR, BOTTOM_RIGHT)

        #print str(topRight) + "  " + str(bottomRight) + "  " + str(topLeft) + "  " + str(bottomLeft)

        boardEvent = BoardEvent(topLeft, topRight, bottomLeft, bottomRight, buttonPressed, buttonReleased)
        return boardEvent

    def calcMass(self, raw, pos):
        val = 0.0
        #calibration[0] is calibration values for 0kg
        #calibration[1] is calibration values for 17kg
        #calibration[2] is calibration values for 34kg
        if raw < self.calibration[0][pos]:
            return val
        elif raw < self.calibration[1][pos]:
            val = ((raw - self.calibration[0][pos]) * 17) / float(self.calibration[1][pos] - self.calibration[0][pos])
            #val = 17 * ((raw - self.calibration[0][pos]) / float((self.calibration[1][pos] - self.calibration[0][pos])))
        elif raw > self.calibration[1][pos]:
            val = 17 + ( (raw - self.calibration[1][pos]) * 17 ) / float(self.calibration[2][pos] - self.calibration[1][pos])
            #val = 17 + 17 * ((raw - self.calibration[1][pos]) / float((self.calibration[2][pos] - self.calibration[1][pos])))

        return val

    def getEvent(self):
        return self.lastEvent

    def getLED(self):
        return self.LED

    def parseCalibrationResponse(self, bytes):
        index = 0

        #print "Calibration " + str(len(bytes))

        if len(bytes) == 16:
            for i in xrange(2):
                for j in xrange(4):
                    self.calibration[i][j] = (int(bytes[index].encode("hex"), 16) << 8) + int(bytes[index + 1].encode("hex"), 16)
                    #print str(self.calibration[i][j])
                    index += 2
        elif len(bytes) < 16:
            for i in xrange(4):
                self.calibration[2][i] = (int(bytes[index].encode("hex"), 16) << 8) + int(bytes[index + 1].encode("hex"), 16)
                #print str(self.calibration[2][i])
                index += 2

            #print "Calibration 0Kg"
            #print self.calibration[0][0]
            #print self.calibration[0][1]
            #print self.calibration[0][2]
            #print self.calibration[0][3]

            #print "Calibration 17Kg"
            #print self.calibration[1][0]
            #print self.calibration[1][1]
            #print self.calibration[1][2]
            #print self.calibration[1][3]

            #print "Calibration 34Kg"
            #print self.calibration[2][0]
            #print self.calibration[2][1]
            #print self.calibration[2][2]
            #print self.calibration[2][3]

    # Send <data> to the Wiiboard
    # <data> should be an array of strings, each string representing a single hex byte
    def send(self, data):
        if self.status != "Connected":
            return
        data[0] = "52"

        senddata = ""
        for byte in data:
            byte = str(byte)
            senddata += byte.decode("hex")

        self.controlsocket.send(senddata)

    #Turns the power button LED on if light is True, off if False
    #The board must be connected in order to set the light
    def setLight(self, light):
        if light:
            val = "10"
        else:
            val = "00"

        message = ["00", COMMAND_LIGHT, val]
        self.send(message)
        self.LED = light

    def calibrate(self):
        message = ["00", COMMAND_READ_REGISTER, "04", "A4", "00", "24", "00", "18"]
        self.send(message)
        self.calibrationRequested = True

    def setReportingType(self):
        bytearr = ["00", COMMAND_REPORTING, CONTINUOUS_REPORTING, EXTENSION_8BYTES]
        self.send(bytearr)

    def wait(self, millis):
        time.sleep(millis / 1000.0)

def getWiiInfo():
    if _user != CONST.USER_NONE :   
        board.receive()
        root.after(50, getWiiInfo)


def stopProg(e):
    GPIO.cleanup()
    display.clear()
    display.write_display()
    root.destroy()


def speakMe(text, gap):

    # Connect the speaker now we want sound
    GPIO.output(CONST.RELAY_SPKR, 0)

    dquote = '"'
    squote = "'"
    # -g is gap between words in 10ms increments (so 10 is 100mS) I think!
    # -s is speed of speech 175 is default lower is slower 
    # -a is amplitude 200 is max (but seems to clip)
    # -p is pitch 0 to 99 default 50
    strX = "espeak -g " + str(gap) + " -s 150 -a 150 -p 60 " + dquote + text + dquote
    os.system(strX)

    # It takes a little while to empty the sound buffer
    time.sleep(1)

    # Disconnect the speaker to avoid the crackle
    GPIO.output(CONST.RELAY_SPKR, 1)


def startWeighing() :

    global board 
    global _triggerTimeout
    global _user
    global _blnStartWeighing

    if _user != CONST.USER_NONE :

        if startWeighing.Asleep == True :

            # Get power on to the WiiFit board
            GPIO.output(CONST.RELAY_WII_PWR, 0)
            # The power dips slightly for a brief period, so do nothing to minimize the current...            
            time.sleep(2.0)

            displayString("WAIT")
            labelS.configure(text="PLEASE WAIT")
            root.update()

            startWeighing.Asleep = False

            strX = "hold on a second please "
            if _user == CONST.USER_MARK :
                strX  += "mark" 
            if _user == CONST.USER_TRACEY :
                strX  += "tracey" 
            speakMe(strX, 1)

            _processor.resetw()
            board = Wiiboard(_processor)
            print ("Discovering board...")
            wiAddress = board.discover()

            try:
                # Disconnect already-connected devices.
                # This is basically Linux black magic just to get the thing to work.
                subprocess.check_output(["bluez-test-input", "disconnect", wiAddress], stderr=subprocess.STDOUT)
                subprocess.check_output(["bluez-test-input", "disconnect", wiAddress], stderr=subprocess.STDOUT)
            except:
                pass

            print ("Trying to connect...")
            # The wii board must be in sync mode at this time
            if board.connect(wiAddress) == 1 :
                board.wait(200)
                # Flash the LED so we know we can step on.
                board.setLight(False)
                board.wait(500)
                board.setLight(True)

                displayString("STEP")
                labelS.configure(text="STEP ON NOW")
                root.update()
                speakMe("step on now please", 1)
                _blnStartWeighing = True
            else :
                displayString("----")
                labelS.configure(text="WII BOARD NOT FOUND")
                root.update()
                speakMe("we board not found", 1)

            getWiiInfo()
    else :
        if startWeighing.Asleep == False :
            startWeighing.Asleep = True
            print("disconnect")
            board.disconnect()
            GPIO.output(CONST.RELAY_WII_PWR, 1)
        displaySleepMode()

    if _triggerTimeout > 0 :
        _triggerTimeout -= 1
        if _triggerTimeout == 0 :
            # If no-one steps on the board within 60s of activation, then close the board
            _user = CONST.USER_NONE
            speakMe("bye bye", 1)
            labelS.configure(text="PRESS BUTTON")
            labelW.configure(text="--st --lb --oz\r--kg\rBMI = --.- (-----------)")
            root.update()

    root.after(500, startWeighing)

# Start of main()

display = AlphaNum4.AlphaNum4(address=0x70, busnum=1)
# Initialize the display. Must be called once before using the display.
display.begin()

displayString("----")

root=Tk()

displayWorking.Count = 0
displaySleepMode.Count = 0

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(CONST.RELAY_WII, GPIO.OUT)
GPIO.output(CONST.RELAY_WII, 1)
GPIO.setup(CONST.RELAY_SPKR, GPIO.OUT)
GPIO.output(CONST.RELAY_SPKR, 0)
GPIO.setup(CONST.BUTTON_MARK, GPIO.IN)
GPIO.setup(CONST.BUTTON_TRACEY, GPIO.IN)
GPIO.setup(CONST.RELAY_WII_PWR, GPIO.OUT)
GPIO.output(CONST.RELAY_WII_PWR, 1)

GPIO.add_event_detect(CONST.BUTTON_MARK, GPIO.FALLING)
GPIO.add_event_callback(CONST.BUTTON_MARK, buttonMARK)
GPIO.add_event_detect(CONST.BUTTON_TRACEY, GPIO.FALLING)
GPIO.add_event_callback(CONST.BUTTON_TRACEY, buttonTRACEY)

root.title("Pi Weigher")
labelW=Label(root, text="--st --lb --oz\r--kg\rBMI = --.- (-----------)", bg="red", fg="black")
labelW.configure(font=("Courier", 50))
labelW.grid(row=1, column=0, rowspan=1)

labelS=Label(root, text="PRESS BUTTON", fg="black")
labelS.configure(font=("Courier", 50))
labelS.grid(row=2, column=0, rowspan=1, pady=5)

btnExit=Button(root, text="Exit", width=30)
btnExit.bind('<Button-1>', stopProg)
btnExit.grid(row=3, column=0, columnspan=1, pady=1)

center(root)
root.update()

_processor = EventProcessor()

checkForNewDay.thisDay = -1
checkForNewDay()

startWeighing.Asleep = True
startWeighing()

root.mainloop()

