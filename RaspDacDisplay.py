import Winstar_GraphicOLED
import moment
import time
import json
import logging
import commands
from mpd import MPDClient
import telnetlib
import RPi.GPIO as GPIO
import Queue
import math
from threading import Thread
import signal
import sys
import sqlite3
import subprocess
sys.stdout.flush()

STARTUP_MSG = "Jim Industries\n"

WAIT_TIME = 4 # Amount of time to hesitate before scrolling (in seconds)

# The Winstar display shipped with the RaspDac is capable of two lines of display
# when the 5x8 font is used.  This code assumes that is what you will be using.
# The display logic would need significant rework to support a different number
# of display lines!

DISPLAY_WIDTH = 16 # the character width of the display
DISPLAY_HEIGHT = 2 # the number of lines on the display

# This is where the log file will be written
LOGFILE='/var/log/drDisplay.log'

# Adjust this setting to localize the time display to your region
TIMEZONE="Pacific/Auckland"
TIME24HOUR=True
#TIMEZONE="Europe/Paris"

# Logging level
#LOGLEVEL=logging.DEBUG
LOGLEVEL=logging.INFO
#LOGLEVEL=logging.WARNING
#LOGLEVEL=logging.CRITICAL

class RaspDac_Display:
        def __init__(self):
                logging.info("RaspDac_Display Initializing")

                # Initilize the connections to the music Daemons.  Currently supporting
                # MPD and SPOP (for Spotify)

                ATTEMPTS=3
                # Will try to connect multiple times

                for i in range (1,ATTEMPTS):
                        self.client = MPDClient(use_unicode=True)

                        try:
                                # Connect to the MPD daemon
                                self.client.connect("localhost", 6600)
                                break
                        except:
#                               logging.warning("Connection to MPD service attempt " + str(i) + " failed")
                                time.sleep(2)
                else:
                        # After the alloted number of attempts did not succeed in connecting
                        logging.debug("Unable to connect to MPD service on startup")

                # Now attempting to connect to the Spotify daemon
                # This may fail if Spotify is not configured.  That's ok!
                for i in range (1,ATTEMPTS):
                        try:
                                self.spotclient = telnetlib.Telnet("localhost",6602)
                                self.spotclient.read_until("\n")
                                break
                        except:
#                               logging.warning("Connection to Spotify service attempt " + str(i) + " failed")
                                time.sleep(2)
                else:
                        # After the alloted number of attempts did not succeed in connecting
                        logging.debug("Unable to connect to Spotify service on startup")

                for i in range (1,ATTEMPTS):
                        try:
                                #code to "connect" to shairport-sync-metadata
                                break
                        except:
#                               logging.warning("Shairport-sync metadata file doesn't exist failed")
                                time.sleep(2)
                else:
                        # After the alloted number of attempts did not succeed in connecting
                        logging.debug("Unable to connect to Shairport-sync metadata service on startup")


        def status_mpd(self):
                # Try to get status from MPD daemon

                try:
                        m_status = self.client.status()
                        m_currentsong = self.client.currentsong()
                except:
                        # Attempt to reestablish connection to daemon
                        try:
                                self.client.connect("localhost", 6600)
                                m_status=self.client.status()
                                m_currentsong = self.client.currentsong()
                        except:
                                logging.debug("Could not get status from MPD daemon")
                                return { 'state':u"notrunning", 'artist':u"", 'title':u"", 'current':0, 'duration':0 }

                state = m_status.get('state')
                if state == "play":
                  artist = m_currentsong.get('artist')
                  name = m_currentsong.get('name')

                  # Trying to have something to display.  If artist is empty, try the
                  # name field instead.
                  if artist is None:
                        artist = name
                  title = m_currentsong.get('title')

                  (current, duration) = (m_status.get('time').split(":"))

                  # since we are returning the info as a JSON formatted return, convert
                  # any None's into reasonable values
                  if artist is None: artist = u""
                  if title is None: title = u""
                  if current is None: current = 0
                  if duration is None: duration = 0
                  return { 'state':state, 'artist':artist, 'title':title, 'current':current, 'duration': duration }
                else:
                  return { 'state':u"stop", 'artist':u"", 'title':u"", 'current':0, 'duration':0 }

        def status_spop(self):
                # Try to get status from SPOP daemon

                try:
                        self.spotclient.write("status\n")
                        spot_status_string = self.spotclient.read_until("\n").strip()
                except:
                        # Try to reestablish connection to daemon
                        try:
                                self.spotclient = telnetlib.Telnet("localhost",6602)
                                self.spotclient.read_until("\n")
                                self.spotclient.write("status\n")
                                spot_status_string = self.spotclient.read_until("\n").strip()
                        except:
                                logging.debug("Could not get status from SPOP daemon")
                                return { 'state':u"notrunning", 'artist':u"", 'title':u"", 'current':0, 'duration':0 }

                spot_status = json.loads(spot_status_string)

                if spot_status.get('status') == "playing":
                        artist = spot_status.get('artist')
                        title = spot_status.get('title')
                        current = spot_status.get('position')
                        duration = spot_status.get('duration')

                        # since we are returning the info as a JSON formatted return, convert
                        # any None's into reasonable values

                        if artist is None: artist = u""
                        if title is None: title = u""
                        if current is None: current = 0
                        if duration is None:
                                duration = 0
                        else:
                                # The spotify client returns time in 1000's of a second
                                # Need to adjust to seconds to be consistent with MPD
                                duration = duration / 1000

                        return { 'state':u"play", 'artist':artist, 'title':title, 'current':current, 'duration': duration }
                else:
                        return { 'state':u"stop", 'artist':u"", 'title':u"", 'current':0, 'duration':0 }

        def status_shairport(self):
                #get status from airplay daemon
                #only noting if it is playing or not for now
                try:
                        sqlite_file="/var/local/www/db/moode-sqlite3.db"
                        conn = sqlite3.connect(sqlite_file)
                        c = conn.cursor()
                        c.execute("SELECT value FROM cfg_system WHERE param='airplayactv'")
                        row = c.fetchone()

                        if row[0] == "1":
                                        state = "airplay"
                        elif row[0] == "0":
                                        state = "stop"
                except:
                        # Something is broken, make a note:
                        logging.debug("Can't reach moode db to probe airplay state")

                return { 'state':state, 'artist':u"", 'title':u"", 'current':0, 'duration': 0 }

        def status(self):

                # Try MPD daemon first
                status = self.status_mpd()

                # If MPD is stopped
                if status.get('state') != "play":

                        # Try SPOP
                        #status = self.status_spop()

                        #actually no, we will try get the status of shairplay-sync
                        status = self.status_shairport()
                return status

def Display(q, l, c):
        # q - Queue to receive updates from
        # l - number of lines in display
        # c - number of columns in display

        lines = []
        columns = []

        lcd = Winstar_GraphicOLED.Winstar_GraphicOLED()
        lcd.oledReset()
        lcd.home()
        lcd.clear()

        lcd.message(STARTUP_MSG)
        time.sleep(1)

        for i in range (0, l):
                lines.append("")
                columns.append(0)

        # Get first display update off of the queue
        item = q.get()
        q.task_done()

        lcd.home()
        lcd.clear()

        for i in range(len(item)):
                # Convert from Unicode to UTF-8
                item[i] = item[i].encode("utf-8")
                lines[i] = item[i]
                lcd.setCursor(0,i)
                lcd.message( lines[i][0:c] )

        time.sleep(WAIT_TIME)
        prev_time = time.time()

        while True:
                short_lines=True

                # Smooth animation
                if time.time() - prev_time < .20:
                        time.sleep(.20-(time.time()-prev_time))

                try:
                # Determine if any lines have been updated and if yes display them
                        for i in range(len(item)):
                                #print("string length: ", len(item[i]))
                                #print("on: ", i)
                                # Convert from Unicode into UTF-8
                                # item[i] = item[i].encode("utf-8")
                                # Check if line is longer than display
                                if len(item[i])>c:
                                        short_lines = False

                                # Check if line has been updated
                                if lines[i] != item[i]:
                                        # Create a line to print that is at least as long as the existing line
                                        # This is to erase any extraneous characters on the display
                                        buf = item[i].ljust(len(lines[i]))

                                        # Reset cursor to beginning of changed line and then display the change
                                        lcd.setCursor(0,i)
                                        lcd.message(buf[0:c])

                                        # Update the local line data and reset the column position for the line
                                        lines[i] = item[i]
                                        columns[i] = 0

                                # If lines all fit on display then we can wait for new input
                                if short_lines:
                                        item=q.get()
                                        q.task_done()
                                else:
                                        # Update all long lines
                                        for i in range(len(lines)):
                                                if len(lines[i])>c:
                                                        buf = "%s                                       %s" % (lines[i], lines[i][0:DISPLAY_WIDTH-1])
                                                        #buf = "{}              {}".format(lines[i],lines[i][0:DISPLAY_WIDTH-1])
                                                        #buf = lines[i]+"                       "+lines[i][0:c]

                                                        columns[i] = columns[i]+1
                                                        if columns[i] > len(buf)-c:
                                                                columns[i]=0

                                                        lcd.setCursor(0,i)

                                                        # Print the portion of the string that is currently visible
                                                        lcd.message(buf[columns[i]:columns[i]+c])


                                        # Since we have to continue updating the display, check for a new update but don't block
                                        item=q.get_nowait()
                                        q.task_done()

                                if i == len(item):
                                        time.sleep(WAIT_TIME)
                                prev_time = time.time()

                except Queue.Empty:
                        prev_time = time.time()
                        pass

def sigterm_handler(_signo, _stack_frame):
        sys.exit(0)

if __name__ == '__main__':
        signal.signal(signal.SIGTERM, sigterm_handler)
        logging.basicConfig(format='%(asctime)s:%(levelname)s:%(message)s', filename=LOGFILE, level=LOGLEVEL)
        logging.info("RaspDac Display Startup")

        try:
                dq = Queue.Queue()  # Create display Queue
                dm = Thread(target=Display, args=(dq,DISPLAY_HEIGHT,DISPLAY_WIDTH))
                dm.setDaemon(True)
                dm.start()

                rd = RaspDac_Display()
        except:
                #e = sys.exc_info()[0]
                #logging.critical("Received exception: %s" % e)
                logging.critical("Unable to initialize RaspDac Display.  Exiting...")
                sys.exit(0)

        try:
                beenplaying = True
                currentArtist = ""
                currentTitle = ""

                needtotoggle_artist = False
                needtotoggle_title = False
                togglestate = True

                hesitate = False
                wait_until = 0
                wait_until = time.time() + WAIT_TIME

                currentscreen = 0

                while True:
                        cstatus = rd.status()
                        state = cstatus.get('state')

                        if state == "play":
                                #title = cstatus.get('title')[0:16]
                                #artist = cstatus.get('artist')[0:16]
                                #dq.put([artist, title])
                                output = "moOde"
                                dq.put([output.center(DISPLAY_WIDTH),""])
                                time.sleep(1)


                        elif state == "airplay":
                                output = "AirPlay"
                                dq.put([output.center(DISPLAY_WIDTH),""])
                                time.sleep(1)

                        elif state == "stop":
                                if beenplaying:
                                        beenplaying = False
                                        currentArtist = ""
                                        currentTitle = ""
                                dq.put(["",""])
                                time.sleep(1)

        except KeyboardInterrupt:
                pass

        finally:
                dq.put(["",""])
                logging.info("Goodbye!")
                try:
                        rd.client.disconnect()
                except:
                        pass
                try:
                        rd.spotclient.write("bye\n")
                        rd.spotclient.close()
                except:
                        pass

                time.sleep(3)
                GPIO.cleanup()
