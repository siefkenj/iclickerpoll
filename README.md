iClickerPoll
============

iClickerPoll is a Python interface to the iClicker base unit.
It should be compatible with an operating system that supports
libusb, and in particular, GNU/Linux.


Requirements
------------

* Python 2.x/3.x
* pyusb


Usage
-----

To start a poll, run iclickerpoll.py with the desired arguments.
For example:


    ./iclickerpoll.py --type alpha --dest polldata.csv

To stop the poll, use Ctrl+C to terminate iclickerpoll.py.  At
this point, iclickerpoll.py will send the closing sequence to
the iclicker base station and save any data if requested (with --dest).

Full options:


     optional arguments:
      -h, --help            show this help message and exit
      --debug               Display debug information about the USB transactions
      --type TYPE           Sets the poll type to alpha, numeric, or alphanumeric
      --duration DURATION   Sets the duration of the poll in minutes and seconds.
                            0m0s is unlimited.
      --dest DEST           Sets the file to save polling data to.
      --frequency FREQUENCY
                            Sets the two base-station frequency codes. Should be
                            formatted as two letters (e.g., 'aa' or 'ab')

