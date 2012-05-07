#!/usr/bin/python
from __future__ import print_function

from usb import USBError
import usb.core, usb.util
from array import array
from collections import defaultdict, Counter
import logging, time, sys
import threading

log = logging.getLogger(__name__)


class Command(object):
    def __init__(self, byte_array=None):
        if byte_array is None:
            byte_array = []

        if type(byte_array) is str:
            # If we passed in a string, assume it is a string of hex characters and turn it into bytes
            byte_array = byte_array.replace(' ', '')
            byte_array = array('B', (int(byte_array[i:i+2], 16) for i in range(0, len(byte_array), 2)))
        elif type(byte_array) is bytes:
            pass
        # Make sure we have a 64 byte packet by padding with zeros
        self.bytes = array('B', byte_array[:64])
        self.bytes.extend([0]*(64-len(self.bytes)))

    def __getitem__(self, key):
        return self.bytes[key]

    def __setitem__(self, key, value):
        self.bytes[key] = valuse

    def __repr__(self):
        """ return the command as a hex string """
        SPLIT_BY_N_CHARS = 16
        hex_string = ''.join("%02X" % x for x in self.bytes)
        return ' '.join(hex_string[i:i+SPLIT_BY_N_CHARS] for i in range(0, len(hex_string), SPLIT_BY_N_CHARS)).lower()

    def __eq__(self, other):
        return self.bytes == other.bytes
    
    def __ne__(self, other):
        return self.bytes != other.bytes

    def as_bytes(self):
        return self.bytes.tostring()

    @staticmethod
    def clicker_id_from_bytes(byte_seq):
        """ Given a sequence of three bytes, computes the last byte
        in the clicker id and returns it as hex """
        # Make a copy since we'll be appending to it
        byte_seq = byte_seq[:]
        byte_seq.append(byte_seq[0] ^ byte_seq[1] ^ byte_seq[2])

        return ''.join("%02X" % b for b in byte_seq)

    def _process_alpha_clicker_response(self):
        """ This method will return information about an alpha clicker response """
        ret = {'type': 'ClickerResponse', 'poll_type': 'Alpha'}
        ret['clicker_id'] = self.clicker_id_from_bytes(self.bytes[3:6])
        # Responses start with 0x81 for A and work their way up, so ascii-recode them
        ret['response'] = chr(self.bytes[2] - 0x81 + 65)
        ret['seq_num'] = self.bytes[6]
        
        return ret

    def info(self):
        """ return all the information we know about the command """
        byte0 = self.bytes[0]
        byte1 = self.bytes[1]
        ret = { 'type': 'unknown', 'raw_command': self.__repr__() }
        if byte0 == 0x01:
            if byte1 == 0x10:
                ret['type'] = 'SetFrequency'
                ret['freq1'] = self.bytes[2] - 0x21
                ret['freq2'] = self.bytes[3] - 0x41
            if byte1 == 0x11:
                ret['type'] = 'StartPolling'
            if byte1 == 0x12:
                ret['type'] = 'StopPolling'
            if byte1 == 0x18:
                if self.bytes[2] == 0x01 and self.bytes[3] == 0x00:
                    ret['type'] = 'ResetBase'
            if byte1 == 0x19:
                ret['type'] = 'SetPollType'
                ret['quiz_type'] = self.bytes[2] - 0x67
            if byte1 == 0x2d:
                ret['type'] = 'SetIClicker2Protocol'
        elif byte0 == 0x02:
            if byte1 == 0x13:
                ret.update(self._process_alpha_clicker_response())
            if byte1 == 0x1a:
                pass

        return ret

    def response_info(self):
        """ Returns a list containing every response in this command.
        Since a 64 byte command can contain two 32 byte clicker responses,
        this separates them and returns a list with both their infos """
        info1 = Command(self.bytes[:32]).info()
        info2 = Command(self.bytes[32:]).info()
        ret = []
        if info1['type'] == 'ClickerResponse':
            ret.append(info1)
        if info2['type'] == 'ClickerResponse':
            ret.append(info2)

        return ret
        

class IClickerBase(object):
    """ This class handles all the hardware-related aspects of talking
    with the iClicker base unit. """
    VENDOR_ID = 0x1881
    PRODUCT_ID = 0x0150
    def __init__(self):
        self.device = None
        self.last_set_screen_time = 0
        self.has_initialized = False
        # pyusb is not threadsafe, so we need to aquire a lock for all usb operations
        self.usb_lock = threading.RLock()
        self.screen_buffer = [' '*16, ' '*16]
        self.screen_queue = [False, False] # A list of which line of the screen needs to be updated

    def _write(self, data):
        """ raw-write of data to self.device"""
        with self.usb_lock:
            self.device.ctrl_transfer(0x21, 0x09, 0x0200, 0x0000, data.as_bytes())

    def _read(self, timeout=100):
        """ read a packet of data from self.device"""
        with self.usb_lock:
            ret = Command(self.device.read(0x83, 64, timeout=timeout))
        return ret

    def _syncronous_write(self, data, timeout=100):
        """ writes data to self.device expecting a reponse of "?? ?? aa"
        where "?? ??" are the first two bytes of data """
        expected_response = Command([data[0], data[1], 0xaa])
        self._write(data)
        response = self._read(timeout=timeout)
        if response != expected_response:
            raise IOError("Attempted syncronuous write of {0} and got {1} (expecting {2})".format(data.__repr__(), response.__repr__(), expected_response.__repr__()))
    def _write_command_sequence(self, seq):
        """ Write a sequence of commands to the usb device and read all the responses """
        for cmd in seq:
            self._write(cmd)
            try:
                while True:
                    response = self._read()
            except USBError:
                pass

    def read(self, timeout=100):
        try:
            return Command(self._read(timeout))
        except:
            return None
        
    def get_base(self):
        """ Looks on the USB bus for an iClicker device """
        with self.usb_lock:
            self.device = usb.core.find(idVendor=self.VENDOR_ID, idProduct=self.PRODUCT_ID)

            if self.device is None:
                raise ValueError('Error: no iclicker device found')
            
            if self.device.is_kernel_driver_active(0):
                log.warning("The iClicker seems to be in use by another device--Forcing reattach.")
                self.device.detach_kernel_driver(0)
        
            self.device.set_configuration()

    def set_base_frequency(self, code1='a', code2='a'):
        """ Sets the operating frequency """
        def code_to_number(code):
            if type(code) is str:
                # 'a' == 1, 'b' == 2, etc.
                return ord(code.lower()) - 97
            return code

        time.sleep(0.2)
        cmd = Command([0x01, 0x10, 0x21 + code_to_number(code1), 0x41 + code_to_number(code2)])
        self._syncronous_write(cmd)
        time.sleep(0.2)
        cmd = Command([0x01, 0x16])
        self._syncronous_write(cmd)
        time.sleep(0.2)

    def set_version_two_protocol(self):
        """ Sets the base unit to use the iClicker version 2 protocol """
        cmd = Command([0x01, 0x2d])
        self._write(cmd)
        time.sleep(0.2)

    def set_poll_type(self, poll_type='alpha'):
        """ Sets the poll type to 'alpha', 'numeric', or 'alphanumeric' """
        log.debug('Setting poll type to {0}'.format(poll_type))

        poll_type = {'alpha': 0, 'numeric': 1, 'alphanumeric': 2}[poll_type]
        cmd = Command([0x01, 0x19, 0x66+poll_type, 0x0a, 0x01])
        self._write(cmd)
        time.sleep(0.2)

    #TODO: There are still a lot of unknowns here...right now
    # it just repeates what was snooped from USB on Windows
    def initialize(self, freq1='a', freq2='a'):
        COMMAND_SEQUENCE_A = [
            Command("01 2a 21 41 05"),
            Command("01 12"),
            Command("01 15"),
            Command("01 16"),
            ]
        
        COMMAND_SEQUENCE_B = [
            Command("01 29 a1 8f 96 8d 99 97 8f"),
            Command("01 17 04"),
            Command("01 17 03"),
            Command("01 16"),
            ]

        if self.device is None:
            self.get_base()

        self.set_base_frequency(freq1, freq2)
        self._write_command_sequence(COMMAND_SEQUENCE_A)
        self.set_version_two_protocol()
        self._write_command_sequence(COMMAND_SEQUENCE_B)
        self.has_initialized = True

    def start_poll(self, poll_type='alpha'):
        COMMAND_SEQUENCE_A = [
            Command("01 17 03"),
            Command("01 17 05"),
            ]
        command_START_POLL = Command("01 11")
        
        self._write_command_sequence(COMMAND_SEQUENCE_A)
        self.set_poll_type(poll_type)
        self._write(command_START_POLL)
    
    def stop_poll(self):
        COMMAND_SEQUENCE_A = [
            Command("01 12"),
            Command("01 16"),
            Command("01 17 01"),
            Command("01 17 03"),
            Command("01 17 04"),
            ]
        
        self._write_command_sequence(COMMAND_SEQUENCE_A)
    
    def _set_screen(self, line=0):
        """ Sets the line @line to the characters specified by self.screen_buffer[line].
        This command messes up the screen if it is sent too frequently. """
        if line == 0:
            cmd = [0x01, 0x13]
        else:
            cmd = [0x01, 0x14]

        # Make sure we are writing only 16 characters to the screen
        string = self.screen_buffer[line]
        string = string[:16]
        string = string + ' '*(16-len(string))
        cmd.extend(ord(c) for c in string)
        cmd = Command(cmd)
        
        self.last_set_screen_time = time.time()
        
        self._write(cmd)

    def set_screen(self, string, line=0, force_update=False):
        """ Sets the line @line to the characters specified by @string.
        This command messes up the screen if it is sent too frequently,
        so an automatic delay is added between issuances of set_screen """
        MIN_SCREEN_UPDATE_TIME = 0.1
        
        # Set our buffer to the appropriate string, and if our buffer hasn't
        # changed, just exit--we don't even need to update the screen
        if string == self.screen_buffer[line] and force_update is False:
            return

        self.screen_buffer[line] = string
        self.screen_queue[line] = True
        
        def process_screen_queue(line):
            # if the screenqueue is false, it means another thread already handled updating
            # the screen for us
            if self.screen_queue[line] is False:
                return
            # Make sure we don't send two write commands too frequently.
            # If we have tried to send a command too recently, start a 
            curr_time = time.time()
            if curr_time - self.last_set_screen_time < MIN_SCREEN_UPDATE_TIME:
                delay_duration = (MIN_SCREEN_UPDATE_TIME - (curr_time - self.last_set_screen_time))
                timer = threading.Timer(delay_duration, process_screen_queue, [line])
                timer.start()
                return

            # If the last write wasn't too recent, let's do it!
            self.screen_queue[line] = False
            self._set_screen(line)
        
        process_screen_queue(line)

class Response(object):
    """ Keeps track of all relavent information about a clicker response """
    def __init__(self, clicker_id=None, response=None, click_time=None, seq_num=None, command=None):
        if click_time is None:
            self.click_time = time.time()
        else:
            self.click_time = click_time

        if command is not None:
            pass
        self.clicker_id = clicker_id
        self.response = response
        self.seq_num = seq_num

    def __eq__(self, other):
        if type(other) is Response:
            return self.clicker_id == other.clicker_id and self.response == other.response and self.seq_num == other.seq_num
        else:
            return False

    def __ne__(self, other):
        if type(other) is Response:
            return self.clicker_id != other.clicker_id or self.response != other.response or self.seq_num != other.seq_num
        else:
            return True

    def __repr__(self):
        return "{0}: {1} ({2} at {3})".format(self.clicker_id, self.response, self.seq_num, self.click_time)
    
class IClickerPoll(object):
    def __init__(self, iclicker_base):
        self.base = iclicker_base
        self.STOP_POLL = False
        self.should_print = True
        self.poll_start_time = 0
        self.responses = defaultdict(list)

    def update_display(self):
        """ updates the base display according to the poll results """
        
        # Write the distribution of votes to the second line of the display
        out_string = " 0  0  0  0  0 "
        recent_responses = self.get_most_recent_responses()
        tally = Counter(r.response for r in recent_responses if r.response != 'F') #'F' means retract answer
        if len(tally) > 0:
            total = sum(tally.values())
            out_string = "{0} {1} {2} {3} {4}".format(int(100*tally['A']/total),
                                                      int(100*tally['B']/total),
                                                      int(100*tally['C']/total),
                                                      int(100*tally['D']/total),
                                                      int(100*tally['E']/total))
        self.base.set_screen(out_string, line=1)

        # Write the time and number of total votes to the first line of the display
        secs = int(time.time() - self.poll_start_time)
        mins = secs // 60
        secs = secs % 60

        out_string_time = "{0}:{1:02}".format(mins, secs)
        out_string = "{0}{1:>{padding}}".format(out_string_time, sum(tally.values()), padding=(16-len(out_string_time)))
        self.base.set_screen(out_string, line=0)

    def start_poll(self, poll_type='alpha'):
        """ Starts a poll and then starts watching input """

        if not self.base.has_initialized:
            self.base.initialize()

        self.STOP_POLL = False
        self.poll_start_time = time.time()
        self.poll_type = poll_type
        self.base.start_poll(poll_type)

        # This blocks until self.STOP_POLL is set to true
        self.watch_input()

        # After watch input exits, we want to stop the poll
        self.stop_poll()
        
    def stop_poll(self):
        self.STOP_POLL = True
        self.base.stop_poll()

    def watch_input(self):
        """ Constantly polls the usb device for clicker responses """

        self.display_update_loop()
        while self.STOP_POLL is False:
            response = self.base.read(50)
            # if there is no response, do nothing but update the display
            if response is None:
                continue
            for info in response.response_info():
                self.add_response(Response(info['clicker_id'], info['response'],
                                           time.time(), info['seq_num']))
            self.update_display()

    def display_update_loop(self, interval=1):
        """ Spawns a new thread and updates the display every @interval
        number of seconds """

        def update():
            while self.STOP_POLL is False:
                self.update_display()
                time.sleep(interval)

        display_thread = threading.Thread(target=update)
        display_thread.start()

    def add_response(self, response):
        """ Adds a response to the response list """
        if response not in self.responses[response.clicker_id]:
            self.responses[response.clicker_id].append(response)
            self.print_response(response)

    def get_most_recent_responses(self):
        """ returns a list of the most recent responses """
        return [self.responses[key][-1] for key in self.responses.keys()]

    def get_most_recent_responses_formatted(self):
        """ returns a csv formatted string containing all the responses for
        each clicker ID """
        
        recent_responses = self.get_most_recent_responses()
        out = ['{0},{1}'.format(r.clicker_id, r.response) for r in recent_responses]
        return '\n'.join(out)

    def print_response(self, response):
        if self.should_print:
            print(response)


# This is a callback that stops the poll, since start a poll is a blocking operation
def close_pole(poll):
    print("Stopping Poll")
    poll.stop_poll()

if __name__ == '__main__':
    import signal, argparse

    parser = argparse.ArgumentParser(description='Start an iClicker poll')
    parser.add_argument('--debug', action='store_true', default=False,
                        help='Display debug information about the USB transactions')
    parser.add_argument('--type', type=str, default='alpha',
                        help='Sets the poll type to alpha, numeric, or alphanumeric')
    parser.add_argument('--duration', type=str, default='100m0s',
                        help='Sets the duration of the poll in minutes and seconds. 0m0s is unlimited.')
    parser.add_argument('--dest', type=str, default='',
                        help='Sets the file to save polling data to.')
    parser.add_argument('--frequency', type=str, default='aa',
                        help='Sets the two base-station frequency codes. Should be formatted as two letters (e.g., \'aa\' or \'ab\')')

    args = parser.parse_args()

    #
    # Process all the arguments
    #

    if args.debug:
        log.setLevel(0)
    if args.type in ['alpha', 'numeric', 'alphanumeric']:
        poll_type = args.type
    else:
        raise ValueError("Poll type must be 'alpha', 'numeric', or 'alphanumeric', not '{0}'".format(args.type))
    if args.duration:
        poll_duration = 1000
    if args.frequency:
        freq1 = args.frequency[0].lower()
        freq2 = args.frequency[1].lower()
        if freq1 not in ('a', 'b', 'c', 'd') or freq2 not in ('a', 'b', 'c', 'd'):
            raise ValueError("Frequency combintation '{0}{1}' is not valid".format(freq1, freq2))
    

    #
    # Initiate the polling
    #
    print('Finding iClicker Base')
    base = IClickerBase()
    base.get_base()
    print('Initializing iClicker Base')
    base.initialize(freq1, freq2)
        
    # If we have successfully started a poll, set up a signal handler
    # to clean up when we get a SIGINT (ctrl+c or kill) command
    poll = IClickerPoll(base)
    signal.signal(signal.SIGINT, lambda *x: close_pole(poll))
    # Set a callback to stop the poll after the desired amount of time
    if poll_duration:
        stop_timer = threading.Timer(poll_duration, lambda *x: close_pole(poll))
        stop_timer.start()
    print('Poll Started')
    poll.start_poll(poll_type)

    # If we made it this far and stop_timer wasn't triggered, we were asked to stop another
    # way, so we should stop the stop_timer
    stop_timer.cancel()
    if args.dest:
        file_name = args.dest
        print('Writing results to {0}'.format(file_name))
        with open(file_name, 'w') as out_file:
            out_file.write(poll.get_most_recent_responses_formatted())
