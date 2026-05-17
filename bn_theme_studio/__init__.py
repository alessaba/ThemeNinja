from __future__ import annotations

try:
	from binaryninja import log_error
except ModuleNotFoundError:
	# Allows the non-UI helper module to be imported by local tests outside Binary Ninja.
	pass
else:
	try:
		from .ui import register_plugin

		register_plugin()
	except Exception as exc:
		log_error(f"Theme Ninja failed to load: {exc}")
