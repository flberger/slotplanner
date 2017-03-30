"""A web app to manage a barcamp slot plan.

   Copyright (c) 2017 Florian Berger <florian.berger@posteo.de>
"""

# This file is part of slotplan.
#
# slotplan is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# slotplan is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with slotplan.  If not, see <http://www.gnu.org/licenses/>.

# Work started on 29. Mar 2017.

import logging
import cherrypy

VERSION = "0.1.0"

LOGGER = logging.getLogger("slotplan")
LOGGER.setLevel(logging.DEBUG)
STDERR_FORMATTER = logging.Formatter("slotplan [{levelname}] {funcName}(): {message} (l.{lineno})", style = "{")
STDERR_HANDLER = logging.StreamHandler()
STDERR_HANDLER.setFormatter(STDERR_FORMATTER)
LOGGER.addHandler(STDERR_HANDLER)

PORT = 8311
THREADS = 10
AUTORELOAD = False


class SlotplanWebApp:
    """Slotplan main class, suitable as cherrypy root.

       All data is stored in SlotplanWebApp.slotplan_db, which is
       a nested data structure designed for easy JSON serialisation
       an deserialisation:

       slotplan_db =
       {
       "contributions":
           {ID:
               {"first_name": FIRST_NAME,
                "last_name": LAST_NAME,
                "title": TITLE,
                "twitter_handle": TWITTER_HANDLE,
                "email": EMAIL,
                "abstract": ABSTRACT
               },
            ...
           },
       "slot_dimension_names":
           [
               [FIRST_1, FIRST_2],
               [SECOND_1, SECOND_2],
               ...
           ],
       "schedule":
           {FIRST_1:
               {SECOND_1: ID,
                SECOND_2: ID,
                ...
               },
            FIRST_2:
               {SECOND_1: ID,
                SECOND_2: ID,
                ...
               },
            ...
           }
       }
    """

    def __init__(self):
        """Initialise SlotplanWebApp.
        """

        self.slotplan_db = {"contributions": {},
                            "slot_dimension_names": [],
                            "schedule": {}
                           }

        # Make self.__call__ visible to cherrypy
        #
        self.exposed = True

        return

    def __call__(self):
        """Called by cherrypy for the / root page.
        """

        return '<html><head><title>Hello World</title></head><body><h1>Hello World</h1><p><a href="/subpage">Go to subpage</a></p></body></html>'

    def subpage(self):

        return '<html><head><title>Hello World Subpage</title></head><body><h1>Hello World Subpage</h1><p><a href="/">Go to main page</a></p></body></html>'

    subpage.exposed = True

def main():
    """Main function, for IDE convenience.
    """

    root = SlotplanWebApp()

    config_dict = {"/" : {"tools.sessions.on" : True,
                          "tools.sessions.timeout" : 60},
                   "global" : {"server.socket_host" : "0.0.0.0",
                               "server.socket_port" : PORT,
                               "server.thread_pool" : THREADS}}

    # Conditionally turn off Autoreloader
    #
    if not AUTORELOAD:

        cherrypy.engine.autoreload.unsubscribe()

    cherrypy.quickstart(root, config = config_dict)

    return

if __name__ == "__main__":

    main()
