import os
import logging
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

from server import app as application
