from pathlib import Path
import sys


plugin_dir = str(Path(__file__).resolve().parent)
if plugin_dir not in sys.path:
	sys.path.insert(0, plugin_dir)

from bn_theme_studio import *
