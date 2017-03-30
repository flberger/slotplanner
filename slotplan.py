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
import json
import pathlib
import os
import datetime
import simple.email
import simple.html

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

# Make HTML textareas more compact
#
simple.html.ROWS = 8

CSS = """body {
    background: rgb(250, 250, 250) ;
    padding: 1em 12em ;
    }
"""

class SlotplanWebApp:
    """Slotplan main class, suitable as cherrypy root.

       All data is stored in SlotplanWebApp.slotplan_db, which is
       a nested data structure designed for easy JSON serialisation
       an deserialisation:

       slotplan_db =
       {
       "contributions":
           {CONTRIBUTION_ID_STRING:
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
           {INDEX_FIRST_1_AS_STRING:
               {INDEX_SECOND_1_AS_STRING: CONTRIBUTION_ID_STRING,
                INDEX_SECOND_2_AS_STRING: CONTRIBUTION_ID_STRING,
                ...
               },
            INDEX_FIRST_2_AS_STRING:
               {INDEX_SECOND_1_AS_STRING: CONTRIBUTION_ID_STRING,
                INDEX_SECOND_2_AS_STRING: CONTRIBUTION_ID_STRING,
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

        LOGGER.debug("Attempting to read serialised data")

        try:
            with open("slotplan_db.json", "rt", encoding = "utf8") as f:

                self.slotplan_db = json.loads(f.read())

        except:

            LOGGER.info("Error reading database from file, starting fresh")

            # Using already initialised self.slotplan_db

        LOGGER.debug("Attempting to read config")

        self.config = {"__builtins__": None}
        
        try:
            with open("slotplan.conf", "rt", encoding = "utf8") as f:

                # The threat model is that anyone who can access the
                # config can access this source and hence execute
                # arbitrary code anyway.
                #
                exec(f.read(), self.config)
                
        except:
            
            LOGGER.error("Config file slotplan.conf not found. Creating an empty one.")

            with open("slotplan.conf", "wt", encoding = "utf8") as f:

                f.write('event = ""\ncontact_email = ""\n')

            raise
            
        # Make self.__call__ visible to cherrypy
        #
        self.exposed = True

        return

    def __call__(self):
        """Called by cherrypy for the / root page.
        """

        page = simple.html.Page("slotplan - {}".format(self.config["event"]), css = CSS)

        page.append('<h1>Slotplan for {}</h1>'.format(self.config["event"]))

        page.append('<p><a href="/submit">Submit your contribution here!</a></p>')

        return str(page)

    def write(self):
        """Serialise the database to disk.
        """

        if pathlib.Path("slotplan_db.json").exists():

            current_time = datetime.datetime.now()

            # Silently replace any existing backup for this second
            #
            os.replace("slotplan_db.json",
                       "slotplan_db-{}-{}-{}-{}_{}_{}.json".format(current_time.year,
                                                                   current_time.month,
                                                                   current_time.day,
                                                                   current_time.hour,
                                                                   current_time.minute,
                                                                   current_time.second))

        with open("slotplan_db.json", "wt", encoding = "utf8") as f:

            # Write a human-readable, diff- and version
            # control-friendly representation
            #
            f.write(json.dumps(self.slotplan_db,
                               indent = 4,
                               sort_keys = True))

        return

    def test(self):
        """Test various things, e.g. data serialisation.
        """

        LOGGER.debug(self.slotplan_db)

        LOGGER.debug("Overwriting slotplan_db with sample data")

        self.slotplan_db = {"contributions": {},
                            "slot_dimension_names": [],
                            "schedule": {}
                           }

        self.slotplan_db["contributions"]["123"] = {"first_name": "John",
                                                    "last_name": "Doe",
                                                    "title": "My Presentation",
                                                    "twitter_handle": "@invalid",
                                                    "email": "john.doe@some.tld",
                                                    "abstract": "My presenation abstract."
                                                   }

        self.slotplan_db["slot_dimension_names"].append(["Monday", "Tuesday"])
        self.slotplan_db["slot_dimension_names"].append(["Room 1", "Room 2"])
        self.slotplan_db["slot_dimension_names"].append(["Morning", "Afternoon"])

        self.slotplan_db["schedule"]["0"] = {"0": {"1": "123"}}

        self.write()

        return

    def submit(self,
               first_name = None,
               last_name = None,
               email = None,
               twitter_handle = None,
               title = None,
               abstract = None):

        page = simple.html.Page("Sign Up", css = CSS)

        page.append('<h1>Slotplan for {}</h1>'.format(self.config["event"]))
        
        page.append('<h2>Sign up</h2>')

        page.append('<p><a href="/">Back to home page</a></p>')

        form = simple.html.Form("/submit", "POST")

        form.add_fieldset("About you")

        form.add_input("Your first name:", "text", "first_name")
        form.add_input("Your last name:", "text", "last_name")
        form.add_input("Email address you signed up with*:", "text", "email")
        form.add_input("Your Twitter handle (optional):", "text", "twitter_handle", value = "@")

        form.add_fieldset("Contribution Title")
        form.add_textarea("title")

        form.add_fieldset("Contribution Abstract (optional)")
        form.add_textarea("abstract")

        page.append(str(form))

        page.append('<p>*Your email address is required to verify that you are signed up for the event. We will never give it to anyone else.</p>')

        page.append('<p>Questions? Email <a href="mailto:{0}">{0}</a></p>'.format(self.config["contact_email"]))

        return str(page)

    submit.exposed = True

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
