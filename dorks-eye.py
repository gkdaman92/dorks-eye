#!/usr/bin/env python3
# This Python file uses the following encoding: utf-8

# ===== #
#   
# ▀█████████▄     ▄████████         Websites: HackingPassion.com | Bullseye0.com
#   ███    ███   ███    ███         Author: Jolanda de Koff | Bulls Eye
#   ███    ███   ███    █▀          GitHub: https://github.com/BullsEye0
#  ▄███▄▄▄██▀   ▄███▄▄▄             LinkedIn: https://www.linkedin.com/in/jolandadekoff
# ▀▀███▀▀▀██▄  ▀▀███▀▀▀             Facebook Group: https://www.facebook.com/groups/hack.passion/
#   ███    ██▄   ███    █▄          Facebook: https://www.facebook.com/profile.php?id=100069546190609
#   ███    ███   ███    ███         YouTube: https://www.youtube.com/@HackingPassion
# ▄█████████▀    ██████████         LBRY: https://lbry.tv/$/invite/@hackingpassion:9
#                                   Github Sponsor: https://github.com/sponsors/BullsEye0
#                                   Ethical Hacking Course: https://www.udemy.com/course/ethical-hacking-complete-course-zero-to-expert/?couponCode=DECEMBER25
#          Bulls Eye..!
# ===== #

# ===== #
# Created April | Copyright (c) 2020 Jolanda de Koff.
# Updated October 2025 - Multi Search Engine
# Updated 2026 - v3: SOCKS5/proxy rotation, AI operators (any LLM), MCP server
# ===== #

########################################################################

# A notice to all nerds and n00bs...
# If you will copy the developer's work it will not make you a hacker..!
# Respect all developers, we doing this because it's fun...

########################################################################


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dorkseye.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
